"""Route and RouteStop endpoints with two interval geometries (PRD §3.7)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_role, require_role, parse_pagination, paginate
from response import object_response, array_response
from services.common import make_record, public_view, sort_by_created
from services import validate

bp = Blueprint("routes_stops", __name__)

SEQUENCE_BUFFER_MIN = 15


def _ensure_route(route_id):
    r = db.routes.get(route_id)
    if r is None:
        raise errors.not_found("Route not found.")
    return r


# ---- Routes ----
@bp.route("/routes", methods=["POST"])
def create_route():
    role = get_role()
    require_role(role, {"ProgramAdmin"})
    body = validate.get_body()

    route_code = validate.require_str(body, "route_code")
    service_day = validate.require_enum(body, "service_day", validate.SERVICE_DAYS)
    driver_user_id = validate.require_str(body, "driver_user_id")

    for r in db.routes.values():
        if r["route_code"] == route_code:
            raise errors.duplicate_key("route_code already in use.")

    r = make_record("routes", {
        "route_code": route_code,
        "service_day": service_day,
        "driver_user_id": driver_user_id,
    })
    return object_response(public_view(r), 201)


@bp.route("/routes/<route_id>", methods=["GET"])
def get_route(route_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "RouteDriver"})
    r = _ensure_route(route_id)
    return object_response(public_view(r), 200)


# ---- Route Stops ----
@bp.route("/routes/<route_id>/stops", methods=["POST"])
def add_stop(route_id):
    role = get_role()
    require_role(role, {"ProgramAdmin"})
    _ensure_route(route_id)
    body = validate.get_body()

    account_id = validate.require_str(body, "account_id")
    stop_sequence = validate.require_int(body, "stop_sequence", minimum=1)
    window_start = validate.require_int(body, "window_start_min")
    window_end = validate.require_int(body, "window_end_min")

    # priority 4: FK integrity on account_id.
    if account_id not in db.accounts:
        raise errors.fk_integrity("account_id does not resolve.")

    # Window well-formedness (0 <= start < end <= 1440) -> ERR_INVALID_REQUEST.
    if not (0 <= window_start < window_end <= 1440):
        raise errors.invalid_request("Window must satisfy 0 <= start < end <= 1440.")

    existing = [s for s in db.route_stops.values() if s["route_id"] == route_id]

    # priority 9: window overlap (half-open, positive-length intersection).
    for s in existing:
        if window_start < s["window_end_min"] and s["window_start_min"] < window_end:
            raise errors.stop_window_overlap()

    # priority 11: stop_sequence uniqueness + 15-min travel buffer between
    # consecutive sequence-ordered stops.
    for s in existing:
        if s["stop_sequence"] == stop_sequence:
            raise errors.stop_sequence_conflict("stop_sequence duplicated.")

    # Determine immediate predecessor and successor by sequence order and
    # enforce the buffer in both directions.
    prior = None  # largest sequence < new
    nxt = None    # smallest sequence > new
    for s in existing:
        if s["stop_sequence"] < stop_sequence:
            if prior is None or s["stop_sequence"] > prior["stop_sequence"]:
                prior = s
        elif s["stop_sequence"] > stop_sequence:
            if nxt is None or s["stop_sequence"] < nxt["stop_sequence"]:
                nxt = s

    if prior is not None and window_start < prior["window_end_min"] + SEQUENCE_BUFFER_MIN:
        raise errors.stop_sequence_conflict("Travel buffer to prior stop violated.")
    if nxt is not None and nxt["window_start_min"] < window_end + SEQUENCE_BUFFER_MIN:
        raise errors.stop_sequence_conflict("Travel buffer to next stop violated.")

    stop = make_record("route_stops", {
        "route_id": route_id,
        "account_id": account_id,
        "stop_sequence": stop_sequence,
        "window_start_min": window_start,
        "window_end_min": window_end,
    })
    return object_response(public_view(stop), 201)


@bp.route("/routes/<route_id>/stops", methods=["GET"])
def list_stops(route_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "RouteDriver"})
    _ensure_route(route_id)
    limit, offset = parse_pagination()
    rows = [s for s in db.route_stops.values() if s["route_id"] == route_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([public_view(s) for s in page], limit, offset, total)


@bp.route("/route-stops/<stop_id>", methods=["GET"])
def get_stop(stop_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "RouteDriver"})
    s = db.route_stops.get(stop_id)
    if s is None:
        raise errors.not_found("Route stop not found.")
    return object_response(public_view(s), 200)


@bp.route("/route-stops", methods=["GET"])
def list_route_stops():
    role = get_role()
    require_role(role, {"ProgramAdmin", "RouteDriver", "AccountManager"})
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    rows = list(db.route_stops.values())
    if account_id is not None:
        rows = [s for s in rows if s["account_id"] == account_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([public_view(s) for s in page], limit, offset, total)
