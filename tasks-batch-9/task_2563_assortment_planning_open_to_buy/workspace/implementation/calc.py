"""Calculation rules (§3 of the PRD / 1.3 of the scaffold).

Every rounding step happens exactly where the formula names it.  All money is
integer cents; all rates are integer basis points.
"""
from datetime import timedelta

from common import fail, rhu, retail_to_cost, trunc
import store
from store import db

# --- constants -------------------------------------------------------------
ROLE_RECEIPT_MULTIPLIER_BPS = {
    "TRAFFIC_DRIVER": 11000,
    "DESTINATION": 10000,
    "CONVENIENCE": 9000,
    "SEASONAL": 12500,
    "OCCASIONAL": 8500,
}
DEPARTMENT_SHARE_CAP_BPS = 1200
TURN_TARGET_REFERENCE_X100 = 300
TURN_FLOOR_X100 = 200

RESERVE_TIER_LOW_BPS = 4000
RESERVE_TIER_MID_BPS = 6500
RESERVE_TIER_HIGH_BPS = 8500
RESERVE_RATE_DEEP_BPS = 900
RESERVE_RATE_MID_BPS = 600
RESERVE_RATE_LIGHT_BPS = 350
RESERVE_RATE_MIN_BPS = 150

WEEKS_PER_FISCAL_MONTH = 4

TIER_BREADTH_SHARE_BPS = {"GOOD": 4500, "BETTER": 3500, "BEST": 2000}
MIN_SLOTS_PER_TIER = 2

TIER_BENCHMARK_BPS = {"GOOD": 6200, "BETTER": 5500, "BEST": 4300}
SELL_THROUGH_CAP_BPS = 9800

OVERLAY_MULTIPLIER_FLOOR_BPS = 5000
OVERLAY_MULTIPLIER_CEILING_BPS = 15000
OVERLAY_ORDER = ["CLIMATE", "DEMOGRAPHIC", "VOLUME"]
OVERLAY_BUFFER_DAYS = 7

POSTURE_OPEN_FLOOR_BPS = 1500
POSTURE_RESTRICTED_FLOOR_BPS = 500

VARIANCE_BREACH_UNDER_BPS = -1000
VARIANCE_WATCH_UNDER_BPS = -400
VARIANCE_BREACH_OVER_BPS = 1500

CHASE_WINDOW_DAYS = 14
REFORECAST_ROUND_CAP = 3

PLANNED_BASIS = "PLANNED_BASIS"
PROJECTED_BASIS = "PROJECTED_BASIS"


# ---------------------------------------------------------------------------
# plan_receipt_budget (§3.4)
# ---------------------------------------------------------------------------
def plan_receipt_budget(plan):
    category = store.plan_category(plan)
    department = db.departments.get(category["department_id"]) if category else None
    cost_of_goods = retail_to_cost(plan["planned_sales_cents"], plan["planned_margin_bps"])
    role_capacity = rhu(cost_of_goods * ROLE_RECEIPT_MULTIPLIER_BPS[category["role"]], 10000)
    turn_basis = max(plan["planned_turn_x100"], TURN_FLOOR_X100)
    turn_capacity = rhu(cost_of_goods * TURN_TARGET_REFERENCE_X100, turn_basis)
    dept_cap = rhu(department["sales_target_cents"] * DEPARTMENT_SHARE_CAP_BPS, 10000)
    return min(dept_cap, max(role_capacity, turn_capacity))


# ---------------------------------------------------------------------------
# Commitment-derived sums for one month
# ---------------------------------------------------------------------------
def month_committed_receipt_cost(month_id):
    """S1 input: open + received cost over COMMITTED and CLOSED rows only."""
    total = 0
    for rc in store.month_commitments(month_id):
        if rc["commit_status"] in ("COMMITTED", "CLOSED"):
            total += rc["open_cost_cents"] + rc["received_cost_cents"]
    return total


def month_buckets(month_id):
    committed = 0
    received = 0
    for rc in store.month_commitments(month_id):
        if rc["commit_status"] == "COMMITTED":
            committed += rc["open_cost_cents"]
        # §3.4 names COMMITTED and CLOSED and says cancelled rows "contribute
        # nothing to either, because their open cost is zero and their received
        # cost counts only units genuinely received" -- a rationale that holds
        # only while nothing was received.  §3.6 cascade A link 2 governs the
        # partially received case directly: cancelling "drops the month's
        # otb_committed_cents by the released amount and raises the month's
        # otb_open_cents by that same amount", the released amount being the
        # open cost link 1 zeroed.  Dollars for units genuinely received are not
        # released, so they stay in the received bucket on a CANCELLED row.
        if rc["commit_status"] in ("COMMITTED", "CLOSED", "CANCELLED"):
            received += rc["received_cost_cents"]
    return committed, received


