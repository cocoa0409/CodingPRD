"""Core services: entity lifecycle, audit hash chain, computed rollups, clock sweep."""

import hashlib
from datetime import datetime, timezone, timedelta

import db
from util import iso_format, parse_iso, round_half_up, dec, num_out

# Entity name -> (store, not-found error id)
ENTITY_REGISTRY = {
    "Permit": ("permits", "ERR_PERMIT_NOT_FOUND"),
    "Outfall": ("outfalls", "ERR_OUTFALL_NOT_FOUND"),
    "EffluentLimit": ("effluent_limits", "ERR_LIMIT_NOT_FOUND"),
    "SamplingEvent": ("sampling_events", "ERR_SAMPLE_NOT_FOUND"),
    "LabResult": ("lab_results", "ERR_RESULT_NOT_FOUND"),
    "Exceedance": ("exceedances", "ERR_EXCEEDANCE_NOT_FOUND"),
    "DischargeMonitoringReport": ("dmrs", "ERR_DMR_NOT_FOUND"),
    "StormwaterPlan": ("swppp_plans", "ERR_PLAN_NOT_FOUND"),
    "Inspection": ("inspections", "ERR_INSPECTION_NOT_FOUND"),
    "CorrectiveAction": ("corrective_actions", "ERR_CORRECTIVE_ACTION_NOT_FOUND"),
    "RenewalApplication": ("renewal_applications", "ERR_RENEWAL_NOT_FOUND"),
    "ConsentOrder": ("consent_orders", "ERR_CONSENT_ORDER_NOT_FOUND"),
}

# Ledger/record entities: id + created_at only (no updated_at, no version)
LEDGER_ENTITIES = {"ChainOfCustodyRecord", "PenaltyPayment", "AuditLogEntry"}

PARAMETER_CODES = {"BOD5", "TSS", "PH", "AMMONIA_N", "COPPER", "FECAL_COLIFORM"}
LIMIT_TYPES = {"DAILY_MAX", "MONTHLY_AVG"}
UNITS = {"MG_L", "SU", "MPN_100ML"}
AVERAGE_METHODS = {"ARITHMETIC", "FLOW_WEIGHTED"}
MONITORING_FREQUENCIES = {"WEEKLY", "MONTHLY"}
CUSTODY_EVENT_TYPES = {"SEAL", "TRANSFER", "RECEIVE_LAB", "ANALYSIS_START"}
QUALIFIERS = {"NONE", "BELOW_MDL", "ESTIMATED"}
SEVERITIES = {"CRITICAL", "MAJOR", "MINOR"}
ASSESSMENT_VARIANTS = {"PER_DAY", "ECONOMIC_BENEFIT"}
PAYMENT_DIRECTIONS = {"PAYMENT", "REFUND"}

HOLDING_TIME_HOURS = {
    "PH": 2,
    "FECAL_COLIFORM": 8,
    "BOD5": 48,
    "TSS": 168,
    "AMMONIA_N": 672,
    "COPPER": 4320,
}

CA_DEADLINE_DAYS = {"CRITICAL": 7, "MAJOR": 30, "MINOR": 90}


def store_for(entity_name):
    attr, _ = ENTITY_REGISTRY[entity_name]
    return getattr(db, attr)


def nf_error(entity_name):
    return ENTITY_REGISTRY[entity_name][1]


def base_entity(entity_name):
    """Common fields for primary resources."""
    now = db.clock.now()
    return {
        "id": None,  # caller assigns
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }


def ledger_entity():
    now = db.clock.now()
    return {
        "id": None,
        "created_at": now,
        "_seq": db.next_insert_seq(),
    }


def touch(entity):
    """Refresh updated_at and bump version for a mutated primary resource."""
    entity["updated_at"] = db.clock.now()
    if "version" in entity:
        entity["version"] += 1


# ---------------------------------------------------------------------------
# Audit chain
# ---------------------------------------------------------------------------

def append_audit(entity_type, entity_id, action, actor_user_id, actor_role):
    prev_hash = db.audit_entries[-1]["entry_hash"] if db.audit_entries else "0" * 64
    occurred = db.clock.now()
    occurred_iso = iso_format(occurred)
    payload = "|".join(
        [prev_hash, entity_type, entity_id, action, actor_user_id, actor_role, occurred_iso]
    )
    entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    entry = ledger_entity()
    import uuid as _uuid
    entry["id"] = str(_uuid.uuid4())
    entry.update(
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            "occurred_at": occurred,
            "prev_entry_hash": prev_hash,
            "entry_hash": entry_hash,
        }
    )
    db.audit_entries.append(entry)
    return entry


