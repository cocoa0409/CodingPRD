"""Route endpoints: creation with stop auto-generation and assignment lifecycle."""
from flask import Blueprint, request

from db import db, stamp_new, touch
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION, ERR_ROUTE_OUTSIDE_READ_WINDOW,
    ERR_TECHNICIAN_WINDOW_CONFLICT, ERR_TECHNICIAN_NOT_ACTIVE,
    ERR_STALE_VERSION, ERR_ROUTE_NOT_REASSIGNABLE, ERR_NOT_ASSIGNED_TECHNICIAN,
    ERR_ROUTE_HAS_PENDING_STOPS, ERR_INVALID_REQUEST,
)
from middleware import require_roles, ALL_ROLES, body, req_str, req_enum, req_date, opt_bool
from response import success, list_response, created_sorted
from serializers import ser_route, ser_stop, route_stops
from services.cascades import technician_window_conflict
from util import parse_date, rate_2dp

bp = Blueprint("routes", __name__)

COVERED_STATES = ("VALIDATED", "ESTIMATED", "SUPERSEDED")


def get_route(rid):
    r = db.routes.get(rid)
    if not r:
        raise ApiError(ERR_NOT_FOUND, "Route not found", 404)
    return r


def _get_tech_ref(tid):
    t = db.technicians.get(tid)
    if not t:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND, "FieldTechnician not found", 404)
    return t


def _check_assignable(route, technician):
    """Ladder: window conflict (17) precedes technician-active (23)."""
    if technician_window_conflict(technician["id"], route["scheduled_date"], route["route_shift"]):
        raise ApiError(
            ERR_TECHNICIAN_WINDOW_CONFLICT,
            "Technician has an overlapping commitment on that date/shift",
            409,
        )
    if technician["technician_status"] != "ACTIVE":
        raise ApiError(ERR_TECHNICIAN_NOT_ACTIVE, "Technician is not ACTIVE", 409)


@bp.route("/routes", methods=["POST"])
def create():
    require_roles("Dispatcher")
    data = body()
    period_id = req_str(data, "billing_cycle_period_id")
    scheduled_date = req_date(data, "scheduled_date")
    route_shift = req_enum(data, "route_shift", ("AM", "PM", "FULL"))
    two_person_crew = opt_bool(data, "two_person_crew", default=False)
    period = db.periods.get(period_id)
    if not period:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND, "BillingCyclePeriod not found", 404)
    if period["period_status"] not in ("SCHEDULED", "WINDOW_OPEN"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Period must be SCHEDULED or WINDOW_OPEN for route creation",
            409,
        )
    if not (
        parse_date(period["read_window_open_date"])
        <= parse_date(scheduled_date)
        <= parse_date(period["read_window_close_date"])
    ):
        raise ApiError(
            ERR_ROUTE_OUTSIDE_READ_WINDOW,
            "scheduled_date is outside the period read window",
            422,
        )
    rec = {
        "billing_cycle_period_id": period_id,
        "scheduled_date": scheduled_date,
        "route_shift": route_shift,
        "two_person_crew": two_person_crew,
        "technician_id": None,
        "route_status": "DRAFT",
        "read_rate_percent": None,
        "net_read_rate_percent": None,
    }
    stamp_new(rec)
    db.routes[rec["id"]] = rec
    # Auto-generate stops: eligible accounts of the period's cycle, ordered by
    # account created_at ascending (1-based sequence numbers).
    eligible = []
    for a in db.accounts.values():
        if a["billing_cycle_code"] != period["cycle_code"]:
            continue
        if a["account_status"] != "ACTIVE":
            continue
        meter = next(
            (m for m in db.meters.values()
             if m["installed_service_account_id"] == a["id"]
             and m["meter_status"] == "IN_SERVICE"),
            None,
        )
        if meter is None:
            continue
        if meter["meter_type"] == "HANDHELD" or meter["endpoint_comms_status"] != "COMMUNICATING":
            eligible.append(a)
    eligible.sort(key=lambda a: (a["created_at"], a["_seq"]))
    for idx, account in enumerate(eligible, start=1):
        stop = {
            "route_id": rec["id"],
            "service_account_id": account["id"],
            "billing_cycle_period_id": period_id,
            "sequence_number": idx,
            "stop_status": "PENDING",
            "no_read_reason": None,
            "hazard_flag_id": None,
            "current_read_id": None,
        }
        stamp_new(stop)
        db.stops[stop["id"]] = stop
    return success(ser_route(rec), code=201)


@bp.route("/routes", methods=["GET"])
def list_all():
    require_roles(*ALL_ROLES)
    items = list(db.routes.values())
    for param in ("billing_cycle_period_id", "technician_id", "route_status"):
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if r[param] == val]
    return list_response([ser_route(r) for r in created_sorted(items)])