# ---------------------------------------------------------------------------
# PROJECTED_BASIS walk P1..P4 (§3.7)
# ---------------------------------------------------------------------------
def projected_figures(month, plan):
    rows = store.month_actuals(month["id"])
    weeks_posted = len(rows)
    actual_sales = sum(a["actual_sales_cents"] for a in rows)
    actual_receipts = sum(a["actual_receipts_cents"] for a in rows)
    if weeks_posted > 0:
        # run rate kept as an exact rational and NOT rounded
        unposted = WEEKS_PER_FISCAL_MONTH - weeks_posted
        projected_sales = rhu(actual_sales * weeks_posted + actual_sales * unposted,
                              weeks_posted)
        projected_sales_cost = retail_to_cost(projected_sales, plan["planned_margin_bps"])
    else:
        projected_sales = 0
        projected_sales_cost = 0
    actual_sales_cost = retail_to_cost(actual_sales, plan["planned_margin_bps"])
    projected_bom = month["bom_inventory_cents"] + actual_receipts - actual_sales_cost
    return {
        "weeks_posted": weeks_posted,
        "actual_sales_cents": actual_sales,
        "actual_receipts_cents": actual_receipts,
        "projected_sales_cents": projected_sales,
        "projected_sales_cost_cents": projected_sales_cost,
        "actual_sales_cost_cents": actual_sales_cost,
        "projected_bom_cents": projected_bom,
    }


# ---------------------------------------------------------------------------
# markdown_reserve (§3.4) — single pass, never iterated to a fixed point
# ---------------------------------------------------------------------------
def markdown_reserve(month, plan, basis, projected=None):
    if basis == PLANNED_BASIS:
        sales_cost = retail_to_cost(month["planned_sales_cents"], plan["planned_margin_bps"])
        inventory_base = month["bom_inventory_cents"]
    else:
        if projected is None:
            projected = projected_figures(month, plan)
        sales_cost = projected["projected_sales_cost_cents"]
        inventory_base = projected["projected_bom_cents"]
    committed_receipt_cost = month_committed_receipt_cost(month["id"])
    denominator = max(1, inventory_base + committed_receipt_cost)
    provisional = rhu(10000 * sales_cost, denominator)
    if provisional < RESERVE_TIER_LOW_BPS:
        rate = RESERVE_RATE_DEEP_BPS
    elif provisional < RESERVE_TIER_MID_BPS:
        rate = RESERVE_RATE_MID_BPS
    elif provisional < RESERVE_TIER_HIGH_BPS:
        rate = RESERVE_RATE_LIGHT_BPS
    else:
        rate = RESERVE_RATE_MIN_BPS
    reserve = rhu(denominator * rate, 10000)
    return {
        "provisional_sell_through_bps": provisional,
        "reserve_rate_bps": rate,
        "markdown_reserve_cents": reserve,
        "denominator_cents": denominator,
        "sales_cost_cents": sales_cost,
        "inventory_base_cents": inventory_base,
    }


# ---------------------------------------------------------------------------
# plan_month_open_to_buy (§3.4 / §3.7)
# ---------------------------------------------------------------------------
def otb_planned(month, plan, basis, reserve_cents, projected=None):
    if basis == PLANNED_BASIS:
        planned_sales_cost = retail_to_cost(month["planned_sales_cents"],
                                            plan["planned_margin_bps"])
        return (planned_sales_cost + month["planned_eom_cents"]
                + month["planned_markdown_cents"] + reserve_cents
                - month["bom_inventory_cents"])
    if projected is None:
        projected = projected_figures(month, plan)
    return (projected["projected_sales_cost_cents"] + month["planned_eom_cents"]
            + month["planned_markdown_cents"] + reserve_cents
            - projected["projected_bom_cents"])


def evaluate_month(month, plan, basis):
    """Full non-persisting evaluation of one month under an explicit basis."""
    projected = projected_figures(month, plan)
    reserve = markdown_reserve(month, plan, basis, projected)
    planned = otb_planned(month, plan, basis, reserve["markdown_reserve_cents"], projected)
    committed, received = month_buckets(month["id"])
    return {
        "plan_month_id": month["id"],
        "basis": basis,
        "bom_inventory_cents": month["bom_inventory_cents"],
        "projected_bom_cents": projected["projected_bom_cents"],
        "planned_sales_cost_cents": retail_to_cost(month["planned_sales_cents"],
                                                   plan["planned_margin_bps"]),
        "projected_sales_cost_cents": projected["projected_sales_cost_cents"],
        "provisional_sell_through_bps": reserve["provisional_sell_through_bps"],
        "reserve_rate_bps": reserve["reserve_rate_bps"],
        "markdown_reserve_cents": reserve["markdown_reserve_cents"],
        "otb_planned_cents": planned,
        "otb_committed_cents": committed,
        "otb_received_cents": received,
        "otb_open_cents": planned - committed - received,
        "weeks_posted": projected["weeks_posted"],
    }


