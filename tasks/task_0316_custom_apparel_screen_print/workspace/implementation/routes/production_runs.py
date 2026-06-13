"""ProductionRun endpoints: schedule, start, complete, abort
(PRD §3.7, §3.8; SCAFFOLD §1.2 ProductionRun state machine)."""
from flask import Blueprint, request

from db import store, new_common_fields, touch
from errors import err
from clock import parse_iso8601
from middleware import endpoint
from response import success, list_response
from serialize import view, view_list
from validation import get_body, require_datetime, require_int, parse_pagination, paginate
from services import scheduling, lifecycle
from services.lookups import (
    get_order, get_run_under_order, get_production_run,
    get_press, get_embroidery_station,
    lines_of_order, get_decoration_method, active_reservations_of_order,
)

bp = Blueprint("production_runs", __name__)


def _order_resource_kind(order):
    """The decoration method resource_kind for the order, taken from its lines."""
    lines = lines_of_order(order["id"])
    if not lines:
        return None
    method = get_decoration_method(lines[0]["decoration_method_id"])
    return method["resource_kind"]


# ---- Schedule a run ----

@bp.route("/orders/<order_id>/production-runs", methods=["POST"])
@endpoint("ShopManager")
def schedule_run(order_id):
    order = get_order(order_id)
    body = get_body()

    # Body well-formedness (priority 4): the production-run body proper is its
    # booking window. PRD §2.10 tier 4 covers body shape; whether the order has
    # lines (and thus a determinable resource_kind) is a consequence of the
    # order's state, not of this request's body, so it must NOT pre-empt the
    # PRD-named state error below.
    window_start = require_datetime(body, "window_start")
    window_end = require_datetime(body, "window_end")
    if window_end <= window_start:
        raise err("ERR_INVALID_REQUEST", "window_end must be after window_start")
    press_id = body.get("press_id")
    station_id = body.get("embroidery_station_id")

    # State (priority 5 / PRD §3.7): order must be CONFIRMED or IN_PRODUCTION,
    # else ERR_ORDER_NOT_CONFIRMED. A non-confirmed order has no lines yet, so the
    # state check must precede resource_kind resolution.
    if order["fulfillment_status"] not in ("CONFIRMED", "IN_PRODUCTION"):
        raise err("ERR_ORDER_NOT_CONFIRMED", "Order is not CONFIRMED or IN_PRODUCTION")

    # Machine-reference must match the order's method resource_kind (PRD §3.7).
    kind = _order_resource_kind(order)
    if kind == "PRESS":
        if not press_id or station_id:
            raise err("ERR_INVALID_REQUEST", "SCREEN_PRINT order requires press_id")
    elif kind == "EMBROIDERY_STATION":
        if not station_id or press_id:
            raise err("ERR_INVALID_REQUEST", "EMBROIDERY order requires embroidery_station_id")
    else:
        raise err("ERR_INVALID_REQUEST", "Order has no lines to determine the machine")

    # Machine availability (priority 11/12).
    if kind == "PRESS":
        press = get_press(press_id)
        scheduling.check_press_window(press, window_start, window_end)
    else:
        station = get_embroidery_station(station_id)
        scheduling.check_station_window(station, window_start, window_end)

    run = new_common_fields()
    run.update({
        "order_id": order_id,
        "press_id": press_id if kind == "PRESS" else None,
        "embroidery_station_id": station_id if kind == "EMBROIDERY_STATION" else None,
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "good_units": None,
        "spoiled_units": None,
        "consumed_units": None,
        "released_units": None,
        "blanks_pulled": None,
        "status": "SCHEDULED",
    })
    store.production_runs[run["id"]] = run

    # First run on a CONFIRMED order advances it to IN_PRODUCTION (PRD §3.7).
    if order["fulfillment_status"] == "CONFIRMED":
        order["fulfillment_status"] = "IN_PRODUCTION"
        touch(order)

    return success(view(run), status=201)


@bp.route("/orders/<order_id>/production-runs", methods=["GET"])
@endpoint("ShopManager", "ArtStaff")
def list_order_runs(order_id):
    get_order(order_id)
    limit, offset = parse_pagination()
    items = [r for r in store.production_runs.values() if r["order_id"] == order_id]
    items = _apply_run_filters(items)
    page, total = paginate(items, limit, offset)
    return list_response(view_list(page), limit, offset, total)


