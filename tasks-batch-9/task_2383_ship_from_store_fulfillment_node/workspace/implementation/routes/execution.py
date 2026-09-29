"""In-store execution: accept, reject, pick, pack, ship and care cancellation."""
from flask import Blueprint

from constants import (
    API_PREFIX, ASSIGNMENT_STATUSES, CARE_CANCEL_REASONS, LABOR_WINDOW_UTILIZATION_CAP,
    PACKAGE_RANK, PACKAGE_TYPES, REJECT_REASONS, ROLE_ASSOCIATE, ROLE_CARE,
    ROLE_CARRIER, ROLE_PLANNER,
)
import clock
from db import all_of, db
from errors import ApiError
from middleware import (
    authenticate, body, get_bool, get_enum, get_int, get_list, get_str,
    pagination_args, query_enum, query_int, query_str,
)
from routes.common import apply_filter, fetch, finish, listing, require_scope, show
from services import notifications
from services.assignments import billable_weight, final_cost, release_assignment
from services.derive import (
    assignment_lines_of, inventory_for, open_window, packaging_for, recompute_all,
)
from services.routing import create_run, execute_run
from util import D, floor_int, minute_of_day, minutes_between_floor, n2

bp = Blueprint("execution", __name__)

ANY_ROLE = (ROLE_PLANNER, ROLE_ASSOCIATE, ROLE_CARRIER, ROLE_CARE)


def _store_of(assignment):
    return db.stores[assignment["store_id"]]


def _order_of(assignment):
    return db.orders[assignment["order_id"]]


def _require_cutoff(store):
    if minute_of_day(clock.now()) > store["cutoff_utc_minutes"]:
        raise ApiError("ERR_STORE_CUTOFF_PASSED")


def _require_active_node(store):
    if store["node_status"] not in ("ELIGIBLE", "PROBATION"):
        raise ApiError("ERR_STORE_NODE_DEACTIVATED")


def _line_units(assignment, use_picked):
    pairs = []
    for al in assignment_lines_of(assignment["id"]):
        units = al["units_picked"] if use_picked else al["units_assigned"]
        pairs.append((db.order_lines[al["order_line_id"]], units))
    return pairs


def _reroute(order, assignment, exclude_store_id):
    run = create_run(order, "COMMIT", "SYSTEM_REROUTE", [exclude_store_id])
    outcome = execute_run(run, order,
                          base_generation=assignment["reroute_generation"])
    recompute_all()
    return outcome


# ------------------------------------------------------------------ reads

@bp.route(API_PREFIX + "/assignments", methods=["GET"])
def list_assignments():
    authenticate(*ANY_ROLE)
    limit, offset = pagination_args()
    rows = all_of("assignments")
    rows = apply_filter(rows, "order_id", query_str("order_id"))
    rows = apply_filter(rows, "store_id", query_str("store_id"))
    rows = apply_filter(rows, "routing_run_id", query_str("routing_run_id"))
    rows = apply_filter(rows, "carrier_pickup_id", query_str("carrier_pickup_id"))
    rows = apply_filter(rows, "superseded_by_routing_run_id",
                        query_str("superseded_by_routing_run_id"))
    rows = apply_filter(rows, "status", query_enum("status", ASSIGNMENT_STATUSES))
    rows = apply_filter(rows, "epoch", query_int("epoch"))
    return listing(rows, limit, offset)


@bp.route(API_PREFIX + "/assignments/<assignment_id>", methods=["GET"])
def read_assignment(assignment_id):
    authenticate(*ANY_ROLE)
    return show(fetch("assignments", assignment_id))


@bp.route(API_PREFIX + "/assignment-lines", methods=["GET"])
def list_assignment_lines():
    authenticate(*ANY_ROLE)
    limit, offset = pagination_args()
    rows = all_of("assignment_lines")
    rows = apply_filter(rows, "assignment_id", query_str("assignment_id"))
    rows = apply_filter(rows, "order_line_id", query_str("order_line_id"))
    return listing(rows, limit, offset)


@bp.route(API_PREFIX + "/assignment-lines/<assignment_line_id>", methods=["GET"])
def read_assignment_line(assignment_line_id):
    authenticate(*ANY_ROLE)
    return show(fetch("assignment_lines", assignment_line_id))


# ----------------------------------------------------------------- accept

