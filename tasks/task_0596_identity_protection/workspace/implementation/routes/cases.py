from flask import Blueprint, request

from db import by_seq, db, touch
from errors import ApiError
from middleware import (
    auth,
    body,
    must_exist,
    must_exist_fk,
    req_str,
    require_enrollment_active,
    require_specialist_owner,
    require_subscriber_owner,
)
from response import ok, ok_list, paginate, read_pagination
from serializers import ser, ser_many
from services import calc

bp = Blueprint("cases", __name__)


@bp.get("/idp/restoration-cases")
def list_cases():
    role, user_id = auth(
        "Subscriber", "PlatformAdmin", "RestorationSpecialist", "ClaimsAdjuster"
    )
    limit, offset = read_pagination()

    rows = list(db.cases.values())
    if role == "Subscriber":
        rows = [c for c in rows if c["subscriber_id"] == user_id]

    for key in ("subscriber_id", "origin_alert_id", "specialist_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [c for c in rows if c[key] == value]

    rows = by_seq(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(ser_many(page), limit, offset, total)


@bp.get("/idp/restoration-cases/<case_id>")
def read_case(case_id):
    role, user_id = auth(
        "Subscriber", "PlatformAdmin", "RestorationSpecialist", "ClaimsAdjuster"
    )
    case = must_exist("cases", case_id)
    require_subscriber_owner(role, user_id, case["subscriber_id"])
    return ok(ser(case))


@bp.post("/idp/restoration-cases/<case_id>/assign")
def assign(case_id):
    auth("PlatformAdmin")
    case = must_exist("cases", case_id)
    data = body()
    specialist = must_exist_fk("specialists", data, "specialist_id")
    if specialist is None and data.get("specialist_id") is not None:
        # present but not a well-formed id string
        req_str(data, "specialist_id")

    if case["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Restoration case is not OPEN.")

    subscriber = db.subscribers[case["subscriber_id"]]
    require_enrollment_active(subscriber)

    required_rank = calc.TIER_RANK[case["required_specialist_tier"]]
    if specialist is not None:
        if calc.TIER_RANK[specialist["tier"]] < required_rank:
            raise ApiError(
                "ERR_SPECIALIST_TIER_INSUFFICIENT",
                "The specialist's tier is below the case's required tier.",
            )
        if specialist["active_case_count"] >= specialist["max_caseload"]:
            raise ApiError("ERR_SPECIALIST_AT_CAPACITY", "The specialist is at capacity.")
    else:
        specialist = calc.select_specialist(case)
        if specialist is None:
            raise ApiError(
                "ERR_NO_ELIGIBLE_SPECIALIST",
                "No specialist satisfies the case's eligibility filter.",
            )

    case["specialist_id"] = specialist["id"]
    case["status"] = "ASSIGNED"
    touch(case)

    calc.recompute_specialist(specialist)
    touch(specialist)

    return ok(ser(case))


@bp.post("/idp/restoration-cases/<case_id>/request-info")
def request_info(case_id):
    role, user_id = auth("RestorationSpecialist")
    case = must_exist("cases", case_id)
    require_specialist_owner(role, user_id, case["specialist_id"])
    subscriber = db.subscribers[case["subscriber_id"]]

    data = body()
    info_request = req_str(data, "info_request")

    if case["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Restoration case is not IN_PROGRESS.")
    require_enrollment_active(subscriber)

    case["info_request"] = info_request
    case["status"] = "PENDING_SUBSCRIBER"
    touch(case)
    return ok(ser(case))


@bp.post("/idp/restoration-cases/<case_id>/provide-info")
def provide_info(case_id):
    role, user_id = auth("Subscriber")
    case = must_exist("cases", case_id)
    require_subscriber_owner(role, user_id, case["subscriber_id"])
    subscriber = db.subscribers[case["subscriber_id"]]

    data = body()
    info_response = req_str(data, "info_response")

    if case["status"] != "PENDING_SUBSCRIBER":
        raise ApiError("ERR_INVALID_STATE", "Restoration case is not PENDING_SUBSCRIBER.")
    require_enrollment_active(subscriber)

    case["info_response"] = info_response
    case["status"] = "IN_PROGRESS"
    touch(case)
    return ok(ser(case))


@bp.post("/idp/restoration-cases/<case_id>/resolve")
def resolve(case_id):
    role, user_id = auth("RestorationSpecialist")
    case = must_exist("cases", case_id)
    require_specialist_owner(role, user_id, case["specialist_id"])
    subscriber = db.subscribers[case["subscriber_id"]]

    data = body()
    summary = req_str(data, "resolution_summary")

    if case["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Restoration case is not IN_PROGRESS.")
    require_enrollment_active(subscriber)

    case["resolution_summary"] = summary
    case["status"] = "RESOLVED"
    touch(case)

    # Compensation hop: the case left the working set.
    specialist = db.specialists.get(case["specialist_id"])
    if specialist is not None:
        calc.recompute_specialist(specialist)
        touch(specialist)

    # Cross-entity hop: the origin alert is carried to RESOLVED by the system.
    calc.resolve_origin_alert(case)

    calc.recompute_risk(subscriber)
    touch(subscriber)

    return ok(ser(case))
