"""Session routes: CRUD-ish (create, lifecycle, list, read, roster)."""

from flask import Blueprint, request

from clock import parse_iso_date
from config import (
    AGE_MAX_CEILING,
    AGE_MIN_FLOOR,
    ENROLLMENT_STATUSES,
    ROLE_GUARDIAN,
    ROLE_PROGRAM_ADMIN,
    SESSION_KINDS,
    SESSION_STATUSES,
    SESSION_TITLE_MAX,
    SESSION_TITLE_MIN,
    WEEK_COUNT_MAX,
    WEEK_COUNT_MIN,
    WEEKLY_CAPACITY_MAX,
    WEEKLY_CAPACITY_MIN,
)
from db import db, init_common_fields
from errors import APIError
from middleware import get_json_body, require_auth
from response import list_response, success_response
from services.lookups import get_session
from services.pagination import paginate, parse_pagination
from services.serializers import serialize_enrollment, serialize_session
from services.sessions import (
    cancel_session,
    close_session,
    open_session,
)
from services.validators import (
    require_enum,
    require_int,
    require_string,
)


session_bp = Blueprint("session", __name__)


@session_bp.route("/sessions", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN})
def create_session():
    body = get_json_body()
    title = require_string(body, "title", min_len=SESSION_TITLE_MIN, max_len=SESSION_TITLE_MAX)
    kind = require_enum(body, "kind", SESSION_KINDS)
    age_min = require_int(body, "age_min", minimum=AGE_MIN_FLOOR, maximum=AGE_MAX_CEILING)
    age_max = require_int(body, "age_max", minimum=AGE_MIN_FLOOR, maximum=AGE_MAX_CEILING)
    if age_min > age_max:
        raise APIError("ERR_VALIDATION", "age_min must be <= age_max.")
    reference_date = require_string(body, "reference_date", min_len=10, max_len=10)
    parse_iso_date(reference_date)  # validate format
    weekly_capacity = require_int(body, "weekly_capacity", minimum=WEEKLY_CAPACITY_MIN, maximum=WEEKLY_CAPACITY_MAX)
    week_start = require_string(body, "week_start", min_len=10, max_len=10)
    ws_date = parse_iso_date(week_start)
    if ws_date.weekday() != 0:
        raise APIError("ERR_VALIDATION", "week_start must fall on a Monday.")
    week_count = require_int(body, "week_count", minimum=WEEK_COUNT_MIN, maximum=WEEK_COUNT_MAX)
    base_weekly_fee_cents = require_int(body, "base_weekly_fee_cents", minimum=0)
    rainy_pool = require_int(body, "rainy_day_pool_per_week", minimum=0, maximum=weekly_capacity)
    session = init_common_fields({
        "title": title,
        "kind": kind,
        "age_min": age_min,
        "age_max": age_max,
        "reference_date": reference_date,
        "weekly_capacity": weekly_capacity,
        "week_start": week_start,
        "week_count": week_count,
        "base_weekly_fee_cents": base_weekly_fee_cents,
        "rainy_day_pool_per_week": rainy_pool,
        "status": "DRAFT",
    })
    db.sessions[session["id"]] = session
    return success_response(serialize_session(session), status=201)


@session_bp.route("/sessions/<session_id>/open", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN})
def session_open(session_id):
    session = get_session(session_id)
    open_session(session)
    return success_response(serialize_session(session, include_days=True))


@session_bp.route("/sessions/<session_id>/close", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN})
def session_close(session_id):
    session = get_session(session_id)
    close_session(session)
    return success_response(serialize_session(session, include_days=True))


@session_bp.route("/sessions/<session_id>/cancel", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN})
def session_cancel(session_id):
    session = get_session(session_id)
    cancel_session(session)
    return success_response(serialize_session(session, include_days=True))


@session_bp.route("/sessions", methods=["GET"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def list_sessions():
    limit, offset = parse_pagination()
    kind = request.args.get("kind")
    status = request.args.get("status")
    if kind is not None and kind not in SESSION_KINDS:
        raise APIError("ERR_VALIDATION", "Invalid kind filter.")
    if status is not None and status not in SESSION_STATUSES:
        raise APIError("ERR_VALIDATION", "Invalid status filter.")
    rows = []
    for s in db.sessions.values():
        if kind is not None and s["kind"] != kind:
            continue
        if status is not None and s["status"] != status:
            continue
        rows.append(s)
    window, total = paginate(rows, limit, offset)
    return list_response([serialize_session(s) for s in window], total, limit, offset)


@session_bp.route("/sessions/<session_id>", methods=["GET"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def read_session(session_id):
    session = get_session(session_id)
    return success_response(serialize_session(session, include_days=True))


@session_bp.route("/sessions/<session_id>/roster", methods=["GET"])
@require_auth({ROLE_PROGRAM_ADMIN})
def session_roster(session_id):
    session = get_session(session_id)
    limit, offset = parse_pagination()
    week_index_raw = request.args.get("week_index")
    status = request.args.get("status")
    week_index = None
    if week_index_raw is not None:
        try:
            week_index = int(week_index_raw)
        except (TypeError, ValueError):
            raise APIError("ERR_VALIDATION", "week_index must be an integer.")
    if status is not None and status not in ENROLLMENT_STATUSES:
        raise APIError("ERR_VALIDATION", "Invalid enrollment status filter.")
    rows = []
    for e in db.enrollments.values():
        if e["session_id"] != session["id"]:
            continue
        if week_index is not None and e["week_index"] != week_index:
            continue
        if status is not None and e["status"] != status:
            continue
        rows.append(e)
    window, total = paginate(rows, limit, offset)
    return list_response([serialize_enrollment(e) for e in window], total, limit, offset)