# ---------------------------------------------------------------------------
# Permit rollup (open counts + posture)
# ---------------------------------------------------------------------------

def permit_for_corrective_action(ca):
    """Resolve the Permit reachable from a CorrectiveAction."""
    if ca["source_type"] == "EXCEEDANCE":
        exc = db.exceedances.get(ca.get("exceedance_id"))
        if exc is None:
            return None
        outfall = db.outfalls.get(exc["outfall_id"])
        if outfall is None:
            return None
        return db.permits.get(outfall["permit_id"])
    else:  # INSPECTION
        insp = db.inspections.get(ca.get("inspection_id"))
        if insp is None:
            return None
        plan = db.swppp_plans.get(insp["plan_id"])
        if plan is None:
            return None
        return db.permits.get(plan["permit_id"])


def permit_for_exceedance(exc):
    outfall = db.outfalls.get(exc["outfall_id"])
    if outfall is None:
        return None
    return db.permits.get(outfall["permit_id"])


def recompute_permit_rollup(permit_id):
    """Recompute open_corrective_action_count, open_exceedance_count, compliance_posture."""
    permit = db.permits.get(permit_id)
    if permit is None:
        return

    # Open corrective actions reachable via outfalls/exceedances/inspections
    open_ca_statuses = {"OPEN", "IN_PROGRESS", "COMPLETED", "REOPENED"}
    ca_count = 0
    for ca in db.corrective_actions.values():
        if ca["status"] not in open_ca_statuses:
            continue
        p = permit_for_corrective_action(ca)
        if p is not None and p["id"] == permit_id:
            ca_count += 1

    # Open exceedances on this permit's outfalls
    permit_outfall_ids = {
        o["id"] for o in db.outfalls.values() if o["permit_id"] == permit_id
    }
    exc_count = 0
    for exc in db.exceedances.values():
        if exc["outfall_id"] in permit_outfall_ids and exc["notification_status"] != "CLOSED":
            exc_count += 1

    # Enforcement posture: any consent order in {ISSUED, UNDER_APPEAL, FINAL} linked
    # to this permit through an exceedance chain
    enforcement = False
    for co in db.consent_orders.values():
        if co["status"] in {"ISSUED", "UNDER_APPEAL", "FINAL"}:
            exc = db.exceedances.get(co["exceedance_id"])
            if exc and exc["outfall_id"] in permit_outfall_ids:
                enforcement = True
                break

    if enforcement:
        posture = "ENFORCEMENT"
    elif ca_count > 0:
        posture = "UNDER_CORRECTIVE_ACTION"
    else:
        posture = "GOOD_STANDING"

    changed = (
        permit["open_corrective_action_count"] != ca_count
        or permit["open_exceedance_count"] != exc_count
        or permit["compliance_posture"] != posture
    )
    permit["open_corrective_action_count"] = ca_count
    permit["open_exceedance_count"] = exc_count
    permit["compliance_posture"] = posture
    if changed:
        touch(permit)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cascade_permit_shutdown(permit, actor_user_id="system", actor_role="system"):
    """Permit leaves service: outfalls -> INACTIVE, their SCHEDULED samples -> CANCELLED."""
    for outfall in db.outfalls.values():
        if outfall["permit_id"] == permit["id"] and outfall["status"] == "ACTIVE":
            outfall["status"] = "INACTIVE"
            touch(outfall)
            append_audit("Outfall", outfall["id"], "OUTFALL_DEACTIVATED", actor_user_id, actor_role)
            for ev in db.sampling_events.values():
                if ev["outfall_id"] == outfall["id"] and ev["schedule_status"] == "SCHEDULED":
                    ev["schedule_status"] = "CANCELLED"
                    touch(ev)
                    append_audit("SamplingEvent", ev["id"], "SAMPLE_CANCELLED", actor_user_id, actor_role)


def cascade_outfall_deactivate(outfall, actor_user_id, actor_role):
    """Outfall deactivation: cancel its SCHEDULED sampling events."""
    for ev in db.sampling_events.values():
        if ev["outfall_id"] == outfall["id"] and ev["schedule_status"] == "SCHEDULED":
            ev["schedule_status"] = "CANCELLED"
            touch(ev)
            append_audit("SamplingEvent", ev["id"], "SAMPLE_CANCELLED", actor_user_id, actor_role)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _iso_or_none(v):
    if v is None:
        return None
    return iso_format(v)


