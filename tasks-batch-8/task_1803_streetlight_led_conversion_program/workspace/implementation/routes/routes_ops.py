"""ConversionRoute and RouteStop endpoints (PRD 3.3)."""
from flask import Blueprint

from db import new_record, store, touch
from domain import (
    STOP_MINUTES, estimate_labor_cents, evaluate_auto_close, post_budget,
    program_of_route, program_of_stop, require_active, route_blocked_count,
    route_stop_count, ser_route, ser_stop, stops_of_route,
)
from errors import raise_error
from middleware import ALL_ROLES, get_caller, locked, require_roles
from response import success_object
from util import CLOCK, parse_date
from validate import get_body, req_bool, req_date, req_enum, req_int, req_str
from routes.common import list_endpoint, require_record

bp = Blueprint("routes_ops", __name__)

PM = ["ProgramManager"]
DIFFICULTIES = ["STANDARD", "HEAVY", "COMPLEX"]
TERMINAL_ROUTE_STATES = ("CLOSED", "CANCELLED")


def _route_sort_key_for_stops(stop):
    route = store.routes.get(stop["route_id"])
    route_seq = route["_seq"] if route else 0
    return (route_seq, stop["sequence_number"])


@bp.route("/streetlights/conversion-routes", methods=["POST"])
@locked
def create_route():
    caller = get_caller()
    body = get_body()
    district_id = req_str(body, "district_id")
    crew_id = req_str(body, "crew_id")
    window_start = req_date(body, "window_start_date")
    window_end = req_date(body, "window_end_date")
    traffic = req_bool(body, "traffic_control_required")
    if parse_date(window_end) < parse_date(window_start):
        raise_error("ERR_INVALID_REQUEST", "window_end_date must not precede window_start_date")
    require_roles(caller, PM)
    district = store.districts.get(district_id)
    if district is None:
        raise_error("ERR_DISTRICT_NOT_FOUND", f"district not found: {district_id}")
    crew = store.crews.get(crew_id)
    if crew is None:
        raise_error("ERR_CREW_NOT_FOUND", f"crew not found: {crew_id}")
    require_active(store.programs.get(district["program_id"]))
    # Stage 11 temporal: same-crew CLOSED-interval window conflict — sharing a
    # single calendar day (including same-day adjacency) is a conflict.
    start, end = parse_date(window_start), parse_date(window_end)
    for other in store.routes.values():
        if other["crew_id"] != crew_id or other["status"] == "CANCELLED":
            continue
        o_start, o_end = parse_date(other["window_start_date"]), parse_date(other["window_end_date"])
        if start <= o_end and o_start <= end:
            raise_error("ERR_ROUTE_WINDOW_OVERLAP",
                        "crew already has a non-CANCELLED route window sharing a calendar day")
    rec = new_record("routes", {
        "district_id": district_id,
        "crew_id": crew_id,
        "window_start_date": window_start,
        "window_end_date": window_end,
        "traffic_control_required": traffic,
        "status": "PLANNED",
    })
    return success_object(ser_route(rec), status=201)


@bp.route("/streetlights/conversion-routes", methods=["GET"])
@locked
def list_routes():
    return list_endpoint("routes", ser_route, ["district_id", "crew_id", "status"])


