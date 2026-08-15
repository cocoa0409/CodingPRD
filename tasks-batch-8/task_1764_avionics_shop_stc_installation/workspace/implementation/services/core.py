"""Business logic: derived roll-ups, pricing, weight & balance, scheduling
conflicts, ownership, and cascades. All formulas follow the scaffold
calculation table exactly (round half-up at the pinned step)."""
from datetime import timedelta
from decimal import Decimal

import db
import errors
from db import touch
from util import D, rhu

# --- Calculation constants (scaffold section 1.3) ---
SHOP_RATE_CENTS_PER_HOUR = 14500
DISCOUNT_RATES = {
    "FLEET_OPERATOR": Decimal("0.10"),
    "FLIGHT_SCHOOL": Decimal("0.05"),
    "INDIVIDUAL": Decimal("0.00"),
}
REGULAR_HOUR_CAP = Decimal("8.0")
OVERTIME_MULTIPLIER = Decimal("1.5")
TASK_KIND_MULTIPLIERS = {
    "HARNESS_FABRICATION": Decimal("1.0"),
    "PANEL_ASSEMBLY": Decimal("1.1"),
    "INSTALLATION": Decimal("1.25"),
}
OVERAGE_ACK_THRESHOLD_DAYS = 5
CHANGE_ORDER_FLOOR_CENTS = 250000
FLIGHT_BUFFER = timedelta(minutes=60)

WO_TERMINAL = ("COMPLETED", "CANCELLED")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def work_orders_of_aircraft(aircraft_id):
    return [w for w in db.work_orders.values() if w.aircraft_id == aircraft_id]


def children_of(store, work_order_id):
    return [e for e in store.values() if e.work_order_id == work_order_id]


def owner_customer_id(wo):
    return db.aircraft[wo.aircraft_id].customer_id


def check_customer_ownership(wo, user_id):
    """Customer-role ownership: X-User-ID must equal the id of the Customer
    owning the aircraft of the target work order."""
    if owner_customer_id(wo) != user_id:
        errors.raise_err(
            errors.ERR_FORBIDDEN,
            "Customer does not own the aircraft for this work order",
        )


# ---------------------------------------------------------------------------
# Work order derived counters and roll-ups (calculation: derived_counts_and_totals)
# ---------------------------------------------------------------------------
def recompute_work_order(wo):
    orders = children_of(db.equipment_orders, wo.id)
    tasks = children_of(db.install_tasks, wo.id)
    wo.parts_pending_count = sum(
        1 for o in orders if o.status in ("PLANNED", "ORDERED")
    )
    wo.tasks_unverified_count = sum(
        1 for t in tasks if t.status in ("PLANNED", "IN_PROGRESS", "COMPLETED")
    )
    hours = sum(
        (
            D(str(t.actual_hours))
            for t in tasks
            if t.status in ("COMPLETED", "VERIFIED") and t.actual_hours is not None
        ),
        Decimal(0),
    )
    wo.total_actual_labor_hours = float(rhu(hours, 1))
    wo.total_billed_labor_cents = sum(
        t.billed_labor_cents or 0 for t in tasks if t.status == "VERIFIED"
    )
    # Recomputation refreshes updated_at but does NOT advance version (PRD 2.9).
    touch(wo, bump=False)


def set_aircraft_availability(aircraft_id):
    ac = db.aircraft[aircraft_id]
    busy = any(
        w.status not in WO_TERMINAL for w in work_orders_of_aircraft(aircraft_id)
    )
    new_status = "IN_SHOP" if busy else "AVAILABLE"
    if ac.status != new_status:
        ac.status = new_status
        touch(ac)


def next_order_seq(work_order_id):
    seqs = [o.seq for o in children_of(db.equipment_orders, work_order_id)]
    return (max(seqs) if seqs else 0) + 1


# ---------------------------------------------------------------------------
# Pricing (calculations: quote_total, labor_billing)
# ---------------------------------------------------------------------------
def quote_total(wo):
    """quoted_total_cents = round(quoted_labor_hours * rate)
       + round(equipment_subtotal * (1 - discount_rate)); integer cents, half-up.
    Reads the highest-revision non-SUPERSEDED PanelDesign."""
    designs = [
        d
        for d in children_of(db.panel_designs, wo.id)
        if d.status != "SUPERSEDED"
    ]
    design = max(designs, key=lambda d: d.revision)
    aircraft = db.aircraft[wo.aircraft_id]
    customer = db.customers[aircraft.customer_id]
    labor_quote_cents = int(
        rhu(D(str(wo.quoted_labor_hours)) * SHOP_RATE_CENTS_PER_HOUR, 0)
    )
    equipment_subtotal_cents = sum(
        line["quantity"] * line["unit_price_cents"] for line in design.equipment_list
    )
    discount = DISCOUNT_RATES[customer.customer_kind]
    discounted = int(
        rhu(Decimal(equipment_subtotal_cents) * (1 - discount), 0)
    )
    return labor_quote_cents + discounted


