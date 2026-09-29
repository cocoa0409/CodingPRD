"""Derived-field recomputation, invariants and version reconciliation.

Every computed field in the model is rebuilt from the authoritative rows by
recompute_all(); PRD 2.5 says a change to a derived field is itself a mutation,
so commit() bumps updated_at/version on exactly the rows whose derived state
moved during the request (unioned with the rows the handler explicitly marked).
"""
from decimal import Decimal

import clock
from constants import (
    CAPACITY_REFERENCE_UNITS, CAPACITY_WEIGHT, COLD_START_PERFORMANCE_RATIO,
    COST_DISADVANTAGE_BPS, CYCLE_TIME_CEILING, CYCLE_TIME_FLOOR,
    DC_BASE_CENTS_BY_ZONE, DC_PER_UNIT_CENTS, GOVERNANCE_CURRENT_WEIGHT,
    GOVERNANCE_PRIOR_WEIGHT, LABOR_REFERENCE_MINUTES, LABOR_WEIGHT,
    LIVE_STATUSES, MAX_AVG_CYCLE_TIME_MINUTES, MAX_CANCELLATION_RATE,
    MAX_REROUTE_ATTEMPTS, MIN_FILL_RATE, PERFORMANCE_WEIGHT, RELEASED_STATUSES,
)
from db import db, new_row, touch
from services.costs import order_cost_breakdown
from util import D, clamp01, div, n2, n4, rhu, rhu_int

# ------------------------------------------------------------------ lookups


def order_lines_of(order_id):
    return sorted([l for l in db.order_lines.values() if l["order_id"] == order_id],
                  key=lambda r: r["_seq"])


def assignments_of_order(order_id):
    return sorted([a for a in db.assignments.values() if a["order_id"] == order_id],
                  key=lambda r: r["_seq"])


def assignment_lines_of(assignment_id):
    return sorted([al for al in db.assignment_lines.values()
                   if al["assignment_id"] == assignment_id],
                  key=lambda r: r["_seq"])


def runs_of_order(order_id):
    return sorted([r for r in db.routing_runs.values() if r["order_id"] == order_id],
                  key=lambda r: r["_seq"])


def open_window(store_id):
    for window in sorted(db.windows.values(), key=lambda r: r["_seq"]):
        if window["store_id"] == store_id and window["status"] == "OPEN":
            return window
    return None


def closed_windows_desc(store_id):
    return sorted([w for w in db.windows.values()
                   if w["store_id"] == store_id and w["status"] == "CLOSED"],
                  key=lambda w: (-w["epoch"], -w["_seq"]))


def windows_of(store_id):
    return [w for w in db.windows.values() if w["store_id"] == store_id]


def network_epoch():
    """Highest epoch across all existing windows, or 1 when none exists."""
    epochs = [w["epoch"] for w in db.windows.values()]
    return max(epochs) if epochs else 1


def inventory_for(store_id, sku_id):
    for inv in db.inventories.values():
        if inv["store_id"] == store_id and inv["sku_id"] == sku_id:
            return inv
    return None


def packaging_for(store_id, package_type):
    for pkg in db.packaging.values():
        if pkg["store_id"] == store_id and pkg["package_type"] == package_type:
            return pkg
    return None


def create_window(store, epoch):
    return new_row("windows", {
        "store_id": store["id"],
        "epoch": epoch,
        "status": "OPEN",
        "opened_at_utc": clock.now(),
        "closed_at_utc": None,
        "assignments_created": 0,
        "assignments_shipped": 0,
        "assignments_rejected": 0,
        "assignments_cancelled": 0,
        "units_promised": 0,
        "units_shipped": 0,
        "fill_rate": 1.0,
        "avg_cycle_time_minutes": 0.0,
        "cancellation_rate": 0.0,
        "breach_flags": [],
        "breached": False,
        "store_cost_per_order_cents": 0,
        "dc_cost_per_order_cents": 0,
        "cost_index_bps": 0,
        "cost_disadvantaged": False,
        "node_action": "NONE",
    })