@bp.route("/streetlights/conversion-routes/<rid>", methods=["GET"])
@locked
def get_route(rid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("routes", rid, "ERR_ROUTE_NOT_FOUND")
    return success_object(ser_route(rec))


@bp.route("/streetlights/conversion-routes/<rid>/stops", methods=["POST"])
@locked
def add_stop(rid):
    caller = get_caller()
    body = get_body()
    pole_id = req_str(body, "pole_id")
    sequence_number = req_int(body, "sequence_number", positive=True)
    difficulty = req_enum(body, "difficulty_class", DIFFICULTIES)
    require_roles(caller, PM)
    route = require_record("routes", rid, "ERR_ROUTE_NOT_FOUND")
    pole = store.poles.get(pole_id)
    if pole is None:
        raise_error("ERR_POLE_NOT_FOUND", f"pole not found: {pole_id}")
    require_active(program_of_route(route))
    # Stage 9: target (route) state, then the EXEMPT pole gate.
    if route["status"] != "PLANNED":
        raise_error("ERR_ROUTE_NOT_PLANNED", "stops may be added only while the route is PLANNED")
    if pole["status"] == "EXEMPT":
        raise_error("ERR_POLE_EXEMPT", "operation not permitted on an EXEMPT pole")
    # Stage 11 temporal: window start must not have passed.
    if parse_date(route["window_start_date"]) < CLOCK.today():
        raise_error("ERR_ROUTE_WINDOW_PAST", "route window_start_date has passed")
    # Stage 12: uniqueness checks. A pole holding a PENDING stop on a
    # non-terminal route is reported as ERR_DUPLICATE_STOP (such a pole is
    # SCHEDULED, so this precedes the AUDIT_CLEARED pole-state gate).
    for s in stops_of_route(route["id"]):
        if s["sequence_number"] == sequence_number:
            raise_error("ERR_DUPLICATE_SEQUENCE", "sequence_number already used on this route")
    for s in store.stops.values():
        if s["pole_id"] == pole["id"] and s["status"] == "PENDING":
            other_route = store.routes.get(s["route_id"])
            if other_route and other_route["status"] not in TERMINAL_ROUTE_STATES:
                raise_error("ERR_DUPLICATE_STOP",
                            "pole already holds a PENDING stop on a non-terminal route")
    # Pole-state gate: only an AUDIT_CLEARED pole may join a route.
    if pole["status"] != "AUDIT_CLEARED":
        raise_error("ERR_POLE_NOT_AUDIT_CLEARED", "stop pole must be AUDIT_CLEARED")
    crew = store.crews[route["crew_id"]]
    existing = [s for s in stops_of_route(route["id"]) if s["status"] != "SKIPPED"]
    m_new = STOP_MINUTES[difficulty]
    workload = sum(s["stop_minutes"] for s in existing) + m_new
    mobilization = 60 if route["traffic_control_required"] else 30
    required_shifts = -(-workload // (480 - mobilization))
    window_days = (parse_date(route["window_end_date"]) - parse_date(route["window_start_date"])).days + 1
    count_incl = len(existing) + 1
    if required_shifts > window_days:
        raise_error("ERR_ROUTE_CAPACITY_EXCEEDED", "required shifts exceed the route window")
    if -(-count_incl // required_shifts) > crew["base_stops_per_shift"]:
        raise_error("ERR_ROUTE_CAPACITY_EXCEEDED", "stops per required shift exceed crew capacity")
    # Stage 13 referential: pole must live in the route's district.
    if pole["district_id"] != route["district_id"]:
        raise_error("ERR_CROSS_DISTRICT_STOP", "stop pole must belong to the route's district")
    rec = new_record("stops", {
        "route_id": route["id"],
        "pole_id": pole["id"],
        "sequence_number": sequence_number,
        "difficulty_class": difficulty,
        "stop_minutes": m_new,
        "status": "PENDING",
    })
    pole["status"] = "SCHEDULED"
    touch(pole)
    return success_object(ser_stop(rec), status=201)


@bp.route("/streetlights/route-stops", methods=["GET"])
@locked
def list_stops():
    return list_endpoint("stops", ser_stop, ["route_id", "pole_id", "status"],
                         sort_key=_route_sort_key_for_stops)


@bp.route("/streetlights/route-stops/<sid>", methods=["GET"])
@locked
def get_stop(sid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("stops", sid, "ERR_STOP_NOT_FOUND")
    return success_object(ser_stop(rec))


@bp.route("/streetlights/route-stops/<sid>/skip", methods=["POST"])
@locked
def skip_stop(sid):
    caller = get_caller()
    require_roles(caller, PM)
    stop = require_record("stops", sid, "ERR_STOP_NOT_FOUND")
    require_active(program_of_stop(stop))
    linked = [o for o in store.work_orders.values() if o["stop_id"] == stop["id"]]
    if stop["status"] != "PENDING" or any(
            o["execution_status"] in ("DISPATCHED", "COMPLETED") for o in linked):
        raise_error("ERR_STOP_NOT_PENDING",
                    "skip requires a PENDING stop with no DISPATCHED/COMPLETED work order")
    for o in linked:
        if o["execution_status"] == "PENDING":
            o["execution_status"] = "CANCELLED"
            touch(o)
    stop["status"] = "SKIPPED"
    touch(stop)
    pole = store.poles.get(stop["pole_id"])
    if pole and pole["status"] == "SCHEDULED":
        pole["status"] = "AUDIT_CLEARED"
        touch(pole)
    route = store.routes.get(stop["route_id"])
    if route:
        evaluate_auto_close(route)
    return success_object(ser_stop(stop))


@bp.route("/streetlights/conversion-routes/<rid>/release", methods=["POST"])
@locked
def release_route(rid):
    caller = get_caller()
    require_roles(caller, PM)
    route = require_record("routes", rid, "ERR_ROUTE_NOT_FOUND")
    require_active(program_of_route(route))
    if route["status"] != "PLANNED":
        raise_error("ERR_ROUTE_NOT_PLANNED", "release requires a PLANNED route")
    if route_stop_count(route) < 1:
        raise_error("ERR_EMPTY_ROUTE", "route must contain at least one counted stop")
    crew = store.crews[route["crew_id"]]
    stops = sorted((s for s in stops_of_route(route["id"]) if s["status"] != "SKIPPED"),
                   key=lambda s: s["sequence_number"])
    for stop in stops:
        new_record("work_orders", {
            "route_id": route["id"],
            "stop_id": stop["id"],
            "pole_id": stop["pole_id"],
            "crew_id": route["crew_id"],
            "ticket_id": None,
            "is_replacement": False,
            "stop_minutes": stop["stop_minutes"],
            "new_fixture_wattage": None,
            "new_cct_kelvin": None,
            "shielding": None,
            "estimated_labor_cost_cents": estimate_labor_cents(crew, stop["stop_minutes"]),
            "est_reconciled": False,
            "cumulative_week_minutes_before": None,
            "overtime_minutes": None,
            "labor_cost_cents": None,
            "performed_by_user_id": None,
            "qc_by_user_id": None,
            "completed_at": None,
            "_completed_dt": None,
            "execution_status": "PENDING",
            "qc_status": "NONE",
        })
    route["status"] = "RELEASED"
    touch(route)
    return success_object(ser_route(route))


@bp.route("/streetlights/conversion-routes/<rid>/suspend", methods=["POST"])
@locked
def suspend_route(rid):
    caller = get_caller()
    require_roles(caller, PM)
    route = require_record("routes", rid, "ERR_ROUTE_NOT_FOUND")
    require_active(program_of_route(route))
    if route["status"] != "IN_PROGRESS":
        raise_error("ERR_ROUTE_NOT_SUSPENDED", "manual suspend requires an IN_PROGRESS route")
    route["status"] = "SUSPENDED"
    touch(route)
    return success_object(ser_route(route))


@bp.route("/streetlights/conversion-routes/<rid>/resume", methods=["POST"])
@locked
def resume_route(rid):
    caller = get_caller()
    require_roles(caller, PM)
    route = require_record("routes", rid, "ERR_ROUTE_NOT_FOUND")
    require_active(program_of_route(route))
    if route["status"] != "SUSPENDED":
        raise_error("ERR_ROUTE_NOT_SUSPENDED", "resume requires a SUSPENDED route")
    sc = route_stop_count(route)
    bc = route_blocked_count(route)
    if bc * 2 >= sc:
        raise_error("ERR_ROUTE_STILL_BLOCKED", "blocked stop fraction must be under one half")
    route["status"] = "IN_PROGRESS"
    touch(route)
    return success_object(ser_route(route))


@bp.route("/streetlights/conversion-routes/<rid>/cancel", methods=["POST"])
@locked
def cancel_route(rid):
    caller = get_caller()
    require_roles(caller, PM)
    route = require_record("routes", rid, "ERR_ROUTE_NOT_FOUND")
    program = program_of_route(route)
    require_active(program)
    if route["status"] in TERMINAL_ROUTE_STATES:
        raise_error("ERR_ROUTE_TERMINAL", "route is already terminal")
    origin = route["status"]
    # Cascade: every PENDING/BLOCKED stop -> SKIPPED; SCHEDULED poles revert.
    for stop in stops_of_route(route["id"]):
        if stop["status"] in ("PENDING", "BLOCKED"):
            stop["status"] = "SKIPPED"
            touch(stop)
            pole = store.poles.get(stop["pole_id"])
            if pole and pole["status"] == "SCHEDULED":
                pole["status"] = "AUDIT_CLEARED"
                touch(pole)
    if origin != "PLANNED":
        # Non-terminal work orders cancel; DISPATCHED orders refund the
        # outstanding estimate (PRD 2.5); PENDING/REWORK_PENDING post nothing.
        for o in [o for o in store.work_orders.values() if o["route_id"] == route["id"]]:
            if o["execution_status"] in ("PENDING", "DISPATCHED", "REWORK_PENDING"):
                if o["execution_status"] == "DISPATCHED" and not o["est_reconciled"]:
                    post_budget(program, o["estimated_labor_cost_cents"])
                o["execution_status"] = "CANCELLED"
                touch(o)
    route["status"] = "CANCELLED"
    touch(route)
    return success_object(ser_route(route))