@bp.route("/routes/<rid>", methods=["GET"])
def get_one(rid):
    require_roles(*ALL_ROLES)
    return success(ser_route(get_route(rid)), code=200)


@bp.route("/routes/<rid>/stops", methods=["GET"])
def list_stops(rid):
    require_roles(*ALL_ROLES)
    route = get_route(rid)
    stops = sorted(route_stops(route["id"]), key=lambda s: s["sequence_number"])
    return list_response([ser_stop(s) for s in stops])


@bp.route("/routes/<rid>/assign", methods=["POST"])
def assign(rid):
    require_roles("Dispatcher")
    data = body()
    technician_id = req_str(data, "technician_id")
    route = get_route(rid)
    tech = _get_tech_ref(technician_id)
    if route["route_status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Route is not DRAFT", 409)
    _check_assignable(route, tech)
    route["technician_id"] = technician_id
    route["route_status"] = "ASSIGNED"
    touch(route)
    return success(ser_route(route), code=200)


@bp.route("/routes/<rid>/reassign", methods=["POST"])
def reassign(rid):
    require_roles("Dispatcher")
    data = body()
    technician_id = req_str(data, "technician_id")
    expected = data.get("expected_route_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_route_version is required", 400)
    route = get_route(rid)
    tech = _get_tech_ref(technician_id)
    if expected != route["version"]:
        raise ApiError(ERR_STALE_VERSION, "Route version does not match", 412)
    if route["route_status"] != "ASSIGNED":
        raise ApiError(ERR_ROUTE_NOT_REASSIGNABLE, "Route is not ASSIGNED", 409)
    _check_assignable(route, tech)
    route["technician_id"] = technician_id
    touch(route)
    return success(ser_route(route), code=200)


@bp.route("/routes/<rid>/unassign", methods=["POST"])
def unassign(rid):
    require_roles("Dispatcher")
    route = get_route(rid)
    if route["route_status"] != "ASSIGNED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Route is not ASSIGNED", 409)
    route["technician_id"] = None
    route["route_status"] = "DRAFT"
    touch(route)
    return success(ser_route(route), code=200)


def _ownership(route, uid):
    if route["technician_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_TECHNICIAN,
            "Caller is not the assigned technician on this route",
            403,
        )


@bp.route("/routes/<rid>/start", methods=["POST"])
def start(rid):
    uid, _role = require_roles("FieldTechnician")
    route = get_route(rid)
    _ownership(route, uid)
    if route["route_status"] != "ASSIGNED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Route is not ASSIGNED", 409)
    route["route_status"] = "IN_PROGRESS"
    touch(route)
    return success(ser_route(route), code=200)


@bp.route("/routes/<rid>/complete", methods=["POST"])
def complete(rid):
    uid, _role = require_roles("FieldTechnician")
    route = get_route(rid)
    _ownership(route, uid)
    if route["route_status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Route is not IN_PROGRESS", 409)
    if any(s["stop_status"] == "PENDING" for s in route_stops(rid)):
        raise ApiError(ERR_ROUTE_HAS_PENDING_STOPS, "Route still has PENDING stops", 409)
    route["route_status"] = "COMPLETED"
    touch(route)
    return success(ser_route(route), code=200)


@bp.route("/routes/<rid>/reconcile", methods=["POST"])
def reconcile(rid):
    require_roles("Dispatcher")
    route = get_route(rid)
    if route["route_status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Route is not COMPLETED", 409)
    stops = route_stops(rid)
    covered = sum(1 for s in stops if s["stop_status"] in COVERED_STATES)
    gross_denom = sum(1 for s in stops if s["stop_status"] != "CANCELLED")
    skipped = sum(1 for s in stops if s["stop_status"] == "SKIPPED_HAZARD")
    route["read_rate_percent"] = rate_2dp(covered, gross_denom)
    route["net_read_rate_percent"] = rate_2dp(covered, gross_denom - skipped)
    route["route_status"] = "RECONCILED"
    touch(route)
    return success(ser_route(route), code=200)


@bp.route("/routes/<rid>/cancel", methods=["POST"])
def cancel(rid):
    require_roles("Dispatcher")
    route = get_route(rid)
    if route["route_status"] not in ("DRAFT", "ASSIGNED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Route can be cancelled only from DRAFT or ASSIGNED",
            409,
        )
    route["route_status"] = "CANCELLED"
    touch(route)
    for stop in route_stops(rid):
        if stop["stop_status"] == "PENDING":
            stop["stop_status"] = "CANCELLED"
            touch(stop)
    return success(ser_route(route), code=200)
