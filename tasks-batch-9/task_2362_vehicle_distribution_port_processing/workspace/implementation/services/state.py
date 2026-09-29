"""Derived-counter maintenance, selectors and cascades.

Every recompute_* helper rewrites the stored derived fields of one record and
bumps its version/updated_at only when a value actually changed (PRD §2.4).
"""
import db
from services import calculations as calc

ACTIVE_RELEASE_STATUSES = ("ALLOCATED", "RELEASED")
LIVE_CLAIM_STATUSES = ("FILED", "ACCEPTED_PENDING_SETTLEMENT", "DISPUTED")
OPEN_CLAIM_STATUSES = ("FILED", "ACCEPTED_PENDING_SETTLEMENT", "DISPUTED", "SETTLED")


def _apply(record, values):
    changed = False
    for name, value in values.items():
        if record.get(name) != value:
            record[name] = value
            changed = True
    if changed:
        db.touch(record)
    return changed


# ------------------------------------------------------------------ centers
def recompute_center(center):
    center_id = center["id"]
    units = [v for v in db.vehicles.values() if v["processing_center_id"] == center_id]
    occupied = len([v for v in units if v["yard_presence"] == "IN_YARD"])
    capacity = center["yard_capacity_slots"]
    provisional = sum(
        v["storage_charge_provisional_cents"]
        for v in units
        if v["processing_status"] in ("ALLOCATED", "RELEASED")
    )
    realized = sum(
        v["storage_charge_final_cents"] for v in units if v["yard_presence"] == "DEPARTED"
    )
    unit_ids = {v["id"] for v in units}
    repair_spend = sum(
        (r["actual_cost_cents"] or 0)
        for r in db.repair_orders.values()
        if r["status"] == "COMPLETED" and r["vehicle_id"] in unit_ids
    )
    return _apply(
        center,
        {
            "yard_occupied_slots": occupied,
            "yard_free_slots": capacity - occupied,
            "yard_posture": calc.yard_posture(occupied, capacity),
            "provisional_storage_accrued_cents": provisional,
            "realized_storage_revenue_cents": realized,
            "repair_spend_cents": repair_spend,
        },
    )


def center_of_vehicle(vehicle):
    return db.centers.get(vehicle["processing_center_id"])


# ------------------------------------------------------------------ vessels
def recompute_vessel(vessel):
    count = len([v for v in db.vehicles.values() if v["vessel_id"] == vessel["id"]])
    return _apply(vessel, {"discharged_unit_count": count})


# ------------------------------------------------------------- accessory kits
def recompute_kit(kit):
    kit_id = kit["id"]
    reserved = sum(
        w["qty"]
        for w in db.work_orders.values()
        if w["accessory_kit_id"] == kit_id and w["status"] == "KITTED"
    )
    consumed = sum(
        w["qty"]
        for w in db.work_orders.values()
        if w["accessory_kit_id"] == kit_id and w["status"] == "INSTALLED"
    )
    return _apply(
        kit,
        {
            "reserved_qty": reserved,
            "consumed_qty": consumed,
            "available_qty": kit["on_hand_qty"] - reserved,
        },
    )


def vehicle_accessory_billed(vehicle_id):
    return sum(
        w["billed_cents"]
        for w in db.work_orders.values()
        if w["vehicle_id"] == vehicle_id and w["status"] == "INSTALLED"
    )


# ---------------------------------------------------------- carriers / dealers
def recompute_carrier(carrier):
    committed = len(
        [
            o
            for o in db.release_orders.values()
            if o["truck_carrier_id"] == carrier["id"]
            and o["status"] in ACTIVE_RELEASE_STATUSES
        ]
    )
    return _apply(
        carrier,
        {
            "committed_slots": committed,
            "available_slots": carrier["slot_capacity"] - committed,
        },
    )


def recompute_dealer(dealer):
    count = len(
        [
            o
            for o in db.release_orders.values()
            if o["dealer_id"] == dealer["id"] and o["status"] in ACTIVE_RELEASE_STATUSES
        ]
    )
    return _apply(dealer, {"open_allocation_count": count})


def free_slots(carrier):
    committed = len(
        [
            o
            for o in db.release_orders.values()
            if o["truck_carrier_id"] == carrier["id"]
            and o["status"] in ACTIVE_RELEASE_STATUSES
        ]
    )
    return carrier["slot_capacity"] - committed


def select_carrier(route_zone):
    """calculations.carrier_selection — ACTIVE, serves the zone, has a free slot.

    Ranked by rate ascending, then free slots descending, then created_at ascending.
    """
    candidates = []
    for carrier in db.ordered(db.carriers):
        if carrier["status"] != "ACTIVE":
            continue
        if route_zone not in carrier["served_route_zones"]:
            continue
        available = free_slots(carrier)
        if available < 1:
            continue
        candidates.append((carrier, available))
    if not candidates:
        return None
    candidates.sort(
        key=lambda pair: (
            pair[0]["linehaul_rate_cents_per_mile"],
            -pair[1],
            pair[0]["_seq"],
        )
    )
    return candidates[0][0]


