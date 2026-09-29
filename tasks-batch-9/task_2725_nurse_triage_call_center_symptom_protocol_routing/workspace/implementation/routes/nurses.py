"""Nurses, their immutable licences and shifts, and the staffing-adequacy read."""
from flask import Blueprint, request

import lookups
from auth import ALL_ROLES, CHARGE_NURSE, PLATFORM_ADMIN, PRACTICE_LIAISON, authorize
from calc import license_status, shift_status, staffing_adequacy
from envelope import list_response, object_response, pagination_params
from errors import ApiError
from serializers import license_json, nurse_json, shift_json
from store import base_record, ordered, store
from util import STATE_RE, iso, whole_minutes
from validators import (body, get_date, get_int, get_string, get_timestamp,
                        query_enum, query_string, query_timestamp)

bp = Blueprint("nurses", __name__)

LICENSE_STATUSES = ("ACTIVE", "EXPIRED")
SHIFT_STATUSES = ("SCHEDULED", "ACTIVE", "ENDED")

DEFAULT_MAX_CONCURRENT_CALLS = 8
DEFAULT_HIGH_RISK_CAP = 1


@bp.route("/nurses", methods=["POST"])
@authorize([PLATFORM_ADMIN])
def create_nurse():
    data = body()
    full_name = get_string(data, "full_name", min_len=1, max_len=120)
    seniority = get_int(data, "seniority_level", minimum=1, maximum=5)
    max_calls = get_int(data, "max_concurrent_calls", required=False, minimum=1, maximum=8)
    high_risk_cap = get_int(data, "high_risk_cap", required=False, minimum=1, maximum=5)

    record = base_record()
    record.update({
        "full_name": full_name,
        "seniority_level": seniority,
        "max_concurrent_calls": (max_calls if max_calls is not None
                                 else DEFAULT_MAX_CONCURRENT_CALLS),
        "high_risk_cap": (high_risk_cap if high_risk_cap is not None
                          else DEFAULT_HIGH_RISK_CAP),
        "active_call_load": 0,
        "pending_high_risk_count": 0,
        "intake_eligibility": "ON_ROTATION",
    })
    store.nurses[record["id"]] = record
    return object_response(nurse_json(record), 201)


@bp.route("/nurses/<nurse_id>", methods=["GET"])
@authorize(ALL_ROLES)
def read_nurse(nurse_id):
    return object_response(nurse_json(lookups.nurse(nurse_id)))


@bp.route("/nurses/<nurse_id>/licenses", methods=["POST"])
@authorize([PLATFORM_ADMIN])
def create_license(nurse_id):
    data = body()
    state_code = get_string(data, "state_code", pattern=STATE_RE)
    number = get_string(data, "license_number", min_len=1, max_len=40)
    expires_on = get_date(data, "expires_on")

    lookups.nurse(nurse_id)

    record = base_record(with_version=False)
    record.update({
        "nurse_id": nurse_id,
        "state_code": state_code,
        "license_number": number,
        "expires_on": expires_on,
    })
    store.licenses[record["id"]] = record
    return object_response(license_json(record), 201)


@bp.route("/nurses/<nurse_id>/licenses", methods=["GET"])
@authorize(ALL_ROLES)
def list_licenses(nurse_id):
    limit, offset = pagination_params()
    state_code = query_string("state_code")
    status = query_enum("status", LICENSE_STATUSES)
    lookups.nurse(nurse_id)
    rows = [l for l in ordered(store.licenses) if l["nurse_id"] == nurse_id]
    if state_code is not None:
        rows = [l for l in rows if l["state_code"] == state_code]
    if status is not None:
        rows = [l for l in rows if license_status(l) == status]
    return list_response(rows, license_json, limit, offset)


@bp.route("/nurses/<nurse_id>/shifts", methods=["POST"])
@authorize([PLATFORM_ADMIN])
def create_shift(nurse_id):
    data = body()
    start = get_timestamp(data, "start_utc")
    end = get_timestamp(data, "end_utc")
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", "end_utc must be after start_utc.")

    lookups.nurse(nurse_id)

    for existing in ordered(store.shifts):
        if existing["nurse_id"] != nurse_id:
            continue
        if existing["start_utc"] < end and start < existing["end_utc"]:
            raise ApiError("ERR_SHIFT_OVERLAP")

    record = base_record(with_version=False)
    record.update({
        "nurse_id": nurse_id,
        "start_utc": start,
        "end_utc": end,
        "scheduled_minutes": whole_minutes(start, end),
    })
    store.shifts[record["id"]] = record
    return object_response(shift_json(record), 201)


@bp.route("/nurses/<nurse_id>/shifts", methods=["GET"])
@authorize(ALL_ROLES)
def list_shifts(nurse_id):
    limit, offset = pagination_params()
    status = query_enum("status", SHIFT_STATUSES)
    lookups.nurse(nurse_id)
    rows = [s for s in ordered(store.shifts) if s["nurse_id"] == nurse_id]
    if status is not None:
        rows = [s for s in rows if shift_status(s) == status]
    return list_response(rows, shift_json, limit, offset)


@bp.route("/staffing-adequacy", methods=["GET"])
@authorize([PLATFORM_ADMIN, CHARGE_NURSE, PRACTICE_LIAISON])
def read_staffing_adequacy():
    state_code = request.args.get("state_code")
    if state_code is None or state_code == "":
        raise ApiError("ERR_INVALID_REQUEST", "state_code is required.")
    if not STATE_RE.match(state_code):
        raise ApiError("ERR_INVALID_REQUEST", "state_code is malformed.")
    window_start = query_timestamp("window_start_utc", required=True)
    window_end = query_timestamp("window_end_utc", required=True)
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "window_end_utc must be after window_start_utc.")
    result = staffing_adequacy(state_code, window_start, window_end)
    payload = {
        "state_code": state_code,
        "window_start_utc": iso(window_start),
        "window_end_utc": iso(window_end),
    }
    payload.update(result)
    return object_response(payload)
