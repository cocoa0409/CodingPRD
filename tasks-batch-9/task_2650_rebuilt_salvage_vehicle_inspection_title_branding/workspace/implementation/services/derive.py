"""Derived-field recomputation and response serialisation.

Every computed field in the program is recomputed from the rows it depends on.
`touch_row=True` (the default inside mutating handlers) refreshes `updated_at`
and bumps `version` when a published value actually changed; reads recompute
silently so a GET never mutates a row.
"""

import db
from services import calc

TERMINAL_APP = set(calc.TERMINAL_APP_STATUSES)
LIVE_INSPECTION = set(calc.LIVE_INSPECTION_STATUSES)


# ------------------------------------------------------------------- selectors


def titles_of_vehicle(vehicle_id):
    return db.ordered([t for t in db.db.titles.values() if t["vehicle_id"] == vehicle_id])


def apps_of_vehicle(vehicle_id):
    return db.ordered([a for a in db.db.applications.values() if a["vehicle_id"] == vehicle_id])


def apps_of_rebuilder(rebuilder_id):
    return db.ordered([a for a in db.db.applications.values() if a["rebuilder_id"] == rebuilder_id])


def docs_of_app(application_id):
    return db.ordered(
        [d for d in db.db.parts_documents.values() if d["application_id"] == application_id]
    )


def docs_of_rebuilder(rebuilder_id):
    app_ids = set(a["id"] for a in apps_of_rebuilder(rebuilder_id))
    return db.ordered(
        [d for d in db.db.parts_documents.values() if d["application_id"] in app_ids]
    )


def inspections_of_app(application_id):
    return db.ordered(
        [i for i in db.db.inspections.values() if i["application_id"] == application_id]
    )


def findings_of_inspection(inspection_id):
    return db.ordered([f for f in db.db.findings.values() if f["inspection_id"] == inspection_id])


def findings_of_app(application_id):
    ids = set(i["id"] for i in inspections_of_app(application_id))
    return db.ordered([f for f in db.db.findings.values() if f["inspection_id"] in ids])


def appeals_of_inspection(inspection_id):
    return db.ordered([a for a in db.db.appeals.values() if a["inspection_id"] == inspection_id])


def appeals_of_app(application_id):
    ids = set(i["id"] for i in inspections_of_app(application_id))
    return db.ordered([a for a in db.db.appeals.values() if a["inspection_id"] in ids])


def referrals_of_vehicle(vehicle_id):
    return db.ordered([r for r in db.db.referrals.values() if r["vehicle_id"] == vehicle_id])


def referrals_of_rebuilder(rebuilder_id):
    app_ids = set(a["id"] for a in apps_of_rebuilder(rebuilder_id))
    return db.ordered(
        [
            r
            for r in db.db.referrals.values()
            if r.get("application_id") and r["application_id"] in app_ids
        ]
    )


def transfers_of_vehicle(vehicle_id):
    rows = []
    for transfer in db.db.transfers.values():
        outgoing = db.db.titles.get(transfer["from_title_id"])
        if outgoing is not None and outgoing["vehicle_id"] == vehicle_id:
            rows.append(transfer)
    return db.ordered(rows)


def transfers_of_chain(title):
    """Conveyances recorded anywhere on this title's chain (same vehicle)."""
    return transfers_of_vehicle(title["vehicle_id"])


def recognitions_of_title(title_id):
    return db.ordered([r for r in db.db.recognitions.values() if r["title_record_id"] == title_id])


def chain_of_title(title):
    """The title itself followed by its predecessor ancestry, root last."""
    chain = []
    seen = set()
    cursor = title
    while cursor is not None and cursor["id"] not in seen:
        chain.append(cursor)
        seen.add(cursor["id"])
        parent_id = cursor.get("predecessor_title_id")
        cursor = db.db.titles.get(parent_id) if parent_id else None
    return chain


# ------------------------------------------------------------ change detection


def _apply(row, values, touch_row):
    changed = False
    for key, value in values.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed and touch_row:
        db.touch(row)
    return changed


# ------------------------------------------------------------------ recomputes


