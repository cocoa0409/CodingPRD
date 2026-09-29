"""Title instruments: issuance, surrender, conveyances and interstate
recognition."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.reads import fetch
from services import calc, cascades, derive

bp = Blueprint("titles", __name__)


def _mint_title(vehicle, issuing_state_code, owner_name, brand_code, predecessor_id,
                source_damage_report_id, odometer_at_issue):
    row = db.new_row()
    row.update(
        {
            "vehicle_id": vehicle["id"],
            "predecessor_title_id": predecessor_id,
            "source_damage_report_id": source_damage_report_id,
            "brand_code": brand_code,
            "brand_history": [],
            "status": "ACTIVE",
            "recognition_state": "NOT_SUBMITTED",
            "issuing_state_code": issuing_state_code,
            "issued_at": db.now_iso(),
            "is_current": True,
            "transfer_sequence": 0,
            "odometer_at_issue_miles": odometer_at_issue,
            "owner_name": owner_name,
            "brand_severity": calc.severity(brand_code),
        }
    )
    db.db.titles[row["id"]] = row
    derive.recompute_title(row, touch_row=False)
    return row


@bp.post("/v1/title-records")
def create_title():
    mw.authenticate("StateTitleClerk")
    data = mw.body()

    # 4. body foreign keys in declared field order
    vehicle_id = data.get("vehicle_id")
    if not isinstance(vehicle_id, str) or not vehicle_id.strip():
        mw.bad("vehicle_id", "is required")
    vehicle = db.db.vehicles.get(vehicle_id)
    if vehicle is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND")

    report = None
    report_id = data.get("source_damage_report_id")
    if report_id is not None:
        if not isinstance(report_id, str) or not report_id.strip():
            mw.bad("source_damage_report_id", "must be a string identifier")
        report = db.db.damage_reports.get(report_id)
        if report is None:
            raise ApiError("ERR_DAMAGE_REPORT_NOT_FOUND")

    predecessor = None
    predecessor_id = data.get("predecessor_title_id")
    if predecessor_id is not None:
        if not isinstance(predecessor_id, str) or not predecessor_id.strip():
            mw.bad("predecessor_title_id", "must be a string identifier")
        predecessor = db.db.titles.get(predecessor_id)
        if predecessor is None:
            raise ApiError("ERR_TITLE_NOT_FOUND")

    # 5. well-formedness
    issuing_state_code = mw.req_state_code(data, "issuing_state_code")
    owner_name = mw.req_str(data, "owner_name")
    if report is not None and report["vehicle_id"] != vehicle_id:
        mw.bad("source_damage_report_id", "must reference a report of the same vehicle")

    # 9. state-machine admissibility
    if predecessor is not None and predecessor["status"] != "ACTIVE":
        raise ApiError("ERR_TITLE_NOT_ACTIVE", "The predecessor title is not ACTIVE.")
    for existing in derive.titles_of_vehicle(vehicle_id):
        if existing["status"] == "ACTIVE" and (
            predecessor is None or existing["id"] != predecessor["id"]
        ):
            raise ApiError(
                "ERR_TITLE_NOT_ACTIVE",
                "Another title record of this vehicle is still ACTIVE.",
            )

    # 10. business safety
    derive.recompute_vehicle(vehicle, touch_row=False)
    if vehicle["fraud_hold"] == "CONFIRMED":
        raise ApiError(
            "ERR_VEHICLE_FRAUD_HOLD", "A title may not be created for a vehicle under a confirmed fraud hold."
        )

    brand_code = report["recommended_brand_code"] if report is not None else "NONE"
    if report is not None:
        odometer = report["odometer_reading_miles"]
    else:
        odometer = vehicle["last_odometer_miles"]

    title = _mint_title(
        vehicle,
        issuing_state_code,
        owner_name,
        brand_code,
        predecessor["id"] if predecessor is not None else None,
        report["id"] if report is not None else None,
        odometer,
    )
    if predecessor is not None:
        cascades.leave_active(predecessor, "SUPERSEDED")
    derive.recompute_title(title, touch_row=False)
    derive.recompute_vehicle(vehicle, touch_row=True)
    return response.single(derive.title_out(title), 201)


@bp.post("/v1/title-records/<row_id>/surrender")
def surrender_title(row_id):
    mw.authenticate("StateTitleClerk")
    title = fetch(db.db.titles, row_id, "ERR_TITLE_NOT_FOUND")
    data = mw.body()
    mw.opt_str(data, "surrender_note")

    derive.recompute_title(title, touch_row=False)
    # 9. state-machine admissibility
    if title["status"] != "ACTIVE" or not title["is_current"]:
        raise ApiError("ERR_TITLE_NOT_ACTIVE", "Only an ACTIVE, current title may be surrendered.")
    if title["brand_code"] != "NON_REPAIRABLE":
        raise ApiError(
            "ERR_TITLE_NOT_ACTIVE", "Only a NON_REPAIRABLE title may be surrendered."
        )

    # 12. quantitative constraints — no application of the vehicle may still be live
    for application in derive.apps_of_vehicle(title["vehicle_id"]):
        if application["status"] not in derive.TERMINAL_APP:
            raise ApiError(
                "ERR_DUPLICATE_ACTIVE_APPLICATION",
                "A title may not be surrendered while an application of the vehicle is live.",
            )

    cascades.leave_active(title, "SURRENDERED")
    vehicle = db.db.vehicles.get(title["vehicle_id"])
    if vehicle is not None:
        derive.recompute_vehicle(vehicle, touch_row=True)
    return response.single(derive.title_out(title))


@bp.post("/v1/title-transfers")
def create_transfer():
    user_id, _role = mw.authenticate("StateTitleClerk")
    data = mw.body()

    # 4. body foreign keys
    from_title_id = data.get("from_title_id")
    if not isinstance(from_title_id, str) or not from_title_id.strip():
        mw.bad("from_title_id", "is required")
    from_title = db.db.titles.get(from_title_id)
    if from_title is None:
        raise ApiError("ERR_TITLE_NOT_FOUND")

    # 5. well-formedness
    buyer_name = mw.req_str(data, "buyer_name")
    effective_raw, effective_at = mw.req_dt(data, "transfer_effective_at")
    odometer_reading_miles = mw.req_int(data, "odometer_reading_miles", minimum=0)
    sale_price_cents = mw.req_int(data, "sale_price_cents", minimum=0)

    vehicle = db.db.vehicles.get(from_title["vehicle_id"])
    derive.recompute_title(from_title, touch_row=False)

    # 9. state-machine admissibility
    if from_title["status"] != "ACTIVE" or not from_title["is_current"]:
        raise ApiError("ERR_TITLE_NOT_ACTIVE", "The outgoing title is not ACTIVE and current.")

    # 10. business safety
    derive.recompute_vehicle(vehicle, touch_row=False)
    if vehicle["fraud_hold"] != "NONE":
        raise ApiError("ERR_VEHICLE_FRAUD_HOLD", "The vehicle is under a fraud hold.")
    if "NON_REPAIRABLE" in vehicle["brand_history"] or from_title["brand_code"] == "NON_REPAIRABLE":
        raise ApiError(
            "ERR_NON_REPAIRABLE_BRAND", "A NON_REPAIRABLE vehicle may not be conveyed."
        )

    # 13. temporal windows
    issued_at = db.parse_dt(from_title["issued_at"])
    if issued_at is not None and effective_at < issued_at:
        raise ApiError(
            "ERR_TRANSFER_PREDATES_TITLE",
            "transfer_effective_at may not predate the outgoing title's issued_at.",
        )
    for prior in derive.transfers_of_vehicle(vehicle["id"]):
        if prior["status"] == "RECORDED" and effective_at < prior["_effective"]:
            raise ApiError(
                "ERR_TRANSFER_PREDATES_TITLE",
                "transfer_effective_at may not predate an already-recorded conveyance on the chain.",
            )

    # brand carry-forward across the whole ancestry
    chain = derive.chain_of_title(from_title)
    collected = calc.sort_brands([t["brand_code"] for t in chain])
    carried = collected[0] if collected else "NONE"

    # 14. brand integrity
    if calc.severity(carried) < calc.severity(calc.most_severe([t["brand_code"] for t in chain])):
        raise ApiError(
            "ERR_BRAND_ESCALATION_FORBIDDEN",
            "A conveyance may not carry a brand less severe than the chain maximum.",
        )

    # odometer replay over everything known before this conveyance
    events = []
    for report in db.db.damage_reports.values():
        if report["vehicle_id"] == vehicle["id"]:
            events.append((report["_effective"], report["_seq"], report["odometer_reading_miles"]))
    for prior in derive.transfers_of_vehicle(vehicle["id"]):
        if prior["status"] == "RECORDED":
            events.append((prior["_effective"], prior["_seq"], prior["odometer_reading_miles"]))
    flag = calc.odometer_flag(events, effective_at, odometer_reading_miles)

    successor = _mint_title(
        vehicle,
        from_title["issuing_state_code"],
        buyer_name,
        carried,
        from_title["id"],
        None,
        odometer_reading_miles,
    )

    row = db.new_row()
    row.update(
        {
            "from_title_id": from_title["id"],
            "to_title_id": successor["id"],
            "buyer_name": buyer_name,
            "transfer_effective_at": effective_raw,
            "_effective": effective_at,
            "odometer_reading_miles": odometer_reading_miles,
            "odometer_flag": flag,
            "carried_brand_code": carried,
            "sale_price_cents": sale_price_cents,
            "status": "RECORDED",
        }
    )
    db.db.transfers[row["id"]] = row

    cascades.leave_active(from_title, "SUPERSEDED")
    derive.recompute_title(successor, touch_row=False)
    derive.recompute_vehicle(vehicle, touch_row=True)

    if flag == "ROLLBACK_SUSPECTED":
        cascades.open_referral(
            vehicle,
            "ODOMETER",
            "AUTO_CASCADE",
            user_id,
            "Odometer rollback suspected on a recorded conveyance.",
        )
        for application in derive.apps_of_vehicle(vehicle["id"]):
            if application["status"] in derive.TERMINAL_APP:
                continue
            for inspection in derive.inspections_of_app(application["id"]):
                if inspection["status"] == "SCHEDULED":
                    cascades.cancel_attempt(inspection, "FRAUD_HOLD")
        derive.recompute_vehicle(vehicle, touch_row=True)

    return response.single(derive.transfer_out(row), 201)


@bp.post("/v1/recognition-requests")
def create_recognition():
    mw.authenticate("StateTitleClerk")
    data = mw.body()

    # 4. body foreign keys
    title_record_id = data.get("title_record_id")
    if not isinstance(title_record_id, str) or not title_record_id.strip():
        mw.bad("title_record_id", "is required")
    title = db.db.titles.get(title_record_id)
    if title is None:
        raise ApiError("ERR_TITLE_NOT_FOUND")

    # 5. well-formedness
    requesting_state_code = mw.req_state_code(data, "requesting_state_code")
    expected_title_version = mw.req_int(data, "expected_title_version")

    # 8. optimistic concurrency
    if expected_title_version != title["version"]:
        raise ApiError(
            "ERR_STALE_TITLE_VERSION",
            "expected_title_version does not match the title's current version.",
        )

    # 9. state-machine admissibility
    derive.recompute_title(title, touch_row=False)
    if title["status"] != "ACTIVE" or not title["is_current"]:
        raise ApiError("ERR_TITLE_NOT_ACTIVE", "Only an ACTIVE, current title may be submitted.")
    if requesting_state_code == title["issuing_state_code"]:
        mw.bad("requesting_state_code", "must differ from the title's issuing_state_code")
    if title["brand_code"] == "NONE":
        mw.bad("title_record_id", "must reference a branded title")

    for prior in derive.recognitions_of_title(title["id"]):
        if prior["status"] == "PENDING":
            prior["status"] = "SUPERSEDED"
            db.touch(prior)

    row = db.new_row()
    row.update(
        {
            "title_record_id": title["id"],
            "requesting_state_code": requesting_state_code,
            "submitted_brand_code": title["brand_code"],
            "mapped_brand_code": None,
            "outcome": None,
            "status": "PENDING",
            "decided_at": None,
        }
    )
    db.db.recognitions[row["id"]] = row

    title["recognition_state"] = "RECOGNITION_PENDING"
    db.touch(title)
    return response.single(derive.recognition_out(row), 201)


@bp.post("/v1/recognition-requests/<row_id>/decide")
def decide_recognition(row_id):
    mw.authenticate("ProgramAdmin")
    request_row = fetch(db.db.recognitions, row_id, "ERR_RECOGNITION_REQUEST_NOT_FOUND")
    data = mw.body()
    mapped_brand_code = mw.req_enum(data, "mapped_brand_code", calc.BRAND_CODES)
    mw.opt_str(data, "decision_note")

    # 9. state-machine admissibility
    if request_row["status"] != "PENDING":
        raise ApiError(
            "ERR_RECOGNITION_ALREADY_DECIDED", "This recognition request is no longer PENDING."
        )

    submitted = request_row["submitted_brand_code"]
    # 14. brand integrity — severity may never harden across jurisdictions
    if calc.severity(mapped_brand_code) > calc.severity(submitted):
        raise ApiError(
            "ERR_BRAND_ESCALATION_FORBIDDEN",
            "mapped_brand_code may not be more severe than submitted_brand_code.",
        )

    if mapped_brand_code == "NONE":
        outcome = "REJECTED"
    elif mapped_brand_code == submitted:
        outcome = "RECOGNIZED"
    else:
        outcome = "DOWNGRADED"

    request_row["mapped_brand_code"] = mapped_brand_code
    request_row["outcome"] = outcome
    request_row["status"] = "DECIDED"
    request_row["decided_at"] = db.now_iso()
    db.touch(request_row)

    title = db.db.titles.get(request_row["title_record_id"])
    if title is not None:
        title["recognition_state"] = "RECOGNIZED" if outcome == "RECOGNIZED" else "DOWNGRADED"
        db.touch(title)
    return response.single(derive.recognition_out(request_row))