# ------------------------------------------------------------------ line status


def line_status(line):
    """Pinned precedence for OrderLine.line_status (PRD 3.2)."""
    resolved = line["open_units"] == 0
    if resolved and line["assigned_units"] == 0 and line["shipped_units"] == 0:
        if line["cancelled_units"] > 0:
            return "CANCELLED"
        if line["dc_fallback_units"] > 0:
            return "DC_FALLBACK"
    if resolved and line["assigned_units"] == 0 and line["shipped_units"] > 0:
        return "SHIPPED"
    if resolved and line["assigned_units"] > 0:
        return "FULLY_ASSIGNED"
    if line["assigned_units"] > 0 or line["shipped_units"] > 0:
        return "PARTIALLY_ASSIGNED"
    return "OPEN"


# ------------------------------------------------------------------ window metrics


def apply_window_metrics(window):
    """calculations.node_performance_metrics -- everything but node_action."""
    members = [a for a in db.assignments.values()
               if a["store_id"] == window["store_id"] and a["epoch"] == window["epoch"]]
    shipped = [a for a in members if a["status"] == "SHIPPED"]
    created = len(members)
    rejected = sum(1 for a in members if a["status"] == "REJECTED")
    cancelled = sum(1 for a in members if a["status"] == "CANCELLED")
    units_promised = sum(a["assigned_units"] for a in members)
    units_shipped = sum(a["picked_units"] for a in shipped)

    window["assignments_created"] = created
    window["assignments_shipped"] = len(shipped)
    window["assignments_rejected"] = rejected
    window["assignments_cancelled"] = cancelled
    window["units_promised"] = units_promised
    window["units_shipped"] = units_shipped

    window["fill_rate"] = 1.0 if units_promised == 0 else n4(div(units_shipped, units_promised))
    if not shipped:
        window["avg_cycle_time_minutes"] = 0.0
    else:
        total = sum(a["cycle_time_minutes"] or 0 for a in shipped)
        window["avg_cycle_time_minutes"] = n2(div(total, len(shipped)))
    window["cancellation_rate"] = (0.0 if created == 0
                                   else n4(div(rejected + cancelled, created)))

    flags = []
    if len(shipped) >= 1 and D(window["fill_rate"]) < D(MIN_FILL_RATE):
        flags.append("FILL_RATE")
    if len(shipped) >= 1 and D(window["avg_cycle_time_minutes"]) > D(MAX_AVG_CYCLE_TIME_MINUTES):
        flags.append("CYCLE_TIME")
    if created >= 1 and D(window["cancellation_rate"]) > D(MAX_CANCELLATION_RATE):
        flags.append("CANCELLATION_RATE")
    window["breach_flags"] = flags
    window["breached"] = len(flags) > 0

    if not shipped:
        window["store_cost_per_order_cents"] = 0
        window["dc_cost_per_order_cents"] = 0
    else:
        store_total = sum(a["final_cost_cents"] or 0 for a in shipped)
        window["store_cost_per_order_cents"] = rhu_int(div(store_total, len(shipped)))
        dc_total = 0
        for a in shipped:
            order = db.orders[a["order_id"]]
            dc_total += (DC_BASE_CENTS_BY_ZONE[order["destination_zone"]]
                         + DC_PER_UNIT_CENTS * a["picked_units"])
        window["dc_cost_per_order_cents"] = rhu_int(div(dc_total, len(shipped)))
    if window["dc_cost_per_order_cents"] == 0:
        window["cost_index_bps"] = 0
    else:
        window["cost_index_bps"] = rhu_int(
            div(window["store_cost_per_order_cents"] * 10000,
                window["dc_cost_per_order_cents"]))
    window["cost_disadvantaged"] = window["cost_index_bps"] > COST_DISADVANTAGE_BPS


# ------------------------------------------------------------------ scoring