def _num_or_none(v):
    if v is None:
        return None
    return num_out(v)


def serialize_permit(p):
    return {
        "id": p["id"],
        "permit_number": p["permit_number"],
        "facility_name": p["facility_name"],
        "receiving_water_body": p["receiving_water_body"],
        "effective_date": _iso_or_none(p["effective_date"]),
        "expiration_date": _iso_or_none(p["expiration_date"]),
        "status": p["status"],
        "superseded_by_permit_id": p["superseded_by_permit_id"],
        "compliance_posture": p["compliance_posture"],
        "open_corrective_action_count": p["open_corrective_action_count"],
        "open_exceedance_count": p["open_exceedance_count"],
        "created_at": _iso_or_none(p["created_at"]),
        "updated_at": _iso_or_none(p["updated_at"]),
        "version": p["version"],
    }


def serialize_outfall(o):
    return {
        "id": o["id"],
        "permit_id": o["permit_id"],
        "outfall_number": o["outfall_number"],
        "description": o["description"],
        "status": o["status"],
        "created_at": _iso_or_none(o["created_at"]),
        "updated_at": _iso_or_none(o["updated_at"]),
        "version": o["version"],
    }


def serialize_effluent_limit(l):
    return {
        "id": l["id"],
        "outfall_id": l["outfall_id"],
        "parameter_code": l["parameter_code"],
        "limit_type": l["limit_type"],
        "limit_value": num_out(l["limit_value"]),
        "unit": l["unit"],
        "average_method": l["average_method"],
        "monitoring_frequency": l["monitoring_frequency"],
        "effective_from": _iso_or_none(l["effective_from"]),
        "effective_to": _iso_or_none(l["effective_to"]),
        "status": l["status"],
        "supersedes_limit_id": l["supersedes_limit_id"],
        "created_at": _iso_or_none(l["created_at"]),
        "updated_at": _iso_or_none(l["updated_at"]),
        "version": l["version"],
    }


def serialize_sampling_event(e):
    return {
        "id": e["id"],
        "outfall_id": e["outfall_id"],
        "parameter_code": e["parameter_code"],
        "scheduled_for": _iso_or_none(e["scheduled_for"]),
        "collection_window_hours": e["collection_window_hours"],
        "schedule_status": e["schedule_status"],
        "custody_status": e["custody_status"],
        "collected_at": _iso_or_none(e["collected_at"]),
        "collected_by_user_id": e["collected_by_user_id"],
        "created_at": _iso_or_none(e["created_at"]),
        "updated_at": _iso_or_none(e["updated_at"]),
        "version": e["version"],
    }


def serialize_custody_record(r):
    return {
        "id": r["id"],
        "sampling_event_id": r["sampling_event_id"],
        "event_type": r["event_type"],
        "event_at": _iso_or_none(r["event_at"]),
        "from_party": r["from_party"],
        "to_party": r["to_party"],
        "note": r["note"],
        "sequence_index": r["sequence_index"],
        "recorded_by_user_id": r["recorded_by_user_id"],
        "created_at": _iso_or_none(r["created_at"]),
    }


def serialize_lab_result(r):
    return {
        "id": r["id"],
        "sampling_event_id": r["sampling_event_id"],
        "parameter_code": r["parameter_code"],
        "reported_value": num_out(r["reported_value"]),
        "unit": r["unit"],
        "method_detection_limit": num_out(r["method_detection_limit"]),
        "qualifier": r["qualifier"],
        "flow_mgd": num_out(r["flow_mgd"]),
        "analyzed_at": _iso_or_none(r["analyzed_at"]),
        "analyzed_by_user_id": r["analyzed_by_user_id"],
        "validation_status": r["validation_status"],
        "validated_by_user_id": r["validated_by_user_id"],
        "validated_at": _iso_or_none(r["validated_at"]),
        "rejection_reason": r["rejection_reason"],
        "exceeds_limit": r["exceeds_limit"],
        "exceedance_id": r["exceedance_id"],
        "created_at": _iso_or_none(r["created_at"]),
        "updated_at": _iso_or_none(r["updated_at"]),
        "version": r["version"],
    }