@bp.route("/production-runs/<run_id>", methods=["GET"])
@endpoint("ShopManager", "ArtStaff")
def get_run_route(run_id):
    return success(view(get_production_run(run_id)), status=200)


@bp.route("/production-runs", methods=["GET"])
@endpoint("ShopManager", "ArtStaff")
def list_runs():
    limit, offset = parse_pagination()
    items = list(store.production_runs.values())
    val = request.args.get("order_id")
    if val is not None:
        items = [r for r in items if r["order_id"] == val]
    items = _apply_run_filters(items)
    page, total = paginate(items, limit, offset)
    return list_response(view_list(page), limit, offset, total)


def _apply_run_filters(items):
    press_id = request.args.get("press_id")
    station_id = request.args.get("embroidery_station_id")
    status = request.args.get("status")
    if press_id is not None:
        items = [r for r in items if r.get("press_id") == press_id]
    if station_id is not None:
        items = [r for r in items if r.get("embroidery_station_id") == station_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return items


# ---- Start ----

@bp.route("/orders/<order_id>/production-runs/<run_id>/start", methods=["POST"])
@endpoint("ShopManager")
def start_run(order_id, run_id):
    order = get_order(order_id)
    run = get_run_under_order(order_id, run_id)
    if run["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Run is not SCHEDULED")
    # Cross-entity state (priority 10): order CONFIRMED or IN_PRODUCTION.
    if order["fulfillment_status"] not in ("CONFIRMED", "IN_PRODUCTION"):
        raise err("ERR_ORDER_NOT_CONFIRMED", "Order is not CONFIRMED or IN_PRODUCTION")

    # blanks_pulled = sum of the order's ACTIVE reservations' reserved_qty.
    run["blanks_pulled"] = sum(r["reserved_qty"]
                               for r in active_reservations_of_order(order_id))
    run["status"] = "RUNNING"
    touch(run)

    if order["fulfillment_status"] == "CONFIRMED":
        order["fulfillment_status"] = "IN_PRODUCTION"
        touch(order)

    return success(view(run), status=200)


# ---- Complete ----

@bp.route("/orders/<order_id>/production-runs/<run_id>/complete", methods=["POST"])
@endpoint("ShopManager")
def complete_run(order_id, run_id):
    order = get_order(order_id)
    run = get_run_under_order(order_id, run_id)
    body = get_body()
    good_units = require_int(body, "good_units")
    spoiled_units = require_int(body, "spoiled_units")

    if run["status"] != "RUNNING":
        raise err("ERR_INVALID_STATE", "Run is not RUNNING")

    blanks_pulled = run["blanks_pulled"] or 0
    # ERR_INVALID_GOOD_UNITS (priority 13).
    if good_units < 0 or spoiled_units < 0 or (good_units + spoiled_units) > blanks_pulled:
        raise err("ERR_INVALID_GOOD_UNITS", "Invalid good/spoiled units")

    total_ordered = lifecycle.total_ordered_qty(order_id)
    # ERR_RUN_SHORT (priority 14): no state change if good_units short.
    if good_units < total_ordered:
        raise err("ERR_RUN_SHORT", "good_units below total ordered_qty")

    # Commit completion.
    run["good_units"] = good_units
    run["spoiled_units"] = spoiled_units
    run["consumed_units"] = good_units + spoiled_units
    run["released_units"] = blanks_pulled - run["consumed_units"]
    run["status"] = "COMPLETED"
    touch(run)

    # Cascade Order -> FULFILLED (releases/consumes reservations).
    lifecycle.fulfill_order(order, run)

    return success(view(run), status=200)


# ---- Abort ----

@bp.route("/orders/<order_id>/production-runs/<run_id>/abort", methods=["POST"])
@endpoint("ShopManager")
def abort_run(order_id, run_id):
    get_order(order_id)
    run = get_run_under_order(order_id, run_id)
    if run["status"] not in ("SCHEDULED", "RUNNING"):
        raise err("ERR_INVALID_STATE", "Run is not abortable")
    # Abort frees the booked machine window (status -> ABORTED is terminal).
    run["status"] = "ABORTED"
    touch(run)
    return success(view(run), status=200)