def recompute_vehicle(vehicle, touch_row=False):
    referrals = referrals_of_vehicle(vehicle["id"])
    if any(r["status"] == "SUBSTANTIATED" for r in referrals):
        fraud_hold = "CONFIRMED"
    elif any(r["status"] in ("OPEN", "INVESTIGATING") for r in referrals):
        fraud_hold = "UNDER_REFERRAL"
    else:
        fraud_hold = "NONE"

    titles = titles_of_vehicle(vehicle["id"])
    active = [t for t in titles if t["status"] == "ACTIVE"]
    active_brand = active[0]["brand_code"] if len(active) == 1 else "NONE"
    history = calc.sort_brands([t["brand_code"] for t in titles])

    open_count = len([a for a in apps_of_vehicle(vehicle["id"]) if a["status"] not in TERMINAL_APP])

    readings = [r["odometer_reading_miles"] for r in db.db.damage_reports.values() if r["vehicle_id"] == vehicle["id"]]
    for transfer in transfers_of_vehicle(vehicle["id"]):
        if transfer["status"] == "RECORDED" and transfer["_effective"] <= db.now():
            readings.append(transfer["odometer_reading_miles"])
    last_odometer = max(readings) if readings else None

    return _apply(
        vehicle,
        {
            "fraud_hold": fraud_hold,
            "active_brand_code": active_brand,
            "brand_history": history,
            "open_application_count": open_count,
            "last_odometer_miles": last_odometer,
        },
        touch_row,
    )


def rebuilder_scores(rebuilder):
    docs = docs_of_rebuilder(rebuilder["id"])
    window_start = db.now() - db.days(calc.ROLLING_WINDOW_DAYS)
    rolling_docs = [d for d in docs if window_start <= d["_created"] <= db.now()]
    return calc.recordkeeping_score(rolling_docs), calc.recordkeeping_score(docs)


def recompute_rebuilder(rebuilder, touch_row=False):
    apps = apps_of_rebuilder(rebuilder["id"])
    escrowed = sum(a["fee_escrowed_cents"] for a in apps if a["status"] not in TERMINAL_APP)
    consumed = rebuilder["fees_consumed_cents"]
    deposited = rebuilder["fees_deposited_cents"]
    referrals = referrals_of_rebuilder(rebuilder["id"])
    open_referrals = len([r for r in referrals if r["status"] in ("OPEN", "INVESTIGATING")])
    substantiated = len([r for r in referrals if r["status"] == "SUBSTANTIATED"])
    titled = len([a for a in apps if a["status"] == "TITLE_ISSUED"])

    changed = _apply(
        rebuilder,
        {
            "escrowed_fee_total_cents": escrowed,
            "fee_balance_cents": deposited - escrowed - consumed,
            "open_referral_count": open_referrals,
            "substantiated_referral_count": substantiated,
            "applications_titled_count": titled,
        },
        touch_row,
    )
    rolling, lifetime = rebuilder_scores(rebuilder)
    rebuilder["recordkeeping_score_rolling"] = rolling
    rebuilder["recordkeeping_score_lifetime"] = lifetime
    return changed


def recompute_inspector(inspector, touch_row=False):
    expires = inspector["_credential_expires"]
    status = "EXPIRED" if expires is not None and expires <= db.now() else "CURRENT"
    scheduled = len(
        [
            i
            for i in db.db.inspections.values()
            if i["inspector_id"] == inspector["id"] and i["status"] in LIVE_INSPECTION
        ]
    )
    changed = _apply(inspector, {"scheduled_inspection_count": scheduled}, touch_row)
    inspector["credential_status"] = status
    return changed


def recompute_station(station, touch_row=False):
    occupancy = len(
        [
            i
            for i in db.db.inspections.values()
            if i["station_id"] == station["id"] and i["status"] in LIVE_INSPECTION
        ]
    )
    return _apply(station, {"scheduled_occupancy_count": occupancy}, touch_row)


def recompute_title(title, touch_row=False):
    chain = chain_of_title(title)
    history = calc.sort_brands([t["brand_code"] for t in chain])
    siblings = titles_of_vehicle(title["vehicle_id"])
    others_active = any(
        t["id"] != title["id"] and t["status"] == "ACTIVE" for t in siblings
    )
    is_current = title["status"] == "ACTIVE" and not others_active
    return _apply(
        title,
        {
            "brand_history": history,
            "brand_severity": calc.severity(title["brand_code"]),
            "is_current": is_current,
            "transfer_sequence": len(chain) - 1,
        },
        touch_row,
    )