@bp.route(API_PREFIX + "/assignments/<assignment_id>/accept", methods=["POST"])
def accept_assignment(assignment_id):
    actor, role = authenticate(ROLE_ASSOCIATE)
    assignment = fetch("assignments", assignment_id)
    require_scope(actor, role, assignment["store_id"])
    if assignment["status"] != "ASSIGNED":
        raise ApiError("ERR_ASSIGNMENT_STATE_INVALID")
    order = _order_of(assignment)
    if order["fulfillment_status"] == "CANCELLED":
        raise ApiError("ERR_ORDER_NOT_ROUTABLE")
    store = _store_of(assignment)
    _require_active_node(store)
    if open_window(store["id"]) is None:
        raise ApiError("ERR_NO_OPEN_WINDOW")
    _require_cutoff(store)

    now = clock.now()
    if now >= assignment["pick_deadline_utc"]:
        raise ApiError("ERR_PICK_DEADLINE_PASSED")

    # calculations.concurrent_pick_labor_load
    load = D(assignment["labor_minutes_reserved"])
    for other in db.assignments.values():
        if other["id"] == assignment["id"] or other["store_id"] != store["id"]:
            continue
        if other["status"] not in ("ACCEPTED", "PICKED", "SHORT_PICKED"):
            continue
        if other["accepted_at"] is None:
            continue
        if (other["accepted_at"] < assignment["pick_deadline_utc"]
                and now < other["pick_deadline_utc"]):
            load += D(other["labor_minutes_reserved"])
    cap = floor_int(D(store["staffed_labor_minutes"])
                    * D(LABOR_WINDOW_UTILIZATION_CAP))
    if load > D(cap):
        raise ApiError("ERR_LABOR_WINDOW_OVERSUBSCRIBED")

    assignment["status"] = "ACCEPTED"
    assignment["accepted_at"] = now
    return finish(assignment, 200, explicit=[assignment])


# ----------------------------------------------------------------- reject

@bp.route(API_PREFIX + "/assignments/<assignment_id>/reject", methods=["POST"])
def reject_assignment(assignment_id):
    actor, role = authenticate(ROLE_ASSOCIATE)
    payload = body()
    reason = get_enum(payload, "reject_reason_code", REJECT_REASONS)

    assignment = fetch("assignments", assignment_id)
    require_scope(actor, role, assignment["store_id"])
    if assignment["status"] not in ("ASSIGNED", "ACCEPTED"):
        raise ApiError("ERR_ASSIGNMENT_STATE_INVALID")

    order = _order_of(assignment)
    released = release_assignment(assignment, "REJECTED", reason)
    recompute_all()

    outcome = _reroute(order, assignment, assignment["store_id"])
    notification_type = notifications.choose_type(
        "reject",
        dc_fallback_raised=outcome["dc_fallback_units"] > 0,
        replacements_created=len(outcome["created"]) > 0)
    notifications.emit(order, assignment, notification_type, released)
    return finish(assignment, 200, explicit=[assignment])


# ------------------------------------------------------------------- pick

@bp.route(API_PREFIX + "/assignments/<assignment_id>/pick", methods=["POST"])
def pick_assignment(assignment_id):
    actor, role = authenticate(ROLE_ASSOCIATE)
    payload = body()
    picked_units = get_int(payload, "picked_units", minimum=0)
    entries = get_list(payload, "line_picks")
    parsed = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST",
                           "line_picks[%d] must be an object." % index)
        line_id = get_str(entry, "assignment_line_id")
        units = get_int(entry, "units_picked", minimum=0)
        parsed.append((line_id, units))

    assignment = fetch("assignments", assignment_id)
    rows = [fetch("assignment_lines", line_id) for line_id, _units in parsed]
    require_scope(actor, role, assignment["store_id"])
    if assignment["status"] != "ACCEPTED":
        raise ApiError("ERR_ASSIGNMENT_STATE_INVALID")
    store = _store_of(assignment)
    _require_cutoff(store)

    seen = set()
    total = 0
    for (line_id, units), row in zip(parsed, rows):
        if line_id in seen:
            raise ApiError("ERR_PICK_UNITS_INVALID")
        seen.add(line_id)
        if units > row["units_assigned"]:
            raise ApiError("ERR_PICK_UNITS_INVALID")
        total += units
    if picked_units > assignment["assigned_units"] or total != picked_units:
        raise ApiError("ERR_PICK_UNITS_INVALID")
    if picked_units < 1:
        raise ApiError("ERR_ZERO_PICK_NOT_ALLOWED")
    for row in rows:
        if row["assignment_id"] != assignment["id"]:
            raise ApiError("ERR_ASSIGNMENT_LINE_MISMATCH")

    picks = {line_id: units for line_id, units in parsed}
    now = clock.now()
    short = picked_units < assignment["assigned_units"]
    for al in assignment_lines_of(assignment["id"]):
        al["units_picked"] = picks.get(al["id"], 0)
        if short:
            al["units_cancelled"] = al["units_assigned"] - al["units_picked"]
    assignment["picked_units"] = picked_units
    assignment["picked_at"] = now
    assignment["shortfall_units"] = (assignment["assigned_units"] - picked_units
                                     if short else 0)
    assignment["status"] = "SHORT_PICKED" if short else "PICKED"
    assignment["billable_weight_grams"] = billable_weight(
        _line_units(assignment, True))
    recompute_all()

    if short:
        order = _order_of(assignment)
        outcome = _reroute(order, assignment, assignment["store_id"])
        notification_type = notifications.choose_type(
            "short_pick",
            dc_fallback_raised=outcome["dc_fallback_units"] > 0,
            replacements_created=len(outcome["created"]) > 0)
        notifications.emit(order, assignment, notification_type,
                           assignment["shortfall_units"])
    return finish(assignment, 200, explicit=[assignment])


