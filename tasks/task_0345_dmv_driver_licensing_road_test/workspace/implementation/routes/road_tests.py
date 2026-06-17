"""Road-test appointment endpoints (PRD section 3.4, 3.5)."""
from flask import Blueprint, request

import db
from db import db as store
from db import LICENSE_CLASSES
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import serialize
from services import calculations as calc
from services.common import (
    new_common, touch, get_json_body, paginate, require_fields, require_int,
)
from services.lookup import fetch

bp = Blueprint("road_tests", __name__)


def _validate_maneuvers(maneuver_scores, value_key):
    if not isinstance(maneuver_scores, list) or not maneuver_scores:
        raise err("ERR_INVALID_REQUEST", "maneuver_scores must be a non-empty array")
    for m in maneuver_scores:
        if not isinstance(m, dict):
            raise err("ERR_INVALID_REQUEST", "each maneuver must be an object")
        if "weight" not in m or not isinstance(m["weight"], (int, float)) or isinstance(m["weight"], bool):
            raise err("ERR_INVALID_REQUEST", "maneuver weight must be numeric")
        if value_key not in m or not isinstance(m[value_key], (int, float)) or isinstance(m[value_key], bool):
            raise err("ERR_INVALID_REQUEST", f"maneuver {value_key} must be numeric")


@bp.post("/road-test-appointments")
def book_road_test():
    _, role = get_user_context()
    require_role(role, {"LicenseClerk"})
    body = get_json_body()
    require_fields(body, ["driver_record_id", "examiner_id", "license_class",
                          "slot_start_period", "slot_end_period"])
    driver_record_id = body["driver_record_id"]
    examiner_id = body["examiner_id"]
    # existence left-to-right
    fetch(store.driver_records, driver_record_id)
    examiner = fetch(store.examiners, examiner_id)
    license_class = body["license_class"]
    if license_class not in LICENSE_CLASSES:
        raise err("ERR_INVALID_REQUEST", "invalid license_class")
    slot_start = require_int(body, "slot_start_period")
    slot_end = require_int(body, "slot_end_period")
    # field-domain (priority 3.5): slot interval
    if slot_end <= slot_start:
        raise err("ERR_INVALID_SLOT_INTERVAL", "slot_end_period must exceed slot_start_period")
    # business: examiner certified (priority 9)
    if license_class not in examiner["certified_classes"]:
        raise err("ERR_EXAMINER_NOT_CERTIFIED", "Examiner not certified for class")
    # business constraint: slot overlap on same examiner (priority 10), half-open
    for a in store.road_test_appointments.values():
        if a["examiner_id"] != examiner_id:
            continue
        if a["status"] == "CANCELLED":
            continue
        if slot_start < a["slot_end_period"] and a["slot_start_period"] < slot_end:
            raise err("ERR_EXAMINER_SLOT_CONFLICT", "Slot overlaps existing appointment")
    appt = new_common(
        driver_record_id=driver_record_id,
        examiner_id=examiner_id,
        license_class=license_class,
        slot_start_period=slot_start,
        slot_end_period=slot_end,
        maneuver_scores=None,
        provisional_score=None,
        final_score=None,
        outcome=None,
        scored_by_examiner_id=None,
        status="BOOKED",
    )
    store.road_test_appointments[appt["id"]] = appt
    return success(serialize.road_test_appointment(appt), 201, "object")


@bp.get("/road-test-appointments/<aid>")
def get_road_test(aid):
    _, role = get_user_context()
    require_role(role, {"LicenseClerk", "AdjudicationOfficer", "Examiner"})
    appt = fetch(store.road_test_appointments, aid)
    return success(serialize.road_test_appointment(appt), 200, "object")


@bp.get("/road-test-appointments/<aid>/licenses")
def list_appt_licenses(aid):
    _, role = get_user_context()
    require_role(role, {"LicenseClerk", "AdjudicationOfficer", "Examiner"})
    fetch(store.road_test_appointments, aid)
    status = request.args.get("status")
    items = [
        l for l in store.licenses.values()
        if l.get("road_test_appointment_id") == aid
        and (status is None or l["status"] == status)
    ]
    data, pagination = paginate(items, serialize.license_obj)
    return success(data, 200, "array", pagination)


@bp.post("/road-test-appointments/<aid>/proctor")
def proctor(aid):
    user_id, role = get_user_context()
    require_role(role, {"Examiner"})
    appt = fetch(store.road_test_appointments, aid)
    body = get_json_body()
    require_fields(body, ["maneuver_scores"])
    _validate_maneuvers(body["maneuver_scores"], "auto_score")
    # state (priority 5)
    if appt["status"] != "BOOKED":
        raise err("ERR_APPT_NOT_BOOKED", "Appointment not BOOKED")
    # ownership: acting examiner == appointment.examiner_id
    if user_id != appt["examiner_id"]:
        raise err("ERR_EXAMINER_MISMATCH", "Acting examiner is not the assigned examiner")
    # slot started
    if store.current_period < appt["slot_start_period"]:
        raise err("ERR_SLOT_NOT_STARTED", "current clock < slot_start_period")
    # knowledge prerequisite
    record = store.driver_records[appt["driver_record_id"]]
    if not calc.knowledge_test_passed(record, store):
        raise err("ERR_KNOWLEDGE_TEST_REQUIRED", "knowledge_test_passed required")
    appt["maneuver_scores"] = body["maneuver_scores"]
    appt["provisional_score"] = calc.weighted_score(body["maneuver_scores"], "auto_score")
    appt["scored_by_examiner_id"] = user_id
    appt["status"] = "PROCTORED"
    touch(appt)
    return success(serialize.road_test_appointment(appt), 200, "object")


@bp.post("/road-test-appointments/<aid>/score")
def score(aid):
    user_id, role = get_user_context()
    require_role(role, {"Examiner"})
    appt = fetch(store.road_test_appointments, aid)
    body = get_json_body()
    require_fields(body, ["maneuver_scores"])
    _validate_maneuvers(body["maneuver_scores"], "score")
    # state (priority 5)
    if appt["status"] != "PROCTORED":
        raise err("ERR_APPT_NOT_PROCTORED", "Appointment not PROCTORED")
    # ownership
    if user_id != appt["examiner_id"]:
        raise err("ERR_EXAMINER_MISMATCH", "Acting examiner is not the assigned examiner")
    appt["maneuver_scores"] = body["maneuver_scores"]
    final = calc.weighted_score(body["maneuver_scores"], "score")
    appt["final_score"] = final
    appt["outcome"] = "PASS" if final >= db.ROAD_PASS_THRESHOLD else "FAIL"
    appt["status"] = "SCORED"
    touch(appt)
    return success(serialize.road_test_appointment(appt), 200, "object")


@bp.post("/road-test-appointments/<aid>/cancel")
def cancel(aid):
    _, role = get_user_context()
    require_role(role, {"Examiner", "LicenseClerk"})
    appt = fetch(store.road_test_appointments, aid)
    if appt["status"] != "BOOKED":
        raise err("ERR_APPT_NOT_BOOKED", "Appointment not BOOKED")
    appt["status"] = "CANCELLED"
    touch(appt)
    return success(serialize.road_test_appointment(appt), 200, "object")