def performance_ratio(window):
    cycle_factor = rhu(clamp01(div(D(CYCLE_TIME_CEILING) - D(window["avg_cycle_time_minutes"]),
                                   D(CYCLE_TIME_CEILING) - D(CYCLE_TIME_FLOOR))), 4)
    return (D("0.5") * D(window["fill_rate"])
            + D("0.3") * (Decimal(1) - D(window["cancellation_rate"]))
            + D("0.2") * cycle_factor)


def eligibility_score(store, variant="routing", closing_window=None):
    """calculations.store_eligibility_score. Returns (score, basis_or_None)."""
    capacity_headroom = max(0, store["daily_unit_capacity"] - store["units_committed_epoch"])
    capacity_component = rhu(D(CAPACITY_WEIGHT) * min(
        Decimal(1), div(capacity_headroom, CAPACITY_REFERENCE_UNITS)), 4)

    labor_headroom = D(store["staffed_labor_minutes"]) - D(store["reserved_labor_minutes"])
    if labor_headroom < 0:
        labor_headroom = Decimal(0)
    labor_component = rhu(D(LABOR_WEIGHT) * min(
        Decimal(1), div(labor_headroom, LABOR_REFERENCE_MINUTES)), 4)

    closed = closed_windows_desc(store["id"])
    if variant == "governance":
        ratio = performance_ratio(closing_window)
        if closed:
            ratio = (D(GOVERNANCE_CURRENT_WEIGHT) * ratio
                     + D(GOVERNANCE_PRIOR_WEIGHT) * performance_ratio(closed[0]))
        basis = None
    elif closed:
        ratio = performance_ratio(closed[0])
        basis = "TRAILING_WINDOW"
    else:
        ratio = D(COLD_START_PERFORMANCE_RATIO)
        basis = "COLD_START"

    performance_component = rhu(D(PERFORMANCE_WEIGHT) * ratio, 4)
    score = n2(capacity_component + labor_component + performance_component)
    return score, basis


# ------------------------------------------------------------------ order costs


def order_cost(order, variant):
    """PRD 3.8. variant is 'provisional' or 'final'."""
    assignments = assignments_of_order(order["id"])
    if variant == "final":
        included = [a for a in assignments if a["status"] == "SHIPPED"]
        components = [a["final_cost_cents"] or 0 for a in included]
        label = "FINAL"
    else:
        included = [a for a in assignments if a["status"] not in RELEASED_STATUSES]
        components = [a["provisional_cost_cents"] for a in included]
        label = "PROVISIONAL"
    return order_cost_breakdown(order, components, len(included),
                                order["reroute_attempt_count"], variant=label)


# ------------------------------------------------------------------ recompute


