"""District outcome report (PRD §3.9) and the test-driving clock endpoint."""

from flask import Blueprint, request

from db import DB
from errors import err, ERR_WINDOW_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import require_role, ALL_ROLES, get_json_body, require_fields
from response import success_object
from services import resolve_district, compute_outcome_report
from clock import set_clock, now_iso_ms, parse_iso

bp = Blueprint("reports", __name__)


@bp.get("/districts/<districtId>/outcome-report")
def outcome_report(districtId):
    require_role(*ALL_ROLES)
    resolve_district(districtId)
    window_id = request.args.get("window_id")
    if window_id is None:
        raise err(ERR_INVALID_REQUEST, 400, "Missing required query parameter: window_id")
    window = DB.screening_windows.get(window_id)
    if window is None:
        raise err(ERR_WINDOW_NOT_FOUND, 404, "window_id does not exist")
    school = DB.schools.get(window["school_id"])
    if school is None or school["district_id"] != districtId:
        raise err(ERR_WINDOW_NOT_FOUND, 404, "window_id does not exist (within district)")
    return success_object(compute_outcome_report(districtId, window))


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_role("PlatformAdmin")
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    to_iso = body["to_iso8601"]
    if not isinstance(to_iso, str):
        raise err(ERR_INVALID_REQUEST, 400, "to_iso8601 must be a string")
    try:
        parse_iso(to_iso)
    except Exception:
        raise err(ERR_INVALID_REQUEST, 400, "to_iso8601 must be a valid ISO 8601 timestamp")
    set_clock(to_iso)
    return success_object({"current_utc": now_iso_ms()})