# ---------------------------------------------------------------------------
# option_slot_capacity (§3.4 link 4)
# ---------------------------------------------------------------------------
def option_slot_capacity(cell, plan, cluster):
    tier_share = rhu(plan["receipt_budget_cents"] * TIER_BREADTH_SHARE_BPS[cell["tier"]], 10000)
    budget_share = rhu(tier_share * cluster["sales_index_bps"], 10000)
    cost_per_option = (cell["depth_units_per_option"] * cluster["store_count"]
                       * cell["assumed_unit_cost_cents"])
    affordable = trunc(budget_share, cost_per_option)
    total = max(MIN_SLOTS_PER_TIER, min(cell["breadth_target"], affordable))
    return total


# ---------------------------------------------------------------------------
# cluster_size_allocation (§3.3)
# ---------------------------------------------------------------------------
def cluster_size_allocation(cell, cluster, size_cells):
    """Returns (target_units, [(size_cell, raw_units_x10000, allocated_units), ...])."""
    depth = cell["depth_units_per_option"]
    stores = cluster["store_count"]
    index = cluster["sales_index_bps"]
    target_units = rhu(depth * stores * index, 10000)
    rows = []
    for s in size_cells:
        raw = rhu(depth * stores * index * s["pct_bps"], 10000)
        allocated = rhu(raw, 10000)
        rows.append({"cell": s, "raw": raw, "allocated": allocated,
                     "frac": raw % 10000, "sort": s["size_sort_order"]})
    delta = target_units - sum(r["allocated"] for r in rows)
    if delta != 0 and rows:
        if delta < 0:
            order = sorted(rows, key=lambda r: (r["frac"], r["sort"]))
            step = -1
        else:
            order = sorted(rows, key=lambda r: (-r["frac"], r["sort"]))
            step = 1
        remaining = abs(delta)
        idx = 0
        while remaining > 0:
            order[idx % len(order)]["allocated"] += step
            idx += 1
            remaining -= 1
    return target_units, rows


# ---------------------------------------------------------------------------
# overlay_effective_multiplier (§3.5)
# ---------------------------------------------------------------------------
def applicable_overlays(plan_id, cluster_id):
    now = store.clock()
    found = {}
    for o in store.plan_overlays(plan_id):
        if o["store_cluster_id"] != cluster_id or o["status"] != "ACTIVE":
            continue
        start = store.dt(o["effective_start"])
        end = store.dt(o["effective_end"])
        if start is not None and end is not None and start <= now <= end:
            found.setdefault(o["overlay_type"], o)
    return found


def overlay_effective_multiplier(item):
    cell = db.optionplans.get(item["option_plan_id"])
    if cell is None:
        return 10000
    found = applicable_overlays(cell["category_plan_id"], cell["store_cluster_id"])
    effective = 10000
    for overlay_type in OVERLAY_ORDER:
        overlay = found.get(overlay_type)
        if overlay is not None:
            effective = rhu(effective * overlay["unit_multiplier_bps"], 10000)
    return min(OVERLAY_MULTIPLIER_CEILING_BPS,
               max(OVERLAY_MULTIPLIER_FLOOR_BPS, effective))


# ---------------------------------------------------------------------------
# item_sell_through_forecast (§3.5)
# ---------------------------------------------------------------------------
def item_sell_through_forecast(item):
    cell = db.optionplans.get(item["option_plan_id"])
    cluster = db.clusters.get(cell["store_cluster_id"]) if cell else None
    multiplier = item["effective_overlay_multiplier_bps"]
    if item["lifecycle_stage"] == "NEW":
        value = rhu(TIER_BENCHMARK_BPS[cell["tier"]] * cluster["sales_index_bps"] * multiplier,
                    100000000)
        return "NEW_ITEM_BASIS", min(SELL_THROUGH_CAP_BPS, value)
    value = rhu((item.get("prior_season_sell_through_bps") or 0)
                * cluster["demographic_index_bps"], 10000)
    return "CARRYOVER_BASIS", min(SELL_THROUGH_CAP_BPS, value)