def serialize_exceedance(e):
    return {
        "id": e["id"],
        "lab_result_id": e["lab_result_id"],
        "effluent_limit_id": e["effluent_limit_id"],
        "outfall_id": e["outfall_id"],
        "parameter_code": e["parameter_code"],
        "reported_value": num_out(e["reported_value"]),
        "limit_value": num_out(e["limit_value"]),
        "percent_over": num_out(e["percent_over"]),
        "detected_at": _iso_or_none(e["detected_at"]),
        "oral_notification_due_at": _iso_or_none(e["oral_notification_due_at"]),
        "written_report_due_at": _iso_or_none(e["written_report_due_at"]),
        "notification_status": e["notification_status"],
        "enforcement_status": e["enforcement_status"],
        "oral_notified_at": _iso_or_none(e["oral_notified_at"]),
        "written_filed_at": _iso_or_none(e["written_filed_at"]),
        "corrective_action_id": e["corrective_action_id"],
        "created_at": _iso_or_none(e["created_at"]),
        "updated_at": _iso_or_none(e["updated_at"]),
        "version": e["version"],
    }


def serialize_dmr(d):
    return {
        "id": d["id"],
        "outfall_id": d["outfall_id"],
        "period_start": _iso_or_none(d["period_start"]),
        "period_end": _iso_or_none(d["period_end"]),
        "due_date": _iso_or_none(d["due_date"]),
        "status": d["status"],
        "prepared_by_user_id": d["prepared_by_user_id"],
        "certified_by_user_id": d["certified_by_user_id"],
        "submitted_at": _iso_or_none(d["submitted_at"]),
        "is_late": d["is_late"],
        "required_sample_count": d["required_sample_count"],
        "total_validated_results": d["total_validated_results"],
        "monitoring_completeness_ratio": num_out(d["monitoring_completeness_ratio"]),
        "summary_lines": d["summary_lines"],
        "deficiency_notes": d["deficiency_notes"],
        "created_at": _iso_or_none(d["created_at"]),
        "updated_at": _iso_or_none(d["updated_at"]),
        "version": d["version"],
    }


def serialize_swppp_plan(p):
    return {
        "id": p["id"],
        "permit_id": p["permit_id"],
        "plan_title": p["plan_title"],
        "version_label": p["version_label"],
        "inspection_frequency_days": p["inspection_frequency_days"],
        "status": p["status"],
        "created_at": _iso_or_none(p["created_at"]),
        "updated_at": _iso_or_none(p["updated_at"]),
        "version": p["version"],
    }


def serialize_inspection(i):
    return {
        "id": i["id"],
        "plan_id": i["plan_id"],
        "scheduled_for": _iso_or_none(i["scheduled_for"]),
        "status": i["status"],
        "inspector_user_id": i["inspector_user_id"],
        "completed_at": _iso_or_none(i["completed_at"]),
        "findings": i["findings"],
        "created_at": _iso_or_none(i["created_at"]),
        "updated_at": _iso_or_none(i["updated_at"]),
        "version": i["version"],
    }


def serialize_corrective_action(c):
    return {
        "id": c["id"],
        "source_type": c["source_type"],
        "inspection_id": c["inspection_id"],
        "exceedance_id": c["exceedance_id"],
        "description": c["description"],
        "severity": c["severity"],
        "deadline_at": _iso_or_none(c["deadline_at"]),
        "status": c["status"],
        "is_overdue": compute_ca_is_overdue(c),
        "resolved_at": _iso_or_none(c["resolved_at"]),
        "resolved_by_user_id": c["resolved_by_user_id"],
        "actual_cost_cents": c["actual_cost_cents"],
        "verified_by_user_id": c["verified_by_user_id"],
        "created_at": _iso_or_none(c["created_at"]),
        "updated_at": _iso_or_none(c["updated_at"]),
        "version": c["version"],
    }


def compute_ca_is_overdue(c):
    return c["status"] in {"OPEN", "IN_PROGRESS", "REOPENED"} and db.clock.now() > c["deadline_at"]


def serialize_renewal_application(r):
    return {
        "id": r["id"],
        "permit_id": r["permit_id"],
        "proposed_expiration_date": _iso_or_none(r["proposed_expiration_date"]),
        "status": r["status"],
        "submitted_at": _iso_or_none(r["submitted_at"]),
        "info_request_note": r["info_request_note"],
        "decision_reason": r["decision_reason"],
        "resulting_permit_id": r["resulting_permit_id"],
        "created_at": _iso_or_none(r["created_at"]),
        "updated_at": _iso_or_none(r["updated_at"]),
        "version": r["version"],
    }


def compute_consent_amounts(co):
    """Compute accrued_days, provisional_amount_cents (clock-based), and final amount
    components. Returns dict of computed fields."""
    from services.penalty import compute_penalty
    return compute_penalty(co)


