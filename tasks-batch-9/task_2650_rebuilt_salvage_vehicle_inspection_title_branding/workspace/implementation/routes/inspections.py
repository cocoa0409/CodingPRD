"""Scheduling, conducting and closing the physical inspection attempt."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.applications import acting_inspector
from routes.reads import fetch
from services import calc, cascades, derive

bp = Blueprint("inspections", __name__)

SCHEDULABLE = ("DOCS_ACCEPTED", "SCHEDULED", "FAILED")
LIVE_APPEAL = ("FILED", "UNDER_REVIEW", "REMANDED")


def _vehicle_of(inspection):
    application = db.db.applications.get(inspection["application_id"])
    if application is None:
        return None
    return db.db.vehicles.get(application["vehicle_id"])


def _is_flood(vehicle):
    if vehicle is None:
        return False
    derive.recompute_vehicle(vehicle, touch_row=False)
    return vehicle["active_brand_code"] == "FLOOD"


def _widened_end(inspection):
    """The half-open interval end used by the inspector exclusivity rule."""
    end = inspection["_end"]
    if _is_flood(_vehicle_of(inspection)):
        return end + db.minutes(calc.FLOOD_BUFFER_MINUTES)
    return end


def require_assigned(inspection, user_id, role):
    if role == "Inspector" and inspection["inspector_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


# ------------------------------------------------------------------ scheduling


@bp.post("/v1/applications/<row_id>/inspections")
def schedule_inspection(row_id):
    mw.authenticate("StateTitleClerk")
    application = fetch(db.db.applications, row_id, "ERR_APPLICATION_NOT_FOUND")
    data = mw.body()

    # 4. body foreign keys, in declared field order
    inspector_id = data.get("inspector_id")
    if not isinstance(inspector_id, str) or not inspector_id.strip():
        mw.bad("inspector_id", "is required")
    inspector = db.db.inspectors.get(inspector_id)
    if inspector is None:
        raise ApiError("ERR_INSPECTOR_NOT_FOUND")

    station_id = data.get("station_id")
    if not isinstance(station_id, str) or not station_id.strip():
        mw.bad("station_id", "is required")
    station = db.db.stations.get(station_id)
    if station is None:
        raise ApiError("ERR_STATION_NOT_FOUND")

    # 5. well-formedness
    start_raw, start_at = mw.req_dt(data, "scheduled_start_at")
    end_raw, end_at = mw.req_dt(data, "scheduled_end_at")
    expected_version = mw.req_int(data, "expected_application_version")
    if end_at <= start_at:
        mw.bad("scheduled_end_at", "must be strictly after scheduled_start_at")

    # 8. optimistic concurrency
    if expected_version != application["version"]:
        raise ApiError(
            "ERR_STALE_APPLICATION_VERSION",
            "expected_application_version does not match the application's current version.",
        )

    # 9. state-machine admissibility
    if application["status"] not in SCHEDULABLE:
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "An attempt may only be scheduled from DOCS_ACCEPTED, SCHEDULED or FAILED.",
        )

    vehicle = db.db.vehicles.get(application["vehicle_id"])
    rebuilder = db.db.rebuilders.get(application["rebuilder_id"])
    if vehicle is not None:
        derive.recompute_vehicle(vehicle, touch_row=False)
    if rebuilder is not None:
        derive.recompute_rebuilder(rebuilder, touch_row=False)
    derive.recompute_application(application, touch_row=False)
    derive.recompute_inspector(inspector, touch_row=False)

    attempts = derive.inspections_of_app(application["id"])
    previous = None
    if application["status"] == "SCHEDULED":
        for attempt in attempts:
            if attempt["status"] == "SCHEDULED":
                previous = attempt

    # 10. business safety
    if vehicle is not None and vehicle["fraud_hold"] != "NONE":
        raise ApiError("ERR_VEHICLE_FRAUD_HOLD", "The vehicle is under a fraud hold.")
    last_failed = None
    for attempt in attempts:
        if attempt["status"] == "COMPLETED_FAIL":
            last_failed = attempt
    if last_failed is not None and last_failed["inspector_id"] == inspector_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The inspector who failed this vehicle may not conduct the re-inspection.",
        )

    # 11. referential business rules
    if inspector["credential_status"] != "CURRENT":
        raise ApiError("ERR_INSPECTOR_CREDENTIAL_EXPIRED")
    flood = _is_flood(vehicle)
    if flood and (
        not station["supports_flood"] or "STRUCTURAL" not in inspector["certifications"]
    ):
        raise ApiError(
            "ERR_STATION_NOT_FLOOD_CAPABLE",
            "A flood-branded vehicle needs a flood-capable station and a STRUCTURAL-certified inspector.",
        )

    # 12. quantitative constraints
    if application["attempts_completed"] >= application["attempt_limit"]:
        raise ApiError(
            "ERR_ATTEMPT_LIMIT_EXCEEDED", "The application has exhausted its inspection attempts."
        )
    for appeal in derive.appeals_of_app(application["id"]):
        if appeal["status"] in LIVE_APPEAL:
            raise ApiError(
                "ERR_APPEAL_PENDING_BLOCKS_SCHEDULING",
                "An appeal in flight freezes the scheduling track.",
            )

    requested_end = end_at + db.minutes(calc.FLOOD_BUFFER_MINUTES) if flood else end_at
    for attempt in db.db.inspections.values():
        if attempt["inspector_id"] != inspector_id:
            continue
        if attempt["status"] not in calc.LIVE_INSPECTION_STATUSES:
            continue
        if previous is not None and attempt["id"] == previous["id"]:
            continue
        # half-open intervals: exactly touching endpoints never collide
        if attempt["_start"] < requested_end and start_at < _widened_end(attempt):
            raise ApiError(
                "ERR_INSPECTOR_INTERVAL_CONFLICT",
                "The inspector already holds an overlapping attempt.",
            )

    occupancy = 0
    for attempt in db.db.inspections.values():
        if attempt["station_id"] != station_id:
            continue
        if attempt["status"] not in calc.LIVE_INSPECTION_STATUSES:
            continue
        if previous is not None and attempt["id"] == previous["id"]:
            continue
        # closed intervals on the raw ends: touching endpoints do intersect
        if attempt["_start"] <= end_at and start_at <= attempt["_end"]:
            occupancy += 1
    if occupancy >= station["bay_count"]:
        raise ApiError(
            "ERR_STATION_CAPACITY_EXCEEDED", "Every bay at this station is already occupied."
        )

    # 13. temporal windows
    if start_at <= db.now():
        raise ApiError(
            "ERR_INSPECTION_SLOT_IN_PAST",
            "scheduled_start_at must be strictly after the current instant.",
        )

    # 15. fiscal capacity, last of all
    delta = 0
    quote = None
    if application["status"] == "FAILED":
        quote = calc.program_charge(
            application["assessed_fee_cents"],
            application["attempts_completed"],
            application["expedite_requested"],
            rebuilder["applications_titled_count"] if rebuilder is not None else 0,
        )
        delta = quote["total_program_charge_cents"] - application["total_program_charge_cents"]
        if rebuilder is not None and delta > 0 and rebuilder["fee_balance_cents"] < delta:
            raise ApiError(
                "ERR_INSUFFICIENT_FEE_BALANCE",
                "fee_balance_cents cannot absorb the re-inspection delta.",
            )

    if previous is not None:
        attempt_no = previous["attempt_no"]
        cascades.cancel_attempt(previous, "RESCHEDULED")
    else:
        attempt_no = application["attempts_completed"] + 1

    row = db.new_row()
    row.update(
        {
            "application_id": application["id"],
            "inspector_id": inspector_id,
            "station_id": station_id,
            "attempt_no": attempt_no,
            "scheduled_start_at": start_raw,
            "scheduled_end_at": end_raw,
            "effective_end_at": db.fmt_dt(requested_end) if flood else end_raw,
            "_start": start_at,
            "_end": end_at,
            "status": "SCHEDULED",
            "result": None,
            "adequacy_score": None,
            "checkpoint_results": None,
            "blocking_findings_count": 0,
            "forced_fail": False,
            "vin_plate_reading": None,
            "vin_verified": False,
            "started_at": None,
            "completed_at": None,
            "cancellation_reason": None,
        }
    )
    db.db.inspections[row["id"]] = row

    if quote is not None:
        application["total_program_charge_cents"] = quote["total_program_charge_cents"]
        application["fee_escrowed_cents"] = application["fee_escrowed_cents"] + delta
    application["status"] = "SCHEDULED"
    derive.recompute_application(application, touch_row=False)
    db.touch(application)

    derive.recompute_inspection(row, touch_row=False)
    derive.recompute_inspector(inspector, touch_row=True)
    derive.recompute_station(station, touch_row=True)
    if rebuilder is not None:
        derive.recompute_rebuilder(rebuilder, touch_row=True)
    return response.single(derive.inspection_out(row), 201)


# ------------------------------------------------------------------ conducting


@bp.post("/v1/inspections/<row_id>/start")
def start_inspection(row_id):
    user_id, role = mw.authenticate("Inspector")
    inspection = fetch(db.db.inspections, row_id, "ERR_INSPECTION_NOT_FOUND")
    data = mw.body()
    mw.opt_str(data, "start_note")

    # 7. ownership
    require_assigned(inspection, user_id, role)
    inspector = acting_inspector(user_id)

    # 9. state-machine admissibility
    if inspection["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INSPECTION_NOT_SCHEDULED", "Only a SCHEDULED attempt may be started."
        )

    application = db.db.applications.get(inspection["application_id"])
    vehicle = _vehicle_of(inspection)

    # 10. business safety
    if vehicle is not None:
        derive.recompute_vehicle(vehicle, touch_row=False)
        if vehicle["fraud_hold"] != "NONE":
            raise ApiError("ERR_VEHICLE_FRAUD_HOLD", "The vehicle is under a fraud hold.")

    # 11. referential business rules
    if inspector["credential_status"] != "CURRENT":
        raise ApiError("ERR_INSPECTOR_CREDENTIAL_EXPIRED")

    # 13. temporal windows
    if db.now() < inspection["_start"]:
        raise ApiError(
            "ERR_INSPECTION_SLOT_IN_PAST", "The booked interval has not started yet."
        )

    inspection["status"] = "IN_PROGRESS"
    inspection["started_at"] = db.now_iso()
    derive.recompute_inspection(inspection, touch_row=False)
    db.touch(inspection)

    if application is not None:
        application["status"] = "IN_INSPECTION"
        derive.recompute_application(application, touch_row=False)
        db.touch(application)
    return response.single(derive.inspection_out(inspection))


@bp.post("/v1/inspections/<row_id>/findings")
def record_finding(row_id):
    user_id, role = mw.authenticate("Inspector")
    inspection = fetch(db.db.inspections, row_id, "ERR_INSPECTION_NOT_FOUND")
    data = mw.body()

    # 4. body foreign keys
    document = None
    parts_document_id = data.get("parts_document_id")
    if parts_document_id is not None:
        if not isinstance(parts_document_id, str) or not parts_document_id.strip():
            mw.bad("parts_document_id", "must be a string identifier")
        document = db.db.parts_documents.get(parts_document_id)
        if document is None:
            raise ApiError("ERR_PARTS_DOCUMENT_NOT_FOUND")

    # 5. well-formedness
    category = mw.req_enum(data, "category", calc.FINDING_CATEGORIES)
    severity = mw.req_enum(data, "severity", calc.FINDING_SEVERITIES)
    description = mw.req_str(data, "description")

    # 7. ownership
    require_assigned(inspection, user_id, role)

    # 9. state-machine admissibility
    if inspection["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_INSPECTION_NOT_IN_PROGRESS", "Findings may only be recorded on an open attempt."
        )

    row = db.new_row(with_common=False)
    row.update(
        {
            "inspection_id": inspection["id"],
            "parts_document_id": parts_document_id,
            "category": category,
            "severity": severity,
            "description": description,
            "blocking": calc.finding_is_blocking(category, severity),
            "resolved": False,
            "recorded_by_inspector_id": user_id,
        }
    )
    db.db.findings[row["id"]] = row

    derive.recompute_inspection(inspection, touch_row=False)
    db.touch(inspection)

    application = db.db.applications.get(inspection["application_id"])
    vehicle = _vehicle_of(inspection)

    if category == "STOLEN_COMPONENT" and document is not None:
        if document["status"] == "VERIFIED":
            document["status"] = "REJECTED"
            document["rejection_reason"] = "STOLEN_COMPONENT"
            db.touch(document)
        if application is not None:
            derive.recompute_application(application, touch_row=False)
            derive.recompute_fee_fields(application, touch_row=False)
            db.touch(application)
        if vehicle is not None:
            cascades.open_referral(
                vehicle,
                "IDENTITY_TAMPERING",
                "AUTO_CASCADE",
                user_id,
                "Stolen component impeached during inspection.",
                application_id=inspection["application_id"],
                inspection_id=inspection["id"],
            )
        if application is not None:
            rebuilder = db.db.rebuilders.get(application["rebuilder_id"])
            if rebuilder is not None:
                derive.recompute_rebuilder(rebuilder, touch_row=True)
    return response.single(derive.finding_out(row), 201)


def _validate_checkpoints(data):
    entries = data.get("checkpoint_results")
    if not isinstance(entries, list) or len(entries) != len(calc.CHECKPOINT_WEIGHTS):
        mw.bad(
            "checkpoint_results",
            "must carry exactly one entry per weighted checkpoint (%d entries)"
            % len(calc.CHECKPOINT_WEIGHTS),
        )
    seen = []
    for entry in entries:
        if not isinstance(entry, dict):
            mw.bad("checkpoint_results", "entries must be objects carrying a code and an outcome")
        code = entry.get("code")
        outcome = entry.get("outcome")
        if code not in calc.CHECKPOINT_WEIGHTS:
            mw.bad("checkpoint_results", "carries an unknown checkpoint code")
        if outcome not in calc.CHECKPOINT_OUTCOMES:
            mw.bad("checkpoint_results", "carries an unknown checkpoint outcome")
        if code in seen:
            mw.bad("checkpoint_results", "carries a duplicated checkpoint code")
        seen.append(code)
    for code in calc.CHECKPOINT_WEIGHTS:
        if code not in seen:
            mw.bad("checkpoint_results", "is missing checkpoint %s" % code)
    return entries


@bp.post("/v1/inspections/<row_id>/complete")
def complete_inspection(row_id):
    user_id, role = mw.authenticate("Inspector")
    inspection = fetch(db.db.inspections, row_id, "ERR_INSPECTION_NOT_FOUND")
    data = mw.body()

    # 5. well-formedness
    checkpoint_results = _validate_checkpoints(data)
    vin_plate_reading = mw.req_str(data, "vin_plate_reading")

    # 7. ownership
    require_assigned(inspection, user_id, role)

    # 9. state-machine admissibility
    if inspection["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_INSPECTION_NOT_IN_PROGRESS", "Only an open attempt may be completed."
        )

    application = db.db.applications.get(inspection["application_id"])
    vehicle = _vehicle_of(inspection)
    derive.recompute_inspection(inspection, touch_row=False)

    score = calc.adequacy_score(checkpoint_results)
    critical_fail = any(
        entry["outcome"] == "FAIL" and entry["code"] in ("STRUCTURAL_FRAME", "VIN_INTEGRITY")
        for entry in checkpoint_results
    )
    vin_mismatch = vehicle is not None and vin_plate_reading != vehicle["vin"]
    auto_fail = critical_fail or bool(inspection["forced_fail"]) or vin_mismatch
    result = "PASS" if not auto_fail and score >= calc.ADEQUACY_PASS_SCORE else "FAIL"

    # 10. business safety
    if result == "PASS" and application is not None:
        for finding in derive.findings_of_app(application["id"]):
            if finding["category"] in ("STOLEN_COMPONENT", "VIN_ALTERATION") and not finding["resolved"]:
                raise ApiError(
                    "ERR_STOLEN_COMPONENT_UNRESOLVED",
                    "An unresolved identity finding stands against this application.",
                )

    # 14. identity integrity
    if vin_mismatch:
        documented = any(
            finding["category"] == "VIN_ALTERATION"
            for finding in derive.findings_of_inspection(inspection["id"])
        )
        if not documented:
            raise ApiError(
                "ERR_VIN_MISMATCH",
                "vin_plate_reading does not match the vehicle's recorded vin.",
            )

    inspection["checkpoint_results"] = checkpoint_results
    inspection["vin_plate_reading"] = vin_plate_reading
    inspection["adequacy_score"] = score
    inspection["result"] = result
    inspection["status"] = "COMPLETED_PASS" if result == "PASS" else "COMPLETED_FAIL"
    inspection["completed_at"] = db.now_iso()
    derive.recompute_inspection(inspection, touch_row=False)
    db.touch(inspection)

    if application is not None:
        application["last_inspection_result"] = result
        application["status"] = "PASSED" if result == "PASS" else "FAILED"
        derive.recompute_application(application, touch_row=False)
        db.touch(application)

    inspector = db.db.inspectors.get(inspection["inspector_id"])
    station = db.db.stations.get(inspection["station_id"])
    if inspector is not None:
        derive.recompute_inspector(inspector, touch_row=True)
    if station is not None:
        derive.recompute_station(station, touch_row=True)
    return response.single(derive.inspection_out(inspection))


@bp.post("/v1/inspections/<row_id>/cancel")
def cancel_inspection(row_id):
    mw.authenticate("StateTitleClerk")
    inspection = fetch(db.db.inspections, row_id, "ERR_INSPECTION_NOT_FOUND")
    data = mw.body()
    mw.opt_str(data, "cancellation_note")

    # 9. state-machine admissibility
    if inspection["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INSPECTION_NOT_SCHEDULED", "Only a SCHEDULED attempt may be cancelled."
        )

    cascades.cancel_attempt(inspection, "CLERK_REQUEST")

    application = db.db.applications.get(inspection["application_id"])
    if application is not None and application["status"] == "SCHEDULED":
        still_live = any(
            attempt["status"] in calc.LIVE_INSPECTION_STATUSES
            for attempt in derive.inspections_of_app(application["id"])
        )
        if not still_live:
            derive.recompute_application(application, touch_row=False)
            application["status"] = (
                "FAILED" if application["attempts_completed"] >= 1 else "DOCS_ACCEPTED"
            )
            db.touch(application)
    return response.single(derive.inspection_out(inspection))