def recompute_all(skip_windows=False):
    lines_by_order_line = {}
    lines_by_assignment = {}
    for al in db.assignment_lines.values():
        lines_by_order_line.setdefault(al["order_line_id"], []).append(al)
        lines_by_assignment.setdefault(al["assignment_id"], []).append(al)

    # --- OrderLine derived quantities (PRD 2.9 conservation invariant)
    for line in db.order_lines.values():
        assigned = 0
        shipped = 0
        for al in lines_by_order_line.get(line["id"], []):
            assignment = db.assignments[al["assignment_id"]]
            if assignment["status"] in LIVE_STATUSES:
                assigned += al["units_assigned"] - al["units_cancelled"]
            elif assignment["status"] == "SHIPPED":
                shipped += al["units_picked"]
        line["assigned_units"] = assigned
        line["shipped_units"] = shipped
        line["open_units"] = (line["quantity"] - assigned - shipped
                              - line["cancelled_units"] - line["dc_fallback_units"])
        line["line_status"] = line_status(line)

    # --- StoreInventory reservations / ATP
    reserved_by_key = {}
    for al in db.assignment_lines.values():
        assignment = db.assignments[al["assignment_id"]]
        if assignment["status"] not in LIVE_STATUSES:
            continue
        sku_id = db.order_lines[al["order_line_id"]]["sku_id"]
        key = (assignment["store_id"], sku_id)
        reserved_by_key[key] = (reserved_by_key.get(key, 0)
                                + al["units_assigned"] - al["units_cancelled"])
    for inv in db.inventories.values():
        reserved = reserved_by_key.get((inv["store_id"], inv["sku_id"]), 0)
        inv["reserved_units"] = reserved
        inv["available_to_promise_units"] = max(
            0, inv["on_hand_units"] - reserved - inv["safety_stock_units"])

    # --- PackagingSupply reorder flag
    for pkg in db.packaging.values():
        pkg["reorder_flag"] = pkg["on_hand_units"] <= pkg["reorder_point_units"]

    # --- CarrierPickup parcel usage
    parcels = {}
    for a in db.assignments.values():
        if a["status"] == "SHIPPED" and a.get("carrier_pickup_id"):
            parcels[a["carrier_pickup_id"]] = parcels.get(a["carrier_pickup_id"], 0) + 1
    for pickup in db.pickups.values():
        pickup["reserved_parcels"] = parcels.get(pickup["id"], 0)

    # --- Store counters
    for store in db.stores.values():
        window = open_window(store["id"])
        committed = 0
        if window is not None:
            for a in db.assignments.values():
                if a["store_id"] != store["id"] or a["epoch"] != window["epoch"]:
                    continue
                if a["status"] in RELEASED_STATUSES:
                    continue
                released = sum(al["units_cancelled"]
                               for al in lines_by_assignment.get(a["id"], []))
                committed += a["assigned_units"] - released
        store["units_committed_epoch"] = committed
        reserved_labor = Decimal(0)
        for a in db.assignments.values():
            if a["store_id"] == store["id"] and a["status"] in LIVE_STATUSES:
                reserved_labor += D(a["labor_minutes_reserved"])
        store["reserved_labor_minutes"] = n2(reserved_labor)

    # --- OPEN performance window metrics (closed windows stay frozen)
    if not skip_windows:
        for window in db.windows.values():
            if window["status"] == "OPEN":
                apply_window_metrics(window)

    # --- Store eligibility score
    for store in db.stores.values():
        score, basis = eligibility_score(store)
        store["eligibility_score"] = score
        store["eligibility_score_basis"] = basis

    # --- CustomerOrder rollups
    for order in db.orders.values():
        recompute_order(order)


def recompute_order(order):
    lines = order_lines_of(order["id"])
    order["total_units"] = sum(l["quantity"] for l in lines)
    order["shipped_units"] = sum(l["shipped_units"] for l in lines)
    order["unassigned_units"] = sum(l["open_units"] for l in lines)
    order["dc_fallback_units"] = sum(l["dc_fallback_units"] for l in lines)
    cancelled_units = sum(l["cancelled_units"] for l in lines)
    covered_units = sum(l["assigned_units"] + l["shipped_units"] for l in lines)

    assignments = assignments_of_order(order["id"])
    order["split_count"] = sum(1 for a in assignments
                               if a["status"] not in RELEASED_STATUSES)
    runs = runs_of_order(order["id"])
    order["reroute_attempt_count"] = sum(
        1 for r in runs if r["initiated_by"] in ("SYSTEM_REROUTE", "SYSTEM_DEACTIVATION"))

    # fulfillment_status dimension
    if order.get("_cancelled"):
        fulfillment = "CANCELLED"
    elif (order["shipped_units"] > 0
          and order["shipped_units"] + cancelled_units + order["dc_fallback_units"]
          == order["total_units"]):
        fulfillment = "SHIPPED"
    elif order["shipped_units"] > 0:
        fulfillment = "PARTIALLY_SHIPPED"
    else:
        fulfillment = "PENDING"
    order["fulfillment_status"] = fulfillment

    # routing_status dimension (calculations.order_routing_status_derivation)
    pending_reroute = (
        order["unassigned_units"] > 0
        and order["reroute_attempt_count"] < MAX_REROUTE_ATTEMPTS
        and any(a["status"] in ("REJECTED", "CANCELLED", "SHORT_PICKED")
                for a in assignments)
    )
    if not runs:
        routing = "UNROUTED"
    elif order["unassigned_units"] > 0 and pending_reroute:
        routing = "ROUTING"
    elif covered_units == 0:
        routing = "UNROUTABLE"
    elif covered_units + cancelled_units == order["total_units"]:
        routing = "ROUTED"
    else:
        routing = "PARTIALLY_ROUTED"
    order["routing_status"] = routing

    provisional = order_cost(order, "provisional")
    order["provisional_cost_cents"] = provisional["store_cost_cents"]
    order["dc_baseline_cost_cents"] = provisional["dc_baseline_cost_cents"]
    if fulfillment == "SHIPPED":
        final = order_cost(order, "final")
        order["final_cost_cents"] = final["store_cost_cents"]
        order["cost_variance_cents"] = (final["store_cost_cents"]
                                        - order["provisional_cost_cents"])
        order["cost_index_bps"] = final["cost_index_bps"]
    else:
        order["final_cost_cents"] = None
        order["cost_variance_cents"] = None
        order["cost_index_bps"] = provisional["cost_index_bps"]


