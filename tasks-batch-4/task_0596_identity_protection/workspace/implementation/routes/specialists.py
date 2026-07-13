from flask import Blueprint, request

from db import db, new_row, touch
from errors import ApiError
from middleware import (
    auth,
    body,
    must_exist,
    must_exist_fk,
    opt_int,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    require_specialist_owner,
)
from response import ok, ok_list, paginate, read_pagination
from serializers import ser, ser_many
from services import calc

bp = Blueprint("specialists", __name__)

SPECIALIST_TIERS = ("TIER1", "TIER2", "TIER3")
WORKING_STATUSES = ("ASSIGNED", "IN_PROGRESS", "PENDING_SUBSCRIBER")


@bp.post("/idp/specialists")
def create_specialist():
    auth("PlatformAdmin")
    data = body()
    specialist = new_row(
        full_name=req_str(data, "full_name"),
        tier=req_enum(data, "tier", SPECIALIST_TIERS),
        max_caseload=req_int(data, "max_caseload", minimum=1),
        max_concurrent_engagements=opt_int(data, "max_concurrent_engagements", 1, minimum=1),
        active_case_count=0,
        status="AVAILABLE",
    )
    db.specialists[specialist["id"]] = specialist
    return ok(ser(specialist), 201)


@bp.get("/idp/specialists/<specialist_id>")
def read_specialist(specialist_id):
    auth("PlatformAdmin", "RestorationSpecialist", "ClaimsAdjuster")
    return ok(ser(must_exist("specialists", specialist_id)))


# ----------------------------------------------------------------- engagements
@bp.post("/idp/specialist-engagements")
def create_engagement():
    role, user_id = auth("PlatformAdmin", "RestorationSpecialist")
    data = body()

    specialist = must_exist_fk("specialists", data, "specialist_id")
    case = must_exist_fk("cases", data, "case_id")

    if specialist is not None:
        require_specialist_owner(role, user_id, specialist["id"])
        if case is not None:
            require_specialist_owner(role, user_id, case["specialist_id"])

    if specialist is None:
        req_str(data, "specialist_id")
    if case is None:
        req_str(data, "case_id")
    start = req_datetime(data, "window_start")
    end = req_datetime(data, "window_end")
    expected_version = req_int(data, "expected_specialist_version")

    if expected_version != specialist["version"]:
        raise ApiError(
            "ERR_STALE_SPECIALIST_VERSION",
            "expected_specialist_version does not match the specialist's current version.",
        )

    if case["status"] not in WORKING_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE",
            "The case is not in a state that accepts engagements.",
        )
    if case["specialist_id"] != specialist["id"]:
        raise ApiError(
            "ERR_INVALID_STATE",
            "The engagement's specialist does not match the case's assigned specialist.",
        )

    if end <= start:
        raise ApiError("ERR_INVALID_WINDOW", "window_end must be strictly after window_start.")
    if start < calc.now():
        raise ApiError("ERR_WINDOW_IN_PAST", "window_start may not precede the logical clock.")

    if calc.engagement_capacity_exceeded(specialist, start, end):
        raise ApiError(
            "ERR_ENGAGEMENT_CAPACITY_EXCEEDED",
            "The booking exceeds the specialist's concurrent-engagement capacity.",
        )

    engagement = new_row(
        specialist_id=specialist["id"],
        case_id=case["id"],
        window_start=data["window_start"],
        window_end=data["window_end"],
    )
    engagement["_ws"] = start
    engagement["_we"] = end
    db.engagements[engagement["id"]] = engagement

    if case["status"] == "ASSIGNED":
        case["status"] = "IN_PROGRESS"
        touch(case)

    touch(specialist)
    return ok(ser(engagement), 201)


@bp.get("/idp/specialist-engagements")
def list_engagements():
    auth("PlatformAdmin", "RestorationSpecialist")
    limit, offset = read_pagination()

    rows = list(db.engagements.values())
    specialist_id = request.args.get("specialist_id")
    if specialist_id:
        rows = [e for e in rows if e["specialist_id"] == specialist_id]
    case_id = request.args.get("case_id")
    if case_id:
        rows = [e for e in rows if e["case_id"] == case_id]

    rows.sort(key=lambda e: (e["_ws"], e["_seq"]))
    page, total = paginate(rows, limit, offset)
    return ok_list(ser_many(page), limit, offset, total)


@bp.get("/idp/specialist-engagements/<engagement_id>")
def read_engagement(engagement_id):
    auth("PlatformAdmin", "RestorationSpecialist")
    engagement = db.engagements.get(engagement_id)
    if engagement is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Engagement not found.")
    return ok(ser(engagement))
