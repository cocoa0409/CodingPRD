"""Order routing: eligibility filter, deterministic stall selection, prep-window
reservation, FIFO inventory deduction, sold-out flips, and commission estimate.

Implements scaffold §1.3 order_routing_selection / order_prep_window and the
PRD §3.5 routing cascade.
"""
import errors
from db import store
from services import inventory, scheduling, calculations
from services.common import new_entity, touch


def active_leases_for_brand_at_stall(brand_id, stall_id):
    return [
        l for l in store.leases.values()
        if l["brand_id"] == brand_id and l["stall_id"] == stall_id
        and l["status"] == "ACTIVE"
    ]


def required_minutes_by_type(line_items_resolved):
    """total occupancy per equipment_type = sum of prep_minutes * qty over the
    line items whose menu item requires that type."""
    by_type = {}
    for menu_item, qty in line_items_resolved:
        et = menu_item["required_equipment_type"]
        by_type[et] = by_type.get(et, 0) + menu_item["prep_minutes"] * qty
    return by_type


def find_units_for_window(stall_id, type_minutes, start_minute):
    """For each required equipment type, pick an AVAILABLE unit at the stall
    that can host [start_minute, start_minute + minutes) without overlap/buffer
    violation. Returns {equipment_type: (equipment, start, end)} or None if any
    type cannot be satisfied.

    Each required type books a distinct unit; we greedily assign the first
    free AVAILABLE unit (ordered by created_at then seq) per type. Different
    types are independent units, so no cross-type contention exists."""
    assignment = {}
    for et, minutes in type_minutes.items():
        end_minute = start_minute + minutes
        units = [
            e for e in store.equipment.values()
            if e["stall_id"] == stall_id and e["equipment_type"] == et
            and e["status"] == "AVAILABLE"
        ]
        units.sort(key=lambda e: (e["created_at"], e["_seq"]))
        chosen = None
        for unit in units:
            if scheduling.window_is_free(unit, start_minute, end_minute):
                chosen = unit
                break
        if chosen is None:
            return None
        assignment[et] = (chosen, start_minute, end_minute)
    return assignment


def eligible_candidates(order, line_items_resolved):
    """Return list of (stall, lease, assignment) for every routing-eligible
    stall, where assignment is the per-type equipment window plan.

    Eligibility (scaffold order_routing_selection / PRD §3.5):
      (1) an ACTIVE KitchenLease binds brand->stall
      (2) stall.status == OPEN
      (3) for every required equipment type, an AVAILABLE unit can host the
          contiguous window without overlap/buffer violation
      (4) sufficient FIFO inventory for ALL line items at the stall
    """
    start_minute = store.current_clock_minute()
    type_minutes = required_minutes_by_type(line_items_resolved)
    needs = inventory.needs_for_order(order, line_items_resolved)

    candidates = []
    # A brand may have several ACTIVE leases at distinct stalls; consider each.
    for lease in store.leases.values():
        if lease["brand_id"] != order["brand_id"] or lease["status"] != "ACTIVE":
            continue
        stall = store.stalls.get(lease["stall_id"])
        if stall is None or stall["status"] != "OPEN":
            continue
        assignment = find_units_for_window(stall["id"], type_minutes, start_minute)
        if assignment is None:
            continue
        if not inventory.can_fully_satisfy(stall["id"], needs):
            continue
        candidates.append((stall, lease, assignment))
    return candidates


def select_candidate(candidates):
    """Deterministic pick: lease.priority_rank ASC, then lease.created_at ASC
    (then creation seq) tiebreak — never id."""
    candidates.sort(
        key=lambda c: (c[1]["priority_rank"], c[1]["created_at"], c[1]["_seq"])
    )
    return candidates[0]


