from flask import Blueprint, request

from auth import require, ALL_ROLES
from domain import (cases_unrouted, dump_shipment, get_run, get_shipment,
                    freshness_remaining, margin_per_case)
from errors import ApiError
from store import STORE, new_entity, touch, sort_key
from util import body, ok, paginate, req_enum, req_int, opt_int, opt_bool, iso

bp = Blueprint("shipments", __name__)


@bp.post("/snack-mfg/shipments")
def create_shipment():
    require(["RoutePlanner"])
    data = body()
    # tier 3: body FK
    run_id = data.get("run_id")
    run = get_run(STORE, run_id) if isinstance(run_id, str) else None
    if run is None:
        if not isinstance(run_id, str) or run_id == "":
            raise ApiError("ERR_VALIDATION", 400, "missing or invalid field: run_id")
        raise ApiError("ERR_RUN_NOT_FOUND", 404, "run not found")
    # tier 5: shape
    cases = req_int(data, "cases", ge=1)
    requested_route = req_enum(data, "requested_route", {"DSD", "WAREHOUSE", "AUTO"})
    transit_days = opt_int(data, "transit_days", ge=0, default=2)
    # tier 6: source run must be COMPLETED
    if run["execution_status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409, "source run is not COMPLETED")
    # tier 9: reservation availability
    if cases > cases_unrouted(STORE, run):
        raise ApiError("ERR_CASES_UNAVAILABLE", 422, "insufficient cases_unrouted")
    sh = new_entity(STORE)
    sh.update({
        "run_id": run["id"], "cases": cases, "requested_route": requested_route,
        "transit_days": transit_days, "planned_route": None, "status": "DRAFT",
        "freshness_days_at_plan": None, "dispatched_at": None,
    })
    STORE.shipments[sh["id"]] = sh
    return ok(STORE, dump_shipment(sh), status=201)


@bp.get("/snack-mfg/shipments/<sid>")
def get_shipment_ep(sid):
    require(ALL_ROLES)
    sh = get_shipment(STORE, sid)
    return ok(STORE, dump_shipment(sh))


@bp.get("/snack-mfg/shipments")
def list_shipments():
    require(ALL_ROLES)
    items = list(STORE.shipments.values())
    run_id = request.args.get("run_id")
    status = request.args.get("status")
    if run_id is not None:
        items = [s for s in items if s["run_id"] == run_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=sort_key)
    page, meta = paginate([dump_shipment(s) for s in items])
    return ok(STORE, page, response_type="array", pagination=meta)


def _shipment_terminal_guard(sh):
    if sh["status"] in ("DISPATCHED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "shipment is in a terminal state")


def _run_passed_guard(sh):
    run = get_run(STORE, sh["run_id"])
    if run["quality_status"] != "PASSED":
        raise ApiError("ERR_RUN_NOT_PASSED", 409, "source run quality is not PASSED")
    return run


@bp.post("/snack-mfg/shipments/<sid>/plan")
def plan_shipment(sid):
    require(["RoutePlanner"])
    sh = get_shipment(STORE, sid)
    _shipment_terminal_guard(sh)
    if sh["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "shipment is not DRAFT")
    run = _run_passed_guard(sh)
    product = STORE.products.get(run["product_id"])
    remaining = freshness_remaining(product, STORE.clock, run["_completed_dt"])
    transit = sh["transit_days"]
    requested = sh["requested_route"]
    if requested == "DSD":
        if remaining < 4:
            raise ApiError("ERR_ROUTE_INELIGIBLE", 422, "DSD requires at least 4 remaining days")
        route = "DSD"
    elif requested == "WAREHOUSE":
        if remaining - transit <= 10:
            raise ApiError("ERR_ROUTE_INELIGIBLE", 422,
                           "WAREHOUSE requires receipt remaining > 10 days")
        route = "WAREHOUSE"
    else:  # AUTO — warehouse preferred, then DSD
        if remaining - transit > 10:
            route = "WAREHOUSE"
        elif remaining >= 4:
            route = "DSD"
        else:
            raise ApiError("ERR_FRESHNESS_INSUFFICIENT", 422, "no route is freshness-eligible")
    sh["planned_route"] = route
    sh["freshness_days_at_plan"] = remaining
    sh["status"] = "DSD_PLANNED" if route == "DSD" else "WAREHOUSE_PLANNED"
    touch(STORE, sh)
    return ok(STORE, dump_shipment(sh))


@bp.post("/snack-mfg/shipments/<sid>/replan")
def replan_shipment(sid):
    require(["RoutePlanner"])
    sh = get_shipment(STORE, sid)
    _shipment_terminal_guard(sh)
    if sh["status"] not in ("DSD_PLANNED", "WAREHOUSE_PLANNED"):
        raise ApiError("ERR_INVALID_STATE", 409, "shipment is not in a planned state")
    sh["status"] = "DRAFT"
    sh["planned_route"] = None
    sh["freshness_days_at_plan"] = None
    touch(STORE, sh)
    return ok(STORE, dump_shipment(sh))


@bp.post("/snack-mfg/shipments/<sid>/dispatch")
def dispatch_shipment(sid):
    _, role = require(["RoutePlanner", "PlantManager"])
    sh = get_shipment(STORE, sid)
    data = body()
    override = opt_bool(data, "override_margin_floor", default=False)
    _shipment_terminal_guard(sh)
    if sh["status"] not in ("DSD_PLANNED", "WAREHOUSE_PLANNED"):
        raise ApiError("ERR_INVALID_STATE", 409, "shipment is not in a planned state")
    run = _run_passed_guard(sh)
    product = STORE.products.get(run["product_id"])
    # freshness re-check at dispatch
    remaining = freshness_remaining(product, STORE.clock, run["_completed_dt"])
    if sh["status"] == "DSD_PLANNED":
        if remaining < 4:
            raise ApiError("ERR_FRESHNESS_INSUFFICIENT", 422,
                           "freshness below the DSD bar at dispatch")
    else:
        if remaining - sh["transit_days"] <= 10:
            raise ApiError("ERR_FRESHNESS_INSUFFICIENT", 422,
                           "freshness below the warehouse bar at dispatch")
    # fiscal: margin floor (checked last)
    per_case = margin_per_case(run)
    floor = product["min_margin_cents_per_case"]
    holds = per_case is not None and per_case >= floor
    if not holds and not (role == "PlantManager" and override is True):
        raise ApiError("ERR_MARGIN_BELOW_FLOOR", 422, "per-case margin below product floor")
    sh["status"] = "DISPATCHED"
    sh["dispatched_at"] = iso(STORE.clock)
    touch(STORE, sh)
    return ok(STORE, dump_shipment(sh))


@bp.post("/snack-mfg/shipments/<sid>/cancel")
def cancel_shipment(sid):
    require(["RoutePlanner"])
    sh = get_shipment(STORE, sid)
    _shipment_terminal_guard(sh)
    if sh["status"] not in ("DRAFT", "DSD_PLANNED", "WAREHOUSE_PLANNED"):
        raise ApiError("ERR_INVALID_STATE", 409, "shipment cannot be cancelled from this state")
    sh["status"] = "CANCELLED"
    touch(STORE, sh)
    return ok(STORE, dump_shipment(sh))