# ---------------------------------------------------------------------------
# otb_posture (§3.4 link 3)
# ---------------------------------------------------------------------------
def posture_month_set(plan_id):
    return [m for m in store.plan_months(plan_id)
            if m["status"] in ("LOCKED_PLAN", "IN_SEASON")]


def compute_posture(plan, open_sum=None, planned_sum=None, month_count=None):
    """Returns (open_ratio_bps, otb_posture) per §3.4 link 3."""
    if month_count is None:
        months = posture_month_set(plan["id"])
        month_count = len(months)
        open_sum = sum(m["otb_open_cents"] for m in months)
        planned_sum = sum(m["otb_planned_cents"] for m in months)
    if not month_count:
        ratio = 10000
        posture = "OPEN"
    else:
        ratio = rhu(10000 * open_sum, max(1, planned_sum))
        if ratio >= POSTURE_OPEN_FLOOR_BPS:
            posture = "OPEN"
        elif ratio >= POSTURE_RESTRICTED_FLOOR_BPS:
            posture = "RESTRICTED"
        else:
            posture = "FROZEN"
    if plan["variance_status"] == "BREACH":
        posture = "FROZEN"
    return ratio, posture


# ---------------------------------------------------------------------------
# variance_verdict (§3.7)
# ---------------------------------------------------------------------------
def variance_verdict(plan):
    months = [m for m in store.plan_months(plan["id"])
              if m["status"] in ("IN_SEASON", "CLOSED")]
    actual_sales = 0
    plan_to_date = 0
    for m in months:
        rows = store.month_actuals(m["id"])
        actual_sales += sum(a["actual_sales_cents"] for a in rows)
        weeks = min(WEEKS_PER_FISCAL_MONTH, len(rows))
        plan_to_date += rhu(m["planned_sales_cents"] * weeks, WEEKS_PER_FISCAL_MONTH)
    variance = rhu(10000 * (actual_sales - plan_to_date), max(1, plan_to_date))
    if variance <= VARIANCE_BREACH_UNDER_BPS:
        status = "BREACH"
    elif variance <= VARIANCE_WATCH_UNDER_BPS:
        status = "WATCH"
    elif variance >= VARIANCE_BREACH_OVER_BPS:
        status = "BREACH"
    else:
        status = "ON_PLAN"
    return variance, status


# ---------------------------------------------------------------------------
# vendor_window_load (§3.2)
# ---------------------------------------------------------------------------
def window_load(vendor_id, start, end, exclude_id=None):
    """Aggregate open units of PROPOSED/COMMITTED rows whose window overlaps."""
    total = 0
    for rc in store.by_seq(list(db.commitments.values())):
        if rc["vendor_id"] != vendor_id or rc["id"] == exclude_id:
            continue
        if rc["commit_status"] not in ("PROPOSED", "COMMITTED"):
            continue
        rc_start = store.dt(rc["ship_window_start"])
        rc_end = store.dt(rc["ship_window_end"])
        if rc_start is None or rc_end is None:
            continue
        if rc_start < end and start < rc_end:
            total += rc["units"] - rc["cancelled_units"]
    return total


def category_open_units(vendor_id, category_id, exclude_id=None):
    total = 0
    for rc in store.by_seq(list(db.commitments.values())):
        if rc["vendor_id"] != vendor_id or rc["id"] == exclude_id:
            continue
        if rc["commit_status"] not in ("PROPOSED", "COMMITTED"):
            continue
        month = db.months.get(rc["plan_month_id"])
        if month is None:
            continue
        plan = store.month_plan(month)
        if plan is None or plan["category_id"] != category_id:
            continue
        total += rc["units"] - rc["received_units"] - rc["cancelled_units"]
    return total


def check_vendor_capacity(vendor, authorization, candidate_units,
                          window_start, window_end, category_id, exclude_id=None):
    loaded = window_load(vendor["id"], window_start, window_end, exclude_id)
    if loaded + candidate_units > vendor["weekly_unit_capacity"]:
        fail("ERR_VENDOR_CAPACITY_EXCEEDED",
             "overlapping ship-window load exceeds the vendor's weekly unit capacity")
    open_units = category_open_units(vendor["id"], category_id, exclude_id)
    if open_units + candidate_units > authorization["max_open_units"]:
        fail("ERR_VENDOR_CAPACITY_EXCEEDED",
             "vendor open units for the category exceed the authorization ceiling")


def active_authorization(vendor_id, category_id):
    for a in store.by_seq(list(db.vauths.values())):
        if (a["vendor_id"] == vendor_id and a["category_id"] == category_id
                and a["status"] == "ACTIVE"):
            return a
    return None


def days(n):
    return timedelta(days=n)