# ------------------------------------------------------------------- pack

@bp.route(API_PREFIX + "/assignments/<assignment_id>/pack", methods=["POST"])
def pack_assignment(assignment_id):
    actor, role = authenticate(ROLE_ASSOCIATE)
    payload = body()
    package_type = get_enum(payload, "package_type", PACKAGE_TYPES)

    assignment = fetch("assignments", assignment_id)
    require_scope(actor, role, assignment["store_id"])
    if assignment["status"] not in ("PICKED", "SHORT_PICKED"):
        raise ApiError("ERR_ASSIGNMENT_STATE_INVALID")
    store = _store_of(assignment)
    _require_active_node(store)
    _require_cutoff(store)

    supply = packaging_for(store["id"], package_type)
    if supply is None or supply["on_hand_units"] < 1:
        raise ApiError("ERR_PACKAGING_DEPLETED")
    if PACKAGE_RANK[package_type] < PACKAGE_RANK[assignment["derived_package_type"]]:
        raise ApiError("ERR_PACKAGE_TYPE_TOO_SMALL")

    now = clock.now()
    assignment["status"] = "PACKED"
    assignment["packed_at"] = now
    assignment["package_type"] = package_type
    assignment["labor_minutes_actual"] = n2(
        minutes_between_floor(now, assignment["accepted_at"]))
    supply["on_hand_units"] = supply["on_hand_units"] - 1
    supply["lifetime_consumed_units"] = supply["lifetime_consumed_units"] + 1
    return finish(assignment, 200, explicit=[assignment])


# ------------------------------------------------------------------- ship

@bp.route(API_PREFIX + "/assignments/<assignment_id>/ship", methods=["POST"])
def ship_assignment(assignment_id):
    actor, role = authenticate(ROLE_ASSOCIATE)
    payload = body()
    pickup_id = get_str(payload, "carrier_pickup_id")
    expected_pickup_version = get_int(payload, "expected_pickup_version")

    assignment = fetch("assignments", assignment_id)
    pickup = fetch("pickups", pickup_id)
    require_scope(actor, role, assignment["store_id"])
    if expected_pickup_version != pickup["version"]:
        raise ApiError("ERR_STALE_PICKUP_VERSION")
    if assignment["status"] != "PACKED":
        raise ApiError("ERR_ASSIGNMENT_STATE_INVALID")
    if pickup["status"] != "SCHEDULED":
        raise ApiError("ERR_PICKUP_STATE_INVALID")
    store = _store_of(assignment)
    _require_active_node(store)
    _require_cutoff(store)

    now = clock.now()
    if not (pickup["window_start_utc"] <= now < pickup["window_end_utc"]):
        raise ApiError("ERR_PICKUP_WINDOW_CLOSED")
    if pickup["reserved_parcels"] >= pickup["parcel_capacity"]:
        raise ApiError("ERR_PICKUP_CAPACITY_EXCEEDED")
    if pickup["store_id"] != assignment["store_id"]:
        raise ApiError("ERR_PICKUP_STORE_MISMATCH")

    order = _order_of(assignment)
    assignment["status"] = "SHIPPED"
    assignment["shipped_at"] = now
    assignment["carrier_pickup_id"] = pickup["id"]
    assignment["cycle_time_minutes"] = minutes_between_floor(
        now, assignment["created_at"])
    assignment["final_cost_cents"] = final_cost(order, store, assignment)

    for al in assignment_lines_of(assignment["id"]):
        order_line = db.order_lines[al["order_line_id"]]
        inventory = inventory_for(store["id"], order_line["sku_id"])
        if inventory is not None:
            inventory["on_hand_units"] = max(
                0, inventory["on_hand_units"] - al["units_picked"])
    return finish(assignment, 200, explicit=[assignment, pickup])


# ----------------------------------------------------------------- cancel

@bp.route(API_PREFIX + "/assignments/<assignment_id>/cancel", methods=["POST"])
def cancel_assignment(assignment_id):
    authenticate(ROLE_CARE)
    payload = body()
    reason = get_enum(payload, "cancel_reason_code", CARE_CANCEL_REASONS)
    reroute = get_bool(payload, "reroute")

    assignment = fetch("assignments", assignment_id)
    if assignment["status"] not in ("ASSIGNED", "ACCEPTED", "PICKED", "SHORT_PICKED"):
        raise ApiError("ERR_ASSIGNMENT_STATE_INVALID")

    order = _order_of(assignment)
    released = release_assignment(assignment, "CANCELLED", reason,
                                  to_cancelled_units=not reroute)
    recompute_all()

    dc_raised = False
    replacements = False
    if reroute:
        outcome = _reroute(order, assignment, assignment["store_id"])
        dc_raised = outcome["dc_fallback_units"] > 0
        replacements = len(outcome["created"]) > 0

    notification_type = notifications.choose_type(
        "assignment_cancel", reroute=reroute, dc_fallback_raised=dc_raised,
        replacements_created=replacements)
    notifications.emit(order, assignment, notification_type, released)
    return finish(assignment, 200, explicit=[assignment])