def recompute_application(application, touch_row=False):
    docs = docs_of_app(application["id"])
    vehicle = db.db.vehicles.get(application["vehicle_id"])
    body_class = vehicle["body_class"] if vehicle else None
    documented = sum(d["amount_cents"] for d in docs if d["status"] == "VERIFIED")
    completeness = calc.documentation_completeness(body_class, docs)
    views = set(
        d["photo_view_code"]
        for d in docs
        if d["doc_type"] == "PHOTOGRAPH"
        and d["status"] in ("SUBMITTED", "VERIFIED")
        and d["photo_view_code"]
    )
    attempts = len(
        [
            i
            for i in inspections_of_app(application["id"])
            if i["status"] in ("COMPLETED_PASS", "COMPLETED_FAIL")
        ]
    )
    changed = _apply(
        application,
        {
            "documented_parts_cost_cents": documented,
            "photo_view_count": len(views),
            "attempts_completed": attempts,
        },
        touch_row,
    )
    if application.get("documentation_completeness_pct") != completeness:
        application["documentation_completeness_pct"] = completeness
        if touch_row and not changed:
            db.touch(application)
            changed = True
    return changed


def recompute_inspection(inspection, touch_row=False):
    findings = findings_of_inspection(inspection["id"])
    blocking = len([f for f in findings if f["blocking"] and not f["resolved"]])
    vehicle_id = None
    application = db.db.applications.get(inspection["application_id"])
    if application:
        vehicle_id = application["vehicle_id"]
    vehicle = db.db.vehicles.get(vehicle_id) if vehicle_id else None
    vin_verified = None
    if inspection.get("vin_plate_reading") is not None and vehicle is not None:
        vin_verified = inspection["vin_plate_reading"] == vehicle["vin"]
    values = {"blocking_findings_count": blocking}
    if vin_verified is not None:
        values["vin_verified"] = vin_verified
    changed = _apply(inspection, values, touch_row)
    # forced_fail latches on and is never rewound
    if blocking >= 1 and not inspection.get("forced_fail"):
        inspection["forced_fail"] = True
        if touch_row and not changed:
            db.touch(inspection)
            changed = True
    return changed


def recompute_fee_fields(application, touch_row=False):
    """assessed_fee_cents follows the verified documents once submitted."""
    if application["status"] == "DRAFT":
        return False
    assessed = calc.assess_fee(docs_of_app(application["id"]))
    return _apply(application, {"assessed_fee_cents": assessed}, touch_row)


# ------------------------------------------------------------------ serialisers


def _common(row, with_common=True):
    payload = {"id": row["id"], "created_at": row["created_at"]}
    if with_common:
        payload["updated_at"] = row["updated_at"]
        payload["version"] = row["version"]
    return payload


def vehicle_out(row, fresh=True):
    if fresh:
        recompute_vehicle(row)
    payload = {
        "id": row["id"],
        "vin": row["vin"],
        "model_year": row["model_year"],
        "make": row["make"],
        "model": row["model"],
        "body_class": row["body_class"],
        "fraud_hold": row["fraud_hold"],
        "active_brand_code": row["active_brand_code"],
        "brand_history": list(row["brand_history"]),
        "open_application_count": row["open_application_count"],
        "last_odometer_miles": row["last_odometer_miles"],
        "registered_state_code": row["registered_state_code"],
    }
    payload.update(_common(row))
    return payload


def rebuilder_out(row, fresh=True):
    if fresh:
        recompute_rebuilder(row)
    payload = {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "license_number": row["license_number"],
        "license_status": row["license_status"],
        "license_expires_at": row["license_expires_at"],
        "bond_amount_cents": row["bond_amount_cents"],
        "fees_deposited_cents": row["fees_deposited_cents"],
        "fee_balance_cents": row["fee_balance_cents"],
        "escrowed_fee_total_cents": row["escrowed_fee_total_cents"],
        "fees_consumed_cents": row["fees_consumed_cents"],
        "open_referral_count": row["open_referral_count"],
        "substantiated_referral_count": row["substantiated_referral_count"],
        "applications_titled_count": row["applications_titled_count"],
        "recordkeeping_score_rolling": calc.as_number(row["recordkeeping_score_rolling"]),
        "recordkeeping_score_lifetime": calc.as_number(row["recordkeeping_score_lifetime"]),
        "suspended_by_user_id": row["suspended_by_user_id"],
        "last_license_action_by_user_id": row["last_license_action_by_user_id"],
    }
    payload.update(_common(row))
    return payload