def carrier_window_capacity_ok(order, carrier):
    """Aggregate concurrency over half-open pickup windows; adjacency allowed."""
    start = order["pickup_window_start"]
    end = order["pickup_window_end"]
    peers = [
        o
        for o in db.release_orders.values()
        if o["truck_carrier_id"] == order["truck_carrier_id"]
        and o["status"] == "RELEASED"
        and o["id"] != order["id"]
    ]
    instants = [start]
    for peer in peers:
        if start <= peer["pickup_window_start"] < end:
            instants.append(peer["pickup_window_start"])
    max_concurrent = 0
    for instant in instants:
        covering = len(
            [
                p
                for p in peers
                if p["pickup_window_start"] <= instant < p["pickup_window_end"]
            ]
        )
        max_concurrent = max(max_concurrent, 1 + covering)
    return max_concurrent <= carrier["concurrent_load_capacity"]


# ------------------------------------------------------------- release orders
def active_release_order(vehicle_id):
    for order in db.ordered(db.release_orders):
        if order["vehicle_id"] == vehicle_id and order["status"] in ACTIVE_RELEASE_STATUSES:
            return order
    return None


# ------------------------------------------------------------------- claims
def surveys_of_vehicle(vehicle_id):
    return [s for s in db.ordered(db.surveys) if s["vehicle_id"] == vehicle_id]


def claims_of_vehicle(vehicle_id):
    survey_ids = {s["id"] for s in db.surveys.values() if s["vehicle_id"] == vehicle_id}
    return [c for c in db.ordered(db.claims) if c["damage_survey_id"] in survey_ids]


def claims_of_survey(survey_id):
    return [c for c in db.ordered(db.claims) if c["damage_survey_id"] == survey_id]


def claim_recoverable(claim):
    """Recompute recoverable_amount_cents under the claim's current basis."""
    if claim["recoverable_basis"] == "REPAIR_ACTUAL":
        actual = sum(
            (r["actual_cost_cents"] or 0)
            for r in db.repair_orders.values()
            if r["carrier_claim_id"] == claim["id"] and r["status"] == "COMPLETED"
        )
        basis = min(claim["claimed_amount_cents"], actual)
    else:
        basis = claim["claimed_amount_cents"]
    return calc.recoverable_from_basis(basis)


# -------------------------------------------------------------------- holds
def hold_covers(hold, vehicle):
    if hold["scope_type"] == "MODEL_LINE":
        return (
            hold["processing_center_id"] == vehicle["processing_center_id"]
            and hold["model_line"] == vehicle["model_line"]
        )
    return hold["vehicle_id"] == vehicle["id"]


def open_holds_covering(vehicle, exclude_hold_id=None):
    result = []
    for hold in db.ordered(db.hold_orders):
        if hold["status"] != "OPEN":
            continue
        if exclude_hold_id is not None and hold["id"] == exclude_hold_id:
            continue
        if hold_covers(hold, vehicle):
            result.append(hold)
    return result


# ------------------------------------------------------- storage stamping
def stamp_provisional_storage(vehicle, center, allocation_instant):
    end_instant = calc.provisional_end_instant(allocation_instant)
    return calc.storage_charge_cents(
        vehicle["yard_in_at"],
        end_instant,
        center["free_storage_days"],
        0,
        center["daily_storage_rate_cents"],
    )


def stamp_final_storage(vehicle, center, gate_out_instant):
    return calc.storage_charge_cents(
        vehicle["yard_in_at"],
        gate_out_instant,
        center["free_storage_days"],
        vehicle["blocked_credit_days"],
        center["daily_storage_rate_cents"],
    )


# ------------------------------------------------ release-order unwinding
def unwind_release_order(order, new_status, hold_order_id=None):
    """Cancel an ALLOCATED/RELEASED order and reverse its commercial effects."""
    order["status"] = new_status
    if hold_order_id is not None:
        order["cancelled_by_hold_order_id"] = hold_order_id
    db.touch(order)

    vehicle = db.vehicles.get(order["vehicle_id"])
    if vehicle is not None:
        changed = False
        if vehicle["processing_status"] in ("ALLOCATED", "RELEASED"):
            vehicle["processing_status"] = "SHIPPING_READY"
            changed = True
        if vehicle["storage_charge_provisional_cents"] != 0:
            vehicle["storage_charge_provisional_cents"] = 0
            changed = True
        if changed:
            db.touch(vehicle)

    carrier = db.carriers.get(order["truck_carrier_id"])
    if carrier is not None:
        recompute_carrier(carrier)
    dealer = db.dealers.get(order["dealer_id"])
    if dealer is not None:
        recompute_dealer(dealer)
    if vehicle is not None:
        center = center_of_vehicle(vehicle)
        if center is not None:
            recompute_center(center)
    return order
