"""Clock, Inspector, and MitigationCrew endpoints (PRD §2.9, §3.8)."""

from flask import Blueprint

from db import store, format_iso8601_millis, parse_iso8601
import errors
from errors import ApiError
from middleware import get_user_context, require_role, get_json_body
from response import object_response
from services import validate
from services.domain import _common_create_fields, public, touch, now_clock

bp = Blueprint("admin", __name__)


# --------------------------------------------------------------------------
# Logical clock (PRD §3.8). PlatformAdmin only.
# --------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    raw = body.get("to_iso8601")
    if raw is None:
        validate.bad_request("Missing required field: to_iso8601")
    try:
        dt = parse_iso8601(raw)
    except (ValueError, TypeError):
        validate.bad_request("Field to_iso8601 must be an ISO 8601 UTC datetime.")
    store.clock_current_utc = dt
    data = {
        "id": store.clock_id,
        "created_at": format_iso8601_millis(store.clock_created_at),
        "current_utc": format_iso8601_millis(dt),
    }
    return object_response(data, 200)


# --------------------------------------------------------------------------
# Inspector (PRD §2.9).
# --------------------------------------------------------------------------
@bp.route("/inspectors", methods=["POST"])
def create_inspector():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    full_name = validate.require_string(body, "full_name")
    nrpp = validate.require_string(body, "nrpp_license_id")

    # nrpp_license_id unique among ACTIVE inspectors (priority 14).
    for insp in store.inspectors.values():
        if insp["status"] == "ACTIVE" and insp["nrpp_license_id"] == nrpp:
            raise ApiError(
                errors.ERR_DUPLICATE_IDENTIFIER,
                409,
                "nrpp_license_id already in use by an ACTIVE inspector.",
            )

    entity = _common_create_fields()
    entity.update(
        {
            "full_name": full_name,
            "nrpp_license_id": nrpp,
            "status": "ACTIVE",
        }
    )
    store.inspectors[entity["id"]] = entity
    return object_response(public(entity), 201)


@bp.route("/inspectors/<inspector_id>/suspend", methods=["POST"])
def suspend_inspector(inspector_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    insp = store.inspectors.get(inspector_id)
    if insp is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Inspector not found.")
    insp["status"] = "SUSPENDED"
    touch(insp)
    return object_response(public(insp), 200)


# --------------------------------------------------------------------------
# MitigationCrew (PRD §2.9).
# --------------------------------------------------------------------------
@bp.route("/crews", methods=["POST"])
def create_crew():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    crew_name = validate.require_string(body, "crew_name")
    # max_jobs_per_day default 2, never below 1 (PRD §2.9).
    max_jobs = validate.optional_int(body, "max_jobs_per_day", 2, minimum=1)

    entity = _common_create_fields()
    entity.update(
        {
            "crew_name": crew_name,
            "max_jobs_per_day": max_jobs,
            "status": "ACTIVE",
        }
    )
    store.crews[entity["id"]] = entity
    return object_response(public(entity), 201)


@bp.route("/crews/<crew_id>/suspend", methods=["POST"])
def suspend_crew(crew_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    crew = store.crews.get(crew_id)
    if crew is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Crew not found.")
    crew["status"] = "SUSPENDED"
    touch(crew)
    return object_response(public(crew), 200)