def inspector_out(row, fresh=True):
    if fresh:
        recompute_inspector(row)
    payload = {
        "id": row["id"],
        "full_name": row["full_name"],
        "badge_number": row["badge_number"],
        "credential_expires_at": row["credential_expires_at"],
        "credential_status": row["credential_status"],
        "certifications": list(row["certifications"]),
        "scheduled_inspection_count": row["scheduled_inspection_count"],
        "home_state_code": row["home_state_code"],
    }
    payload.update(_common(row))
    return payload


def station_out(row, fresh=True):
    if fresh:
        recompute_station(row)
    payload = {
        "id": row["id"],
        "station_code": row["station_code"],
        "bay_count": row["bay_count"],
        "supports_flood": row["supports_flood"],
        "address_state_code": row["address_state_code"],
        "scheduled_occupancy_count": row["scheduled_occupancy_count"],
    }
    payload.update(_common(row))
    return payload


def damage_report_out(row, fresh=True):
    payload = {
        "id": row["id"],
        "vehicle_id": row["vehicle_id"],
        "insurer_name": row["insurer_name"],
        "claim_number": row["claim_number"],
        "basis_code": row["basis_code"],
        "acv_cents": row["acv_cents"],
        "repair_estimate_cents": row["repair_estimate_cents"],
        "salvage_retention_cents": row["salvage_retention_cents"],
        "damage_type": row["damage_type"],
        "flood_water_depth_cm": row["flood_water_depth_cm"],
        "odometer_reading_miles": row["odometer_reading_miles"],
        "report_effective_at": row["report_effective_at"],
        "total_loss_declared": row["total_loss_declared"],
        "damage_ratio": calc.as_number(row["damage_ratio"]),
        "recommended_brand_code": row["recommended_brand_code"],
    }
    payload.update(_common(row, with_common=False))
    return payload


def title_out(row, fresh=True):
    if fresh:
        recompute_title(row)
    payload = {
        "id": row["id"],
        "vehicle_id": row["vehicle_id"],
        "predecessor_title_id": row["predecessor_title_id"],
        "source_damage_report_id": row["source_damage_report_id"],
        "brand_code": row["brand_code"],
        "brand_history": list(row["brand_history"]),
        "status": row["status"],
        "recognition_state": row["recognition_state"],
        "issuing_state_code": row["issuing_state_code"],
        "issued_at": row["issued_at"],
        "is_current": row["is_current"],
        "transfer_sequence": row["transfer_sequence"],
        "odometer_at_issue_miles": row["odometer_at_issue_miles"],
        "owner_name": row["owner_name"],
        "brand_severity": row["brand_severity"],
    }
    payload.update(_common(row))
    return payload


def application_out(row, fresh=True):
    if fresh:
        recompute_application(row)
    payload = {
        "id": row["id"],
        "vehicle_id": row["vehicle_id"],
        "rebuilder_id": row["rebuilder_id"],
        "salvage_title_id": row["salvage_title_id"],
        "status": row["status"],
        "expedite_requested": row["expedite_requested"],
        "declared_repair_cost_cents": row["declared_repair_cost_cents"],
        "documented_parts_cost_cents": row["documented_parts_cost_cents"],
        "documentation_completeness_pct": calc.as_number(row["documentation_completeness_pct"]),
        "photo_view_count": row["photo_view_count"],
        "assessed_fee_cents": row["assessed_fee_cents"],
        "total_program_charge_cents": row["total_program_charge_cents"],
        "fee_escrowed_cents": row["fee_escrowed_cents"],
        "attempts_completed": row["attempts_completed"],
        "attempt_limit": row["attempt_limit"],
        "last_inspection_result": row["last_inspection_result"],
        "withdrawn_reason": row["withdrawn_reason"],
        "terminal_at": row["terminal_at"],
    }
    payload.update(_common(row))
    return payload


