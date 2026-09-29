"""Coverage windows: the after-hours authorisation the advice line answers under."""
from datetime import timedelta

from flask import Blueprint

import lookups
from auth import ALL_ROLES, PLATFORM_ADMIN, PRACTICE_LIAISON, authorize, practice_scope_guard
from calc import lazy_expire_coverage_windows
from envelope import object_response
from errors import ApiError
from serializers import coverage_window_json
from store import base_record, ordered, store, touch
from validators import body, get_enum, get_string, get_timestamp

bp = Blueprint("coverage", __name__)

COVERAGE_KINDS = ("NIGHTS", "WEEKEND", "HOLIDAY", "OVERFLOW")
BUFFER = timedelta(minutes=30)
BLOCKING_STATUSES = ("DRAFT", "ACTIVE")


@bp.route("/coverage-windows", methods=["POST"])
@authorize([PLATFORM_ADMIN, PRACTICE_LIAISON])
def create_coverage_window():
    data = body()
    practice_id = get_string(data, "practice_id")
    start = get_timestamp(data, "start_utc")
    end = get_timestamp(data, "end_utc")
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", "end_utc must be after start_utc.")
    kind = get_enum(data, "coverage_kind", COVERAGE_KINDS)

    practice = lookups.practice(practice_id)
    if practice["status"] == "SUSPENDED":
        raise ApiError("ERR_PRACTICE_SUSPENDED")

    for existing in ordered(store.coverage_windows):
        if existing["practice_id"] != practice_id:
            continue
        if existing["status"] not in BLOCKING_STATUSES:
            continue
        if (existing["start_utc"] - BUFFER) < end and start < (existing["end_utc"] + BUFFER):
            raise ApiError("ERR_COVERAGE_WINDOW_CONFLICT")

    record = base_record()
    record.update({
        "practice_id": practice_id,
        "start_utc": start,
        "end_utc": end,
        "coverage_kind": kind,
        "status": "DRAFT",
        "suspend_reason": None,
    })
    store.coverage_windows[record["id"]] = record
    return object_response(coverage_window_json(record), 201)


@bp.route("/coverage-windows/<window_id>/activate", methods=["POST"])
@authorize([PLATFORM_ADMIN, PRACTICE_LIAISON])
def activate_coverage_window(window_id):
    window = lookups.coverage_window(window_id)
    practice_scope_guard(window["practice_id"])
    lazy_expire_coverage_windows(window["practice_id"])
    if window["status"] != "DRAFT":
        raise ApiError("ERR_COVERAGE_WINDOW_INVALID_STATE")
    practice = store.practices.get(window["practice_id"])
    if practice is not None and practice["compliance_posture"] == "UNDER_REVIEW":
        raise ApiError("ERR_PRACTICE_COMPLIANCE_HOLD")
    window["status"] = "ACTIVE"
    touch(window)
    return object_response(coverage_window_json(window))


@bp.route("/coverage-windows/<window_id>", methods=["GET"])
@authorize(ALL_ROLES)
def read_coverage_window(window_id):
    window = lookups.coverage_window(window_id)
    lazy_expire_coverage_windows(window["practice_id"])
    return object_response(coverage_window_json(window))