# ------------------------------------------------------------------ versioning

DERIVED_FIELDS = {
    "stores": ("units_committed_epoch", "reserved_labor_minutes", "eligibility_score",
               "eligibility_score_basis", "node_status", "review_score",
               "consecutive_breach_windows", "deactivated_at_epoch",
               "reactivation_count"),
    "inventories": ("on_hand_units", "reserved_units", "safety_stock_units",
                    "available_to_promise_units", "last_adjustment_reason"),
    "packaging": ("on_hand_units", "reorder_point_units", "reorder_flag",
                  "lifetime_consumed_units"),
    "pickups": ("reserved_parcels", "status"),
    "orders": ("routing_status", "fulfillment_status", "total_units", "shipped_units",
               "unassigned_units", "dc_fallback_units", "split_count",
               "reroute_attempt_count", "provisional_cost_cents", "final_cost_cents",
               "cost_variance_cents", "dc_baseline_cost_cents", "cost_index_bps"),
    "order_lines": ("assigned_units", "shipped_units", "cancelled_units",
                    "dc_fallback_units", "open_units", "line_status"),
    "windows": ("status", "closed_at_utc", "assignments_created", "assignments_shipped",
                "assignments_rejected", "assignments_cancelled", "units_promised",
                "units_shipped", "fill_rate", "avg_cycle_time_minutes",
                "cancellation_rate", "breach_flags", "breached",
                "store_cost_per_order_cents", "dc_cost_per_order_cents",
                "cost_index_bps", "cost_disadvantaged", "node_action"),
}


def capture():
    state = {}
    for kind, fields in DERIVED_FIELDS.items():
        for row in getattr(db, kind).values():
            state[(kind, row["id"])] = tuple(_frozen(row.get(f)) for f in fields)
    return state


def _frozen(value):
    if isinstance(value, list):
        return tuple(value)
    return value


def commit(pre_state, explicit=()):
    """Recompute everything, then bump versions on rows whose state moved."""
    recompute_all()
    bumps = set()
    for kind, fields in DERIVED_FIELDS.items():
        for row in getattr(db, kind).values():
            key = (kind, row["id"])
            if key not in pre_state:
                continue
            if pre_state[key] != tuple(_frozen(row.get(f)) for f in fields):
                bumps.add(key)
    for row in explicit:
        if row is None:
            continue
        bumps.add((row["_kind"], row["id"]))
    for kind, row_id in bumps:
        row = getattr(db, kind).get(row_id)
        if row is not None and "version" in row:
            touch(row)
