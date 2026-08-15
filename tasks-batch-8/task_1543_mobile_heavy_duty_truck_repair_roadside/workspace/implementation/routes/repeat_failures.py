"""RepeatFailureCase endpoints: open, review, decide (comeback confirmation)."""
from flask import Blueprint, request

from db import store, new_record, touch
from errors import (ApiError, err_not_found, err_invalid_state)
from middleware import auth
from response import success
from serializers import serialize
from services.cascades import append_event, wall_now
from util import Field, validate_body, parse_pagination, paginate

bp = Blueprint("repeat_failures", __name__)

OPEN_STATES = {"OPEN", "UNDER_REVIEW", "CONFIRMED_COMEBACK"}


def _get_case(case_id):
    c = store.repeat_cases.get(case_id)
    if c is None:
        raise err_not_found("RepeatFailureCase not found")
    return c


@bp.route("/roadside/repeat-failure-cases", methods=["POST"])
def create_case():
    auth(["Dispatcher", "OpsAdmin"])
    vals = validate_body(request.get_json(silent=True), [
        Field("vehicle_id", "string", required=True),
        Field("original_service_call_id", "string", required=True),
        Field("new_service_call_id", "string", required=True),
    ])
    vehicle = store.vehicles.get(vals["vehicle_id"])
    if vehicle is None:
        raise err_not_found("Vehicle not found")
    original = store.service_calls.get(vals["original_service_call_id"])
    if original is None:
        raise err_not_found("Original ServiceCall not found")
    new_call = store.service_calls.get(vals["new_service_call_id"])
    if new_call is None:
        raise err_not_found("New ServiceCall not found")
    if (original["vehicle_id"] != vehicle["id"]
            or new_call["vehicle_id"] != vehicle["id"]):
        raise ApiError("ERR_VEHICLE_MISMATCH",
                       "Referenced calls belong to a different vehicle", 409)
    if original["status"] != "CLOSED":
        raise err_invalid_state("original_service_call_id must be CLOSED")
    if new_call["symptom_category"] != original["symptom_category"]:
        raise ApiError("ERR_REPEAT_SYMPTOM_MISMATCH",
                       "Repeat case links calls with different symptom_category",
                       409)
    for case in store.repeat_cases.values():
        if (case["vehicle_id"] == vehicle["id"]
                and case["status"] in OPEN_STATES):
            raise ApiError("ERR_DUPLICATE_OPEN_CASE",
                           "Vehicle already has an open repeat-failure case",
                           409)
    completed_at = original.get("completed_at")
    if completed_at is not None:
        window_days = int(
            (new_call["received_at"] - completed_at).total_seconds() // 86400)
    else:
        window_days = 0
    completion_miles = original.get("completion_odometer_miles") or 0
    miles_since = vehicle["odometer_miles"] - completion_miles
    if window_days <= 30 and miles_since <= 1000:
        policy = "NO_CHARGE"
    elif window_days <= 45 and miles_since <= 2000:
        policy = "REDUCED"
    else:
        policy = "FULL"
    rec = new_record()
    now = wall_now()
    rec.update({
        "_created": now, "_updated": now,
        "vehicle_id": vehicle["id"],
        "original_service_call_id": original["id"],
        "new_service_call_id": new_call["id"],
        "symptom_category": new_call["symptom_category"],
        "window_days": window_days,
        "miles_since_repair": miles_since,
        "charge_policy": policy,
        "status": "OPEN",
        "decided_by": None,
        "decision_note": None,
    })
    store.repeat_cases[rec["id"]] = rec
    return success(serialize("repeat_case", rec), status=201)


@bp.route("/roadside/repeat-failure-cases/<repeatFailureCaseId>",
          methods=["GET"])
def get_case(repeatFailureCaseId):
    auth(["OpsAdmin", "Dispatcher"])
    return success(serialize("repeat_case", _get_case(repeatFailureCaseId)))


@bp.route("/roadside/repeat-failure-cases", methods=["GET"])
def list_cases():
    auth(["OpsAdmin", "Dispatcher"])
    limit, offset = parse_pagination(request.args)
    veh_f = request.args.get("vehicle_id")
    orig_f = request.args.get("original_service_call_id")
    new_f = request.args.get("new_service_call_id")
    status_f = request.args.get("status")
    items = sorted(store.repeat_cases.values(), key=lambda r: r["_seq"])
    if veh_f is not None:
        items = [c for c in items if c["vehicle_id"] == veh_f]
    if orig_f is not None:
        items = [c for c in items if c["original_service_call_id"] == orig_f]
    if new_f is not None:
        items = [c for c in items if c["new_service_call_id"] == new_f]
    if status_f is not None:
        items = [c for c in items if c["status"] == status_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize("repeat_case", c) for c in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})


@bp.route("/roadside/repeat-failure-cases/<repeatFailureCaseId>/review",
          methods=["POST"])
def review(repeatFailureCaseId):
    auth(["Dispatcher", "OpsAdmin"])
    case = _get_case(repeatFailureCaseId)
    validate_body(request.get_json(silent=True), [])
    if case["status"] != "OPEN":
        raise err_invalid_state("Review requires status OPEN")
    case["status"] = "UNDER_REVIEW"
    touch(case, wall_now())
    return success(serialize("repeat_case", case))


@bp.route("/roadside/repeat-failure-cases/<repeatFailureCaseId>/decide",
          methods=["POST"])
def decide(repeatFailureCaseId):
    uid, role = auth(["OpsAdmin"])
    case = _get_case(repeatFailureCaseId)
    vals = validate_body(request.get_json(silent=True), [
        Field("decision", "enum", required=True,
              enum={"CONFIRMED_COMEBACK", "REJECTED"}),
        Field("decision_note", "string"),
    ])
    if case["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Decide requires status UNDER_REVIEW")
    if vals["decision"] == "CONFIRMED_COMEBACK":
        if case["charge_policy"] == "FULL":
            raise ApiError("ERR_REPEAT_WINDOW_EXPIRED",
                           "Comeback confirmation attempted when charge_policy "
                           "is FULL", 409)
        new_call = store.service_calls.get(case["new_service_call_id"])
        if new_call is not None:
            new_call["is_comeback"] = True
            new_call["repeat_of_call_id"] = case["original_service_call_id"]
            touch(new_call, wall_now())
        original = store.service_calls.get(case["original_service_call_id"])
        if original is not None and original["status"] == "CLOSED":
            original["status"] = "REOPENED"
            original["reopened_count"] = original.get("reopened_count", 0) + 1
            touch(original, wall_now())
            append_event(original["id"], "CALL_REOPENED", "system", "system")
        case["status"] = "CONFIRMED_COMEBACK"
        case["decided_by"] = uid
        if vals.get("decision_note") is not None:
            case["decision_note"] = vals["decision_note"]
    else:
        case["status"] = "REJECTED"
        case["decided_by"] = uid
        case["decision_note"] = vals.get("decision_note")
    touch(case, wall_now())
    return success(serialize("repeat_case", case))
