"""Coverage window endpoints."""

from flask import Blueprint, request

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
    ERR_COVERAGE_WINDOW_NOT_OPEN, ERR_COVERAGE_WINDOW_FULL,
    ERR_ALREADY_ENROLLED, ERR_ENROLL_SHIFT_CONFLICT,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import make_entity, touch, intervals_overlap
from services import serializers
import clock

bp = Blueprint("coverage", __name__)

ALL_ROLES = ["GroupAdmin", "Hospitalist", "ConsultingSpecialist"]
WINDOW_TYPES = {"NIGHT_PRIMARY", "NIGHT_CROSS_COVER"}


def _paginate(items, serializer):
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameters", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameters", 400)
    items = sorted(items, key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(i) for i in page], limit, offset, total)


def _body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be an object", 400)
    return data


@bp.route("/coverage-windows", methods=["POST"])
def create_window():
    require_roles(["GroupAdmin"])
    body = _body()
    window_date = body.get("window_date")
    window_type = body.get("window_type")
    start_at = clock.parse_iso(body.get("start_at"))
    end_at = clock.parse_iso(body.get("end_at"))
    capacity = body.get("capacity")

    if clock.parse_date(window_date) is None:
        raise ApiError(ERR_INVALID_REQUEST, "window_date must be YYYY-MM-DD", 400)
    if window_type not in WINDOW_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, "invalid window_type", 400)
    if start_at is None or end_at is None:
        raise ApiError(ERR_INVALID_REQUEST, "start_at and end_at must be ISO8601 datetimes", 400)
    if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
        raise ApiError(ERR_INVALID_REQUEST, "capacity must be an integer >= 1", 400)
    if end_at <= start_at:
        raise ApiError(ERR_INVALID_REQUEST, "end_at must be strictly after start_at", 400)

    w = make_entity({
        "window_date": window_date,
        "window_type": window_type,
        "start_at": start_at,
        "end_at": end_at,
        "capacity": capacity,
        "enrolled_hospitalist_ids": [],
        "enrolled_count": 0,
        "status": "OPEN",
        "current_load": 0,
    })
    store["coverage_windows"][w["id"]] = w
    return success_object(serializers.coverage_window(w), 201)


@bp.route("/coverage-windows", methods=["GET"])
def list_windows():
    require_roles(ALL_ROLES)
    items = list(store["coverage_windows"].values())
    wt = request.args.get("window_type")
    if wt is not None:
        items = [w for w in items if w["window_type"] == wt]
    st = request.args.get("status")
    if st is not None:
        items = [w for w in items if w["status"] == st]
    return _paginate(items, serializers.coverage_window)


@bp.route("/coverage-windows/<wid>", methods=["GET"])
def get_window(wid):
    require_roles(ALL_ROLES)
    w = store["coverage_windows"].get(wid)
    if w is None:
        raise ApiError(ERR_NOT_FOUND, "CoverageWindow not found", 404)
    return success_object(serializers.coverage_window(w))


@bp.route("/coverage-windows/<wid>/enroll", methods=["POST"])
def enroll_window(wid):
    role, uid = require_roles(["Hospitalist"])
    w = store["coverage_windows"].get(wid)
    if w is None:
        raise ApiError(ERR_NOT_FOUND, "CoverageWindow not found", 404)

    # state tier: LOCKED/CLOSED rejected
    if w["status"] in ("LOCKED", "CLOSED"):
        raise ApiError(ERR_COVERAGE_WINDOW_NOT_OPEN, "window is not open for enrollment", 409)

    # temporal: caller's own overlapping shift conflicts
    for s in store["shifts"].values():
        if s["hospitalist_id"] == uid and s["state"] != "CLOSED":
            if intervals_overlap(w["start_at"], w["end_at"], s["start_at"], s["end_at"]):
                raise ApiError(ERR_ENROLL_SHIFT_CONFLICT, "caller owns a shift overlapping the window", 409)

    # cross-entity: already enrolled
    if uid in w["enrolled_hospitalist_ids"]:
        raise ApiError(ERR_ALREADY_ENROLLED, "caller is already enrolled", 409)

    # capacity: FULL rejects
    if w["status"] == "FULL" or w["enrolled_count"] >= w["capacity"]:
        raise ApiError(ERR_COVERAGE_WINDOW_FULL, "coverage window is at capacity", 422)

    w["enrolled_hospitalist_ids"].append(uid)
    w["enrolled_count"] = len(w["enrolled_hospitalist_ids"])
    if w["enrolled_count"] == w["capacity"]:
        w["status"] = "FULL"
    touch(w)
    return success_object(serializers.coverage_window(w))


@bp.route("/coverage-windows/<wid>/withdraw", methods=["POST"])
def withdraw_window(wid):
    role, uid = require_roles(["Hospitalist"])
    w = store["coverage_windows"].get(wid)
    if w is None:
        raise ApiError(ERR_NOT_FOUND, "CoverageWindow not found", 404)
    if w["status"] in ("LOCKED", "CLOSED"):
        raise ApiError(ERR_COVERAGE_WINDOW_NOT_OPEN, "window is not open for withdrawal", 409)
    if uid in w["enrolled_hospitalist_ids"]:
        w["enrolled_hospitalist_ids"].remove(uid)
        w["enrolled_count"] = len(w["enrolled_hospitalist_ids"])
        if w["status"] == "FULL":
            w["status"] = "OPEN"
        touch(w)
    return success_object(serializers.coverage_window(w))