def route_order(order, line_items_resolved):
    """Execute the INGESTED->ROUTED cascade. Caller has verified state and
    brand-listed-ness. Raises ERR_NO_ELIGIBLE_STALL / ERR_INSUFFICIENT_INVENTORY
    as appropriate WITHOUT mutating the order on failure.

    Precedence note (PRD §3.10): ERR_NO_ELIGIBLE_STALL (priority 8) is checked
    before ERR_INSUFFICIENT_INVENTORY (priority 10). The eligibility filter
    folds inventory into stall eligibility, but to surface the correct error we
    distinguish: if NO stall passes the equipment/open/lease checks, that is
    ERR_NO_ELIGIBLE_STALL; if some stall passes those but none has inventory,
    that is ERR_INSUFFICIENT_INVENTORY.
    """
    start_minute = store.current_clock_minute()
    type_minutes = required_minutes_by_type(line_items_resolved)
    needs = inventory.needs_for_order(order, line_items_resolved)

    # First pass: stalls passing lease + open + equipment window (ignoring inv).
    structural = []  # (stall, lease, assignment)
    for lease in store.leases.values():
        if lease["brand_id"] != order["brand_id"] or lease["status"] != "ACTIVE":
            continue
        stall = store.stalls.get(lease["stall_id"])
        if stall is None or stall["status"] != "OPEN":
            continue
        assignment = find_units_for_window(stall["id"], type_minutes, start_minute)
        if assignment is None:
            continue
        structural.append((stall, lease, assignment))

    if not structural:
        raise errors.no_eligible_stall()

    # Second pass: among structurally-eligible stalls, those with inventory.
    with_inventory = [
        c for c in structural if inventory.can_fully_satisfy(c[0]["id"], needs)
    ]
    if not with_inventory:
        raise errors.insufficient_inventory()

    stall, lease, assignment = select_candidate(with_inventory)

    # ---- Commit cascade (all-or-nothing; preconditions already passed) ----
    # Hop 1: reserve equipment booking(s). For multiple required types each
    # type gets its own unit/window; the order's booking_id references the
    # primary booking. We create one booking per required type.
    booking_ids = []
    primary_booking_id = None
    for et, (unit, s, e) in assignment.items():
        booking = new_entity("EquipmentBooking", {
            "equipment_id": unit["id"],
            "order_id": order["id"],
            "start_minute": s,
            "end_minute": e,
            "status": "HELD",
        })
        store.bookings[booking["id"]] = booking
        booking_ids.append(booking["id"])
        if primary_booking_id is None:
            primary_booking_id = booking["id"]

    order["routed_stall_id"] = stall["id"]
    order["booking_id"] = primary_booking_id
    order["_booking_ids"] = booking_ids

    # Snapshot availability of every menu item that could be affected by this
    # deduction (any item whose recipe uses one of the consumed ingredients,
    # evaluated at the routed stall) BEFORE deducting, so cancellation knows
    # exactly which items THIS order flipped to SOLD_OUT (PRD §3.8).
    affected_items = {}
    for ingredient_name in needs:
        for mi in inventory.menu_items_using_ingredient_at_stall(ingredient_name, stall["id"]):
            affected_items[mi["id"]] = mi["availability"]

    # Hop 2: deduct inventory FIFO, recording consumption slices.
    inventory.consume_fifo(order, stall["id"], needs)

    # Hop 3: flip any menu item left short to SOLD_OUT (at this stall).
    inventory.reevaluate_for_needs(needs, stall["id"])

    # Record which items THIS order flipped AVAILABLE->SOLD_OUT.
    flips = []
    for mid, before in affected_items.items():
        mi = store.menu_items.get(mid)
        if mi is not None and before == "AVAILABLE" and mi["availability"] == "SOLD_OUT":
            flips.append(mid)
    order["_sold_out_flips"] = flips

    # Commission (forward-looking) from snapshotted gross + brand current rate.
    brand = store.brands[order["brand_id"]]
    order["commission_cents"] = calculations.order_commission(
        order["gross_revenue_cents"], brand["commission_rate_bps"]
    )

    order["status"] = "ROUTED"
    touch(order)
