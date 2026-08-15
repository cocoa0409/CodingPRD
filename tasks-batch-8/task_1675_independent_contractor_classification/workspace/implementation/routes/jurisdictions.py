"""Jurisdictions and logical clock endpoints."""

from flask import Blueprint, request
from db import store, new_id, parse_iso
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_auth, ALL_ROLES
from response import success, paginate
from services.core import stamp_new

bp = Blueprint("jurisdictions", __name__)

TEST_TYPES = {"ABC_TEST", "COMMON_LAW_WEIGHTED", "ECONOMIC_REALITY"}


@bp.route("/api/jurisdictions", methods=["POST"])
def create_jurisdiction():
    require_auth(["PlatformAdmin"])
    body = request.get_json(silent=True) or {}
    code = body.get("code")
    test_type = body.get("test_type")
    threshold = body.get("employee_score_threshold", 0.60)
    state_thresh = body.get("state_filing_threshold_cents")
    max_exc = body.get("max_active_exceptions")
    min_ins = body.get("min_insurance_cents")
    description = body.get("description", "")

    if not code or not isinstance(code, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "code is required")
    if test_type not in TEST_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid test_type")
    try:
        threshold_f = float(threshold)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid employee_score_threshold")
    if not (0 < threshold_f <= 1):
        raise ApiError(ERR_INVALID_REQUEST, 400, "employee_score_threshold out of range")
    for v, name in ((state_thresh, "state_filing_threshold_cents"),
                    (max_exc, "max_active_exceptions"),
                    (min_ins, "min_insurance_cents")):
        if v is None or not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be an integer >= 0")
    if not isinstance(description, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "description must be a string")

    # uniqueness of code
    for j in store.jurisdictions.values():
        if j["code"] == code:
            raise ApiError(ERR_INVALID_REQUEST, 400, "code must be unique")

    jur = {
        "id": new_id(),
        "code": code,
        "test_type": test_type,
        "employee_score_threshold": threshold_f,
        "state_filing_threshold_cents": state_thresh,
        "max_active_exceptions": max_exc,
        "min_insurance_cents": min_ins,
        "description": description,
    }
    stamp_new(jur)
    store.jurisdictions[jur["id"]] = jur
    return success(jur, status=201)


@bp.route("/api/jurisdictions", methods=["GET"])
def list_jurisdictions():
    require_auth(ALL_ROLES)
    items = list(store.jurisdictions.values())
    test_type = request.args.get("test_type")
    if test_type:
        items = [j for j in items if j["test_type"] == test_type]
    items.sort(key=lambda j: j["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(["PlatformAdmin"])
    body = request.get_json(silent=True) or {}
    to = body.get("to_iso8601")
    dt = parse_iso(to)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be a valid ISO8601 instant")
    store.clock = dt
    return success({}, status=200)
