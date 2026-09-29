"""Conserved rollups (PRD 2.10).

Every rollup is a sum or a count over a filtered set, never an accumulator, so a
create-then-reverse pair leaves the books byte-identical.  Every recomputation
touches its row: updated_at moves and version increments.
"""
from db import db, touch, now_iso, clock_now


def units_of_model(model_id):
    return [u for u in db.units.values() if u["model_id"] == model_id]


def reservations_of_jig(jig_id):
    return [r for r in db.reservations.values() if r["jig_id"] == jig_id]


def reservations_of_unit(unit_id):
    return [r for r in db.reservations.values() if r["unit_id"] == unit_id]


def inspections_of_unit(unit_id):
    return [i for i in db.inspections.values() if i["unit_id"] == unit_id]


def options_of_unit(unit_id):
    return [o for o in db.options.values() if o["unit_id"] == unit_id]


def road_tests_of_unit(unit_id):
    return [t for t in db.road_tests.values() if t["unit_id"] == unit_id]


def road_tests_of_lane(lane_id):
    return [t for t in db.road_tests.values() if t["lane_id"] == lane_id]


def labels_of_unit(unit_id):
    return [l for l in db.labels.values() if l["unit_id"] == unit_id]


def orders_of_dealer(dealer_id):
    return [o for o in db.orders.values() if o["dealer_id"] == dealer_id]


def claims_of_dealer(dealer_id):
    return [c for c in db.claims.values() if c["dealer_id"] == dealer_id]


def issued_label(unit_id):
    for label in labels_of_unit(unit_id):
        if label["status"] == "ISSUED":
            return label
    return None


def recompute_model_active_unit_count(model):
    if model is None:
        return
    count = 0
    for unit in units_of_model(model["id"]):
        if unit["build_status"] not in ("SHIPPED", "SCRAPPED"):
            count += 1
    model["active_unit_count"] = count
    return count


def recompute_jig_minutes(jig):
    if jig is None:
        return
    total = 0
    for res in reservations_of_jig(jig["id"]):
        if res["status"] in ("RESERVED", "CONSUMED"):
            total += res["duration_minutes"]
    jig["reserved_minutes_total"] = total
    touch(jig)


def allocation_counts(dealer):
    """PRD 3.8: both counters count only ALLOCATED or DELIVERED orders whose
    `allocated_at` falls inside the logical clock's *current* UTC calendar month
    and calendar year, so they must be evaluated live — a clock move across a
    month boundary restarts the month counter while the year counter carries."""
    now = clock_now()
    month_count = 0
    year_count = 0
    for order in orders_of_dealer(dealer["id"]):
        if order["status"] not in ("ALLOCATED", "DELIVERED"):
            continue
        allocated = order.get("_allocated_at_dt")
        if allocated is None:
            continue
        if allocated.year == now.year:
            year_count += 1
            if allocated.month == now.month:
                month_count += 1
    return month_count, year_count


def recompute_dealer(dealer):
    """floor plan, allocation counters and warranty receivable, all as filtered sums."""
    if dealer is None:
        return
    orders = orders_of_dealer(dealer["id"])
    outstanding = 0
    for order in orders:
        if order["floor_plan_status"] == "DRAWN":
            outstanding += order["floor_plan_draw_cents"] or 0
    dealer["floor_plan_outstanding_cents"] = outstanding
    dealer["floor_plan_available_cents"] = dealer["floor_plan_limit_cents"] - outstanding

    month_count, year_count = allocation_counts(dealer)
    dealer["allocations_current_month_count"] = month_count
    dealer["allocations_ytd_count"] = year_count

    receivable = 0
    for claim in claims_of_dealer(dealer["id"]):
        if claim["status"] == "CLOSED":
            receivable += claim["reimbursement_total_cents"] or 0
    dealer["warranty_receivable_cents"] = receivable
    touch(dealer)


def recompute_unit_weights(unit):
    """curb_weight_lbs + payload_capacity_lbs == pinned gvwr_lbs, always."""
    if unit is None or unit.get("gvwr_lbs") is None:
        return
    model = db.models.get(unit["model_id"])
    options_weight = 0
    for line in options_of_unit(unit["id"]):
        if line["status"] in ("PENDING", "COMPLETED"):
            options_weight += line["total_weight_lbs"]
    curb = model["base_curb_weight_lbs"] + options_weight
    unit["curb_weight_lbs"] = curb
    unit["payload_capacity_lbs"] = unit["gvwr_lbs"] - curb
    touch(unit)


def recompute_frame_fail_count(unit):
    count = 0
    for inspection in inspections_of_unit(unit["id"]):
        if inspection["result"] == "FAIL":
            count += 1
    unit["frame_fail_count"] = count
    return count


def recompute_rework_cycle_count(unit):
    count = 0
    for test in road_tests_of_unit(unit["id"]):
        if test["status"] == "FAILED":
            count += 1
    unit["rework_cycle_count"] = count
    return count


def pending_option_count(unit_id):
    count = 0
    for line in options_of_unit(unit_id):
        if line["status"] == "PENDING":
            count += 1
    return count


def maybe_release_to_stock(unit):
    """PRD 3.5: a LABELED unit releases itself once no PENDING option line remains."""
    if unit["build_status"] != "LABELED":
        return False
    if pending_option_count(unit["id"]) != 0:
        return False
    unit["build_status"] = "RELEASED_TO_STOCK"
    unit["released_to_stock_at"] = now_iso()
    unit["_released_to_stock_dt"] = clock_now()
    touch(unit)
    return True