def labor_billing(task):
    """billed_labor_cents = round((regular + overtime * 1.5) * rate * kind_mult);
    rounded once per task at verify time (actual variant)."""
    hours = D(str(task.actual_hours))
    regular = min(hours, REGULAR_HOUR_CAP)
    overtime = max(Decimal(0), hours - REGULAR_HOUR_CAP)
    mult = TASK_KIND_MULTIPLIERS[task.task_kind]
    payable = regular + overtime * OVERTIME_MULTIPLIER
    return int(rhu(payable * SHOP_RATE_CENTS_PER_HOUR * mult, 0))


# ---------------------------------------------------------------------------
# Weight & balance (calculation: weight_balance_recompute; rounding order pinned
# per method)
# ---------------------------------------------------------------------------
def compute_weight_balance(wo, method, added_items, removed_weight_lb, removed_arm_in):
    aircraft = db.aircraft[wo.aircraft_id]

    if method == "INCREMENTAL":
        accepted = [
            r for r in children_of(db.wb_revisions, wo.id) if r.status == "ACCEPTED"
        ]
        if accepted:
            base = max(accepted, key=lambda r: r._seq)
            base_weight = D(str(base.new_empty_weight_lb))
            base_moment = D(str(base.new_moment_lb_in))
        else:
            base_weight = D(str(aircraft.baseline_empty_weight_lb))
            base_moment = D(str(aircraft.baseline_moment_lb_in))
        design_lines = []
    else:  # FULL_REWEIGH always rebuilds from the aircraft baseline
        base_weight = D(str(aircraft.baseline_empty_weight_lb))
        base_moment = D(str(aircraft.baseline_moment_lb_in))
        approved = [
            d for d in children_of(db.panel_designs, wo.id) if d.status == "APPROVED"
        ]
        design_lines = approved[0].equipment_list if approved else []

    # added_lines = manual added_items ++ design lines (design lines contribute
    # quantity * weight_lb at the line arm)
    lines = []
    for item in added_items:
        lines.append((D(str(item["weight_lb"])), D(str(item["arm_in"]))))
    for line in design_lines:
        lines.append(
            (D(line["quantity"]) * D(str(line["weight_lb"])), D(str(line["arm_in"])))
        )

    removed_w = D(str(removed_weight_lb))
    removed_moment = (
        removed_w * D(str(removed_arm_in)) if removed_arm_in is not None else Decimal(0)
    )

    if method == "INCREMENTAL":
        # Round each line moment to 0.1 BEFORE summing; removed moment rounded too.
        added_moment = sum((rhu(w * a, 1) for w, a in lines), Decimal(0))
        new_moment = rhu(base_moment + added_moment - rhu(removed_moment, 1), 1)
    else:
        # Sum unrounded, then round once.
        added_moment_raw = sum((w * a for w, a in lines), Decimal(0))
        new_moment = rhu(base_moment + added_moment_raw - removed_moment, 1)

    new_weight = rhu(
        base_weight + sum((w for w, _ in lines), Decimal(0)) - removed_w, 1
    )
    new_arm = rhu(new_moment / new_weight, 2) if new_weight != 0 else Decimal("0.00")
    cg_ok = (
        D(str(aircraft.cg_min_arm_in)) <= new_arm <= D(str(aircraft.cg_max_arm_in))
    )
    return {
        "new_empty_weight_lb": float(new_weight),
        "new_moment_lb_in": float(new_moment),
        "new_arm_in": float(new_arm),
        "cg_within_limits": bool(cg_ok),
    }


# ---------------------------------------------------------------------------
# Scheduling conflicts (PRD section 2.6, half-open intervals)
# ---------------------------------------------------------------------------
def bay_window_conflict(bay_code, start, end, exclude_id=None):
    for w in db.work_orders.values():
        if w.id == exclude_id or w.bay_code != bay_code:
            continue
        if w.status in WO_TERMINAL:
            continue
        if start < w.bay_window_end and end > w.bay_window_start:
            return True
    return False


def flight_window_conflict(aircraft_id, start, end, exclude_id=None):
    """The new (unbuffered) window must not intersect the [start-60m, end+60m)
    buffered window of any other SCHEDULED/FAILED flight on the same aircraft."""
    for e in db.test_events.values():
        if e.id == exclude_id or e.test_kind != "FLIGHT":
            continue
        if e.status not in ("SCHEDULED", "FAILED"):
            continue
        other_wo = db.work_orders[e.work_order_id]
        if other_wo.aircraft_id != aircraft_id:
            continue
        buf_start = e.scheduled_start - FLIGHT_BUFFER
        buf_end = e.scheduled_end + FLIGHT_BUFFER
        if start < buf_end and end > buf_start:
            return True
    return False