def parts_document_out(row, fresh=True):
    payload = {
        "id": row["id"],
        "application_id": row["application_id"],
        "donor_title_id": row["donor_title_id"],
        "verified_by_inspector_id": row["verified_by_inspector_id"],
        "doc_type": row["doc_type"],
        "part_class": row["part_class"],
        "photo_view_code": row["photo_view_code"],
        "source_type": row["source_type"],
        "vendor_name": row["vendor_name"],
        "amount_cents": row["amount_cents"],
        "part_serial_number": row["part_serial_number"],
        "donor_vin": row["donor_vin"],
        "status": row["status"],
        "rejection_reason": row["rejection_reason"],
        "traceable": row["traceable"],
    }
    payload.update(_common(row))
    return payload


def inspection_out(row, fresh=True):
    if fresh:
        recompute_inspection(row)
    payload = {
        "id": row["id"],
        "application_id": row["application_id"],
        "inspector_id": row["inspector_id"],
        "station_id": row["station_id"],
        "attempt_no": row["attempt_no"],
        "scheduled_start_at": row["scheduled_start_at"],
        "scheduled_end_at": row["scheduled_end_at"],
        "effective_end_at": row["effective_end_at"],
        "status": row["status"],
        "result": row["result"],
        "adequacy_score": calc.as_number(row["adequacy_score"]),
        "checkpoint_results": row["checkpoint_results"],
        "blocking_findings_count": row["blocking_findings_count"],
        "forced_fail": row["forced_fail"],
        "vin_plate_reading": row["vin_plate_reading"],
        "vin_verified": row["vin_verified"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "cancellation_reason": row["cancellation_reason"],
    }
    payload.update(_common(row))
    return payload


def finding_out(row, fresh=True):
    payload = {
        "id": row["id"],
        "inspection_id": row["inspection_id"],
        "parts_document_id": row["parts_document_id"],
        "category": row["category"],
        "severity": row["severity"],
        "description": row["description"],
        "blocking": row["blocking"],
        "resolved": row["resolved"],
        "recorded_by_inspector_id": row["recorded_by_inspector_id"],
    }
    payload.update(_common(row, with_common=False))
    return payload


def appeal_out(row, fresh=True):
    payload = {
        "id": row["id"],
        "inspection_id": row["inspection_id"],
        "grounds": row["grounds"],
        "narrative": row["narrative"],
        "status": row["status"],
        "filed_at": row["filed_at"],
        "decided_at": row["decided_at"],
        "hearing_officer_user_id": row["hearing_officer_user_id"],
        "remand_count": row["remand_count"],
        "decision_note": row["decision_note"],
    }
    payload.update(_common(row))
    return payload


def referral_out(row, fresh=True):
    payload = {
        "id": row["id"],
        "vehicle_id": row["vehicle_id"],
        "application_id": row["application_id"],
        "inspection_id": row["inspection_id"],
        "referral_type": row["referral_type"],
        "origin": row["origin"],
        "status": row["status"],
        "evidence_summary": row["evidence_summary"],
        "opened_by_user_id": row["opened_by_user_id"],
        "investigator_user_id": row["investigator_user_id"],
        "resolved_at": row["resolved_at"],
    }
    payload.update(_common(row))
    return payload


def recognition_out(row, fresh=True):
    payload = {
        "id": row["id"],
        "title_record_id": row["title_record_id"],
        "requesting_state_code": row["requesting_state_code"],
        "submitted_brand_code": row["submitted_brand_code"],
        "mapped_brand_code": row["mapped_brand_code"],
        "outcome": row["outcome"],
        "status": row["status"],
        "decided_at": row["decided_at"],
    }
    payload.update(_common(row))
    return payload


def transfer_out(row, fresh=True):
    payload = {
        "id": row["id"],
        "from_title_id": row["from_title_id"],
        "to_title_id": row["to_title_id"],
        "buyer_name": row["buyer_name"],
        "transfer_effective_at": row["transfer_effective_at"],
        "odometer_reading_miles": row["odometer_reading_miles"],
        "odometer_flag": row["odometer_flag"],
        "carried_brand_code": row["carried_brand_code"],
        "sale_price_cents": row["sale_price_cents"],
        "status": row["status"],
    }
    payload.update(_common(row))
    return payload
