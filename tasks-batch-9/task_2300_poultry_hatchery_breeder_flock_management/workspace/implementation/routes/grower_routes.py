"""Grower farms, placement orders, the whole-box waterfall and delivery
(PRD §3.3 farms, §3.8, §3.9)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import serializers
import services
from errors import fail
from helpers import (apply_filters, authorize, body, is_int, must_get, need_dt,
                     need_enum, need_int, need_str, ok, ok_array, ok_list, pagination,
                     paginate, resolve_fk)
from errors import invalid_request
from store import store

bp = Blueprint("grower", __name__)

OPEN_ORDER_STATES = ("CONFIRMED", "PARTIALLY_FULFILLED")
CAPACITY_STATES = ("CONFIRMED", "PARTIALLY_FULFILLED", "FULFILLED")


def _scope_violation():
    fail("ERR_FARM_SCOPE_VIOLATION", "The farm is outside the principal's scope.")


def _owned_farm_ids(user_id):
    return set(f["id"] for f in store.grower_farms.values()
               if f["operator_user_id"] == user_id)


def _cycle(order):
    start = order["requested_placement_date"]
    return start, start + timedelta(days=calc.FARM_CYCLE_DAYS)


# ---------------------------------------------------------------------------
# Grower farms
# ---------------------------------------------------------------------------
@bp.post("/grower-farms")
def create_grower_farm():
    authorize(("HatcheryManager",))
    data = body()
    code = need_str(data, "code", 1, 40)
    operator_user_id = need_str(data, "operator_user_id", 1)
    capacity = data.get("capacity_chicks")
    if not is_int(capacity):
        invalid_request("capacity_chicks must be an integer.")
    if capacity < 1000:
        fail("ERR_NON_POSITIVE_COUNT", "capacity_chicks must be at least 1000.")

    rec = store.new_record(code=code, operator_user_id=operator_user_id,
                           capacity_chicks=capacity, biosecurity_status="PENDING",
                           cleared_at=None)
    store.grower_farms[rec["id"]] = rec
    return ok(serializers.grower_farm(rec), 201)


@bp.get("/grower-farms/<rid>")
def get_grower_farm(rid):
    user_id, role = authorize(("HatcheryManager", "Veterinarian", "GrowerFarm"))
    if role == "GrowerFarm":
        # rank 3 — scoping is evaluated before existence
        farm = store.grower_farms.get(rid)
        if farm is None or farm["operator_user_id"] != user_id:
            _scope_violation()
        return ok(serializers.grower_farm(farm))
    return ok(serializers.grower_farm(must_get("grower_farms", rid)))


@bp.post("/grower-farms/<rid>/clear")
def clear_grower_farm(rid):
    authorize(("Veterinarian",))
    farm = must_get("grower_farms", rid)
    farm["biosecurity_status"] = "CLEARED"
    farm["cleared_at"] = store.clock
    store.touch(farm)
    return ok(serializers.grower_farm(farm))


# ---------------------------------------------------------------------------
# Placement orders
# ---------------------------------------------------------------------------
@bp.post("/placement-orders")
def create_placement_order():
    user_id, role = authorize(("HatcheryManager", "GrowerFarm"))
    data = body()

    if role == "GrowerFarm":
        farm_id = data.get("farm_id")
        farm = store.grower_farms.get(farm_id) if isinstance(farm_id, str) else None
        if farm is None or farm["operator_user_id"] != user_id:
            _scope_violation()
    else:
        farm = resolve_fk("grower_farms", data, "farm_id")

    if farm is None:
        need_str(data, "farm_id", 1)
    breed = need_enum(data, "requested_breed", calc.BREEDS)
    placement_date = need_dt(data, "requested_placement_date")
    requested = need_int(data, "requested_chicks")

    if requested < calc.BOX_SIZE:
        fail("ERR_NON_POSITIVE_COUNT",
             "requested_chicks must be at least one full box.")

    if placement_date.date() < store.clock.date():
        fail("ERR_TIMESTAMP_OUT_OF_RANGE",
             "requested_placement_date may not precede the current clock date.")

    rec = store.new_record(farm_id=farm["id"], requested_breed=breed,
                           requested_placement_date=placement_date,
                           requested_chicks=requested, allocated_chicks=0,
                           remaining_need=requested, status="REQUESTED")
    store.placement_orders[rec["id"]] = rec
    return ok(serializers.placement_order(rec), 201)


@bp.get("/placement-orders/<rid>")
def get_placement_order(rid):
    user_id, role = authorize(("HatcheryManager", "GrowerFarm"))
    if role == "GrowerFarm":
        order = store.placement_orders.get(rid)
        if order is None:
            _scope_violation()
        farm = store.grower_farms.get(order["farm_id"])
        if farm is None or farm["operator_user_id"] != user_id:
            _scope_violation()
        return ok(serializers.placement_order(order))
    return ok(serializers.placement_order(must_get("placement_orders", rid)))


@bp.get("/placement-orders")
def list_placement_orders():
    user_id, role = authorize(("HatcheryManager", "GrowerFarm"))
    rows = store.sorted_rows("placement_orders")
    if role == "GrowerFarm":
        owned = _owned_farm_ids(user_id)
        wanted_farm = request.args.get("farm_id")
        if wanted_farm is not None and wanted_farm not in owned:
            _scope_violation()
        rows = [r for r in rows if r["farm_id"] in owned]
    limit, offset = pagination()
    rows = apply_filters(rows, {"farm_id": "farm_id", "status": "status",
                                "requested_breed": "requested_breed"})
    page, limit, offset, total = paginate(rows, limit, offset,
                                         serializers.placement_order)
    return ok_list(page, limit, offset, total)


@bp.post("/placement-orders/<rid>/confirm")
def confirm_placement_order(rid):
    authorize(("HatcheryManager",))
    order = must_get("placement_orders", rid)

    if order["status"] != "REQUESTED":
        fail("ERR_ORDER_INVALID_STATE", "Only a REQUESTED order can be confirmed.")

    farm = store.grower_farms.get(order["farm_id"])
    if farm is None or farm["biosecurity_status"] != "CLEARED":
        fail("ERR_FARM_NOT_CLEARED", "The destination farm is not cleared.")

    new_start, new_end = _cycle(order)
    total = order["requested_chicks"]
    for other in store.placement_orders.values():
        if other["id"] == order["id"] or other["farm_id"] != order["farm_id"]:
            continue
        if other["status"] not in CAPACITY_STATES:
            continue
        other_start, other_end = _cycle(other)
        # half-open interval: touching endpoints do not overlap
        if new_start < other_end and other_start < new_end:
            total += other["requested_chicks"]
    if total > farm["capacity_chicks"]:
        fail("ERR_FARM_CAPACITY_EXCEEDED",
             "The farm's aggregate cycle capacity would be exceeded.")

    order["status"] = "CONFIRMED"
    store.touch(order)
    return ok(serializers.placement_order(order))


# ---------------------------------------------------------------------------
# Allocation waterfall
# ---------------------------------------------------------------------------
@bp.post("/chick-batches/<rid>/allocations")
def run_allocation(rid):
    authorize(("HatcheryManager",))
    batch = must_get("chick_batches", rid)
    data = body()

    expected = data.get("expected_chick_batch_version")
    if not is_int(expected):
        invalid_request("expected_chick_batch_version must be an integer.")

    # rank 10 — optimistic concurrency on the batch
    if expected != batch["version"]:
        fail("ERR_STALE_VERSION",
             "expected_chick_batch_version does not match the batch.")

    # rank 15 — the batch must be boxed
    if batch["status"] != "BOXED":
        fail("ERR_CHICK_FLOW_INVALID_STATE", "Only a BOXED batch can be allocated.")

    today = store.clock.date()
    eligible = []
    for order in store.sorted_rows("placement_orders"):
        if order["status"] not in OPEN_ORDER_STATES:
            continue
        if order["requested_breed"] != batch["breed"]:
            continue
        farm = store.grower_farms.get(order["farm_id"])
        if farm is None or farm["biosecurity_status"] != "CLEARED":
            continue
        if abs((order["requested_placement_date"].date() - today).days) \
                > calc.DELIVERY_TOLERANCE_DAYS:
            continue
        if order["remaining_need"] <= 0:
            continue
        eligible.append(order)

    if not eligible:
        fail("ERR_NO_ELIGIBLE_PLACEMENT_ORDER",
             "No placement order qualifies for this batch.")

    eligible.sort(key=lambda o: (o["requested_placement_date"],
                                 -o["remaining_need"], o["created_at"], o["_seq"]))

    pool = batch["unassigned_chicks"]
    created = []
    for order in eligible:
        if pool < calc.BOX_SIZE:
            break
        grant = (min(order["remaining_need"], pool) // calc.BOX_SIZE) * calc.BOX_SIZE
        if grant == 0:
            continue
        assignment = store.new_record(
            chick_batch_id=batch["id"], placement_order_id=order["id"],
            chicks_assigned=grant, boxes_assigned=grant // calc.BOX_SIZE,
            scheduled_delivery_date=order["requested_placement_date"],
            delivered_at=None, reversal_reason=None, status="ASSIGNED",
        )
        store.delivery_assignments[assignment["id"]] = assignment
        created.append(assignment)

        pool -= grant
        order["allocated_chicks"] = order["allocated_chicks"] + grant
        order["remaining_need"] = order["requested_chicks"] - order["allocated_chicks"]
        order["status"] = "FULFILLED" if order["remaining_need"] == 0 \
            else "PARTIALLY_FULFILLED"
        store.touch(order)

    batch["unassigned_chicks"] = pool
    store.touch(batch)

    return ok_array([serializers.delivery_assignment(a) for a in created], 201)


# ---------------------------------------------------------------------------
# Delivery assignments
# ---------------------------------------------------------------------------
def _assignment_farm(assignment):
    order = store.placement_orders.get(assignment["placement_order_id"])
    if order is None:
        return None
    return store.grower_farms.get(order["farm_id"])


@bp.get("/delivery-assignments/<rid>")
def get_delivery_assignment(rid):
    user_id, role = authorize(("HatcheryManager", "GrowerFarm"))
    if role == "GrowerFarm":
        assignment = store.delivery_assignments.get(rid)
        if assignment is None:
            _scope_violation()
        farm = _assignment_farm(assignment)
        if farm is None or farm["operator_user_id"] != user_id:
            _scope_violation()
        return ok(serializers.delivery_assignment(assignment))
    return ok(serializers.delivery_assignment(must_get("delivery_assignments", rid)))


@bp.get("/delivery-assignments")
def list_delivery_assignments():
    user_id, role = authorize(("HatcheryManager", "GrowerFarm"))
    rows = store.sorted_rows("delivery_assignments")
    if role == "GrowerFarm":
        owned = _owned_farm_ids(user_id)
        wanted_order = request.args.get("placement_order_id")
        if wanted_order is not None:
            order = store.placement_orders.get(wanted_order)
            if order is None or order["farm_id"] not in owned:
                _scope_violation()
        rows = [r for r in rows
                if (_assignment_farm(r) or {}).get("id") in owned]
    limit, offset = pagination()
    rows = apply_filters(rows, {"chick_batch_id": "chick_batch_id",
                                "placement_order_id": "placement_order_id",
                                "status": "status"})
    page, limit, offset, total = paginate(rows, limit, offset,
                                         serializers.delivery_assignment)
    return ok_list(page, limit, offset, total)


@bp.post("/delivery-assignments/<rid>/deliver")
def deliver_assignment(rid):
    authorize(("HatcheryManager",))
    assignment = must_get("delivery_assignments", rid)

    if assignment["status"] != "ASSIGNED":
        fail("ERR_ASSIGNMENT_INVALID_STATE",
             "Only an ASSIGNED assignment can be delivered.")

    farm = _assignment_farm(assignment)
    if farm is None or farm["biosecurity_status"] != "CLEARED":
        fail("ERR_FARM_NOT_CLEARED", "The destination farm is not cleared.")

    if services.date_diff_days(store.clock, assignment["scheduled_delivery_date"]) \
            > calc.DELIVERY_TOLERANCE_DAYS:
        fail("ERR_TIMESTAMP_OUT_OF_RANGE",
             "The delivery falls outside the delivery tolerance.")

    assignment["delivered_at"] = store.clock
    assignment["status"] = "DELIVERED"
    store.touch(assignment)
    return ok(serializers.delivery_assignment(assignment))


@bp.post("/delivery-assignments/<rid>/reverse")
def reverse_assignment(rid):
    authorize(("HatcheryManager",))
    assignment = must_get("delivery_assignments", rid)
    data = body()
    reason = need_str(data, "reason", 1)

    if assignment["status"] != "ASSIGNED":
        fail("ERR_ASSIGNMENT_INVALID_STATE",
             "Only an ASSIGNED assignment can be reversed.")

    assignment["status"] = "REVERSED"
    assignment["reversal_reason"] = reason
    store.touch(assignment)

    batch = store.chick_batches.get(assignment["chick_batch_id"])
    if batch is not None:
        batch["unassigned_chicks"] = (batch["unassigned_chicks"] or 0) \
            + assignment["chicks_assigned"]
        store.touch(batch)

    order = store.placement_orders.get(assignment["placement_order_id"])
    if order is not None:
        order["allocated_chicks"] = order["allocated_chicks"] \
            - assignment["chicks_assigned"]
        order["remaining_need"] = order["requested_chicks"] - order["allocated_chicks"]
        if order["allocated_chicks"] <= 0:
            order["allocated_chicks"] = 0
            order["remaining_need"] = order["requested_chicks"]
            order["status"] = "CONFIRMED"
        else:
            order["status"] = "PARTIALLY_FULFILLED"
        store.touch(order)

    return ok(serializers.delivery_assignment(assignment))