def serialize_consent_order(co):
    computed = compute_consent_amounts(co)
    return {
        "id": co["id"],
        "exceedance_id": co["exceedance_id"],
        "assessment_variant": co["assessment_variant"],
        "base_penalty_cents": co["base_penalty_cents"],
        "daily_accrual_cents": co["daily_accrual_cents"],
        "avoided_cost_cents": co["avoided_cost_cents"],
        "gravity_factor": num_out(co["gravity_factor"]) if co["gravity_factor"] is not None else None,
        "statutory_cap_cents": co["statutory_cap_cents"],
        "status": co["status"],
        "issued_at": _iso_or_none(co["issued_at"]),
        "finalized_at": _iso_or_none(co["finalized_at"]),
        "cure_date": _iso_or_none(co["cure_date"]),
        "accrued_days": computed["accrued_days"],
        "provisional_amount_cents": computed["provisional_amount_cents"],
        "final_amount_cents": co["final_amount_cents"],
        "paid_cents": co["paid_cents"],
        "refunded_cents": co["refunded_cents"],
        "outstanding_cents": co["outstanding_cents"],
        "created_at": _iso_or_none(co["created_at"]),
        "updated_at": _iso_or_none(co["updated_at"]),
        "version": co["version"],
    }


def serialize_penalty_payment(p):
    return {
        "id": p["id"],
        "consent_order_id": p["consent_order_id"],
        "direction": p["direction"],
        "amount_cents": p["amount_cents"],
        "posted_at": _iso_or_none(p["posted_at"]),
        "status": p["status"],
        "created_at": _iso_or_none(p["created_at"]),
    }


def serialize_audit_entry(e):
    return {
        "id": e["id"],
        "entity_type": e["entity_type"],
        "entity_id": e["entity_id"],
        "action": e["action"],
        "actor_user_id": e["actor_user_id"],
        "actor_role": e["actor_role"],
        "occurred_at": _iso_or_none(e["occurred_at"]),
        "prev_entry_hash": e["prev_entry_hash"],
        "entry_hash": e["entry_hash"],
        "created_at": _iso_or_none(e["created_at"]),
    }


# ---------------------------------------------------------------------------
# Clock sweep
# ---------------------------------------------------------------------------

def run_sweep():
    """Apply time-based transitions whose condition is now true. Returns count."""
    now = db.clock.now()
    transitions = 0

    # Permit expiry: ACTIVE permit whose expiration_date has been reached or passed
    for permit in sorted(db.permits.values(), key=lambda p: p["_seq"]):
        if permit["status"] == "ACTIVE" and now >= permit["expiration_date"]:
            permit["status"] = "EXPIRED"
            touch(permit)
            cascade_permit_shutdown(permit, "system", "system")
            append_audit("Permit", permit["id"], "PERMIT_EXPIRED", "system", "system")
            transitions += 1

    # Missed sampling events: SCHEDULED with window fully elapsed
    for ev in sorted(db.sampling_events.values(), key=lambda e: e["_seq"]):
        if ev["schedule_status"] == "SCHEDULED":
            window_end = ev["scheduled_for"] + timedelta(hours=ev["collection_window_hours"])
            if now > window_end:
                ev["schedule_status"] = "MISSED"
                touch(ev)
                append_audit("SamplingEvent", ev["id"], "SAMPLE_MISSED", "system", "system")
                transitions += 1

    # Exceedance notification overdue transitions (strictly past due)
    for exc in sorted(db.exceedances.values(), key=lambda e: e["_seq"]):
        if exc["notification_status"] == "PENDING_ORAL" and now > exc["oral_notification_due_at"]:
            exc["notification_status"] = "ORAL_OVERDUE"
            touch(exc)
            append_audit("Exceedance", exc["id"], "EXCEEDANCE_ORAL_OVERDUE", "system", "system")
            transitions += 1
        if exc["notification_status"] == "ORAL_NOTIFIED" and now > exc["written_report_due_at"]:
            exc["notification_status"] = "WRITTEN_OVERDUE"
            touch(exc)
            append_audit("Exceedance", exc["id"], "EXCEEDANCE_WRITTEN_OVERDUE", "system", "system")
            transitions += 1

    return transitions


# ---------------------------------------------------------------------------
# Generic list helper
# ---------------------------------------------------------------------------

def paginate(items, args):
    """Sort by created_at asc (tie-break insertion seq), apply limit/offset."""
    from errors import err, ERR_INVALID_REQUEST

    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, 400, "limit must be an integer")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset < 0:
        raise err(ERR_INVALID_REQUEST, 400, "offset must be >= 0")

    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return page, total, limit, offset
