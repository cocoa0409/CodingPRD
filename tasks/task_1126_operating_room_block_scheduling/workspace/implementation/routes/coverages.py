"""AnesthesiaCoverage endpoints."""

from flask import Blueprint, request as freq

from db import db
from errors import (
    ApiError,
    ERR_COVERAGE_NOT_ACTIVE,
    ERR_COVERAGE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_TIME_RANGE,
    ERR_ROOM_NOT_FOUND,
)
from middleware import get_auth, require_roles, get_json_body
from response import success_object, paginate
from serializers import coverage_json
from services import new_common, touch
from util import is_int, parse_date

bp = Blueprint("coverages", __name__)

COVERAGE_STATUSES = {"ACTIVE", "WITHDRAWN"}


@bp.route("/anesthesia-coverages", methods=["POST"])
def create_coverage():
    require_roles("AnesthesiaCoordinator")
    body = get_json_body()
    or_id = body.get("or_id")
    date = body.get("date")
    start_minute = body.get("start_minute")
    end_minute = body.get("end_minute")
    provider_ref = body.get("provider_ref")

    # body FK existence
    if isinstance(or_id, str) and or_id not in db.rooms:
        raise ApiError(ERR_ROOM_NOT_FOUND, 404, "operating room not found")
    # shape
    if not isinstance(or_id, str) or not or_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "or_id is required")
    try:
        parse_date(date)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "date must be YYYY-MM-DD")
    if not is_int(start_minute) or not (0 <= start_minute <= 1440):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "start_minute must be an integer in [0,1440]"
        )
    if not is_int(end_minute) or not (0 <= end_minute <= 1440):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "end_minute must be an integer in [0,1440]"
        )
    if not isinstance(provider_ref, str) or not provider_ref:
        raise ApiError(ERR_INVALID_REQUEST, 400, "provider_ref is required")
    # time range
    if end_minute <= start_minute:
        raise ApiError(
            ERR_INVALID_TIME_RANGE, 400, "end_minute must be after start_minute"
        )
    rec = new_common()
    rec.update(
        {
            "or_id": or_id,
            "date": date,
            "start_minute": start_minute,
            "end_minute": end_minute,
            "provider_ref": provider_ref,
            "status": "ACTIVE",
        }
    )
    db.coverages[rec["id"]] = rec
    return success_object(coverage_json(rec), 201)


@bp.route("/anesthesia-coverages", methods=["GET"])
def list_coverages():
    get_auth()
    items = list(db.coverages.values())
    or_id = freq.args.get("or_id")
    if or_id is not None:
        items = [c for c in items if c["or_id"] == or_id]
    dt = freq.args.get("date")
    if dt is not None:
        items = [c for c in items if c["date"] == dt]
    st = freq.args.get("status")
    if st is not None:
        if st not in COVERAGE_STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid status filter")
        items = [c for c in items if c["status"] == st]
    out = [coverage_json(c) for c in items]
    out.sort(key=lambda r: (r["created_at"],))
    return paginate(out)


@bp.route("/anesthesia-coverages/<coverageId>", methods=["GET"])
def get_coverage(coverageId):
    get_auth()
    rec = db.coverages.get(coverageId)
    if rec is None:
        raise ApiError(ERR_COVERAGE_NOT_FOUND, 404, "anesthesia coverage not found")
    return success_object(coverage_json(rec))


@bp.route("/anesthesia-coverages/<coverageId>/withdraw", methods=["POST"])
def withdraw_coverage(coverageId):
    require_roles("AnesthesiaCoordinator")
    rec = db.coverages.get(coverageId)
    if rec is None:
        raise ApiError(ERR_COVERAGE_NOT_FOUND, 404, "anesthesia coverage not found")
    if rec["status"] != "ACTIVE":
        raise ApiError(
            ERR_COVERAGE_NOT_ACTIVE, 409, "withdraw requires coverage status ACTIVE"
        )
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return success_object(coverage_json(rec))
