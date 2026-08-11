"""Business logic: calculations (SCAFFOLD §1.3), derived fields, cascades,
and the compound order posture auto-transitions (PRD §2.9, §3.7)."""
from decimal import Decimal

from errors import api_error
from store import db, new_id, now, stamp, touch
from util import D, rhu_2dp, rhu_int

# --- calculation constants (SCAFFOLD §1.3) ----------------------------------
MULTIPLIERS = {
    "L1": Decimal("0.60"),
    "L2": Decimal("0.65"),
    "L3": Decimal("0.70"),
    "L4": Decimal("0.75"),
    "L5": Decimal("0.80"),
}
TIER1_MIN_CENTS = 5_000_000
TIER2_MIN_CENTS = 10_000_000
TIER1_RATE = Decimal("0.05")
TIER2_RATE = Decimal("0.08")

MOD_BASE_FEE_CENTS = {
    "REDUCED_DEPTH": 2500,
    "INCREASED_DEPTH": 4000,
    "REDUCED_WIDTH": 2500,
    "INCREASED_WIDTH": 4000,
    "TOE_KICK_NOTCH": 5500,
    "CUSTOM_BORE": 3000,
}
MOD_TIER_HIGH = Decimal("0.15")   # delta >= 6
MOD_TIER_MID = Decimal("0.10")    # delta >= 3
MOD_TIER_LOW = Decimal("0.05")    # delta < 3
MOD_MAX_PCT = Decimal("0.40")

CUBIC_IN_PER_CU_FT = 1728

FREIGHT_FLAT_MIN_CENTS = 8500
FREIGHT_RATE_PER_CU_FT_CENTS = 450
CONS_TIER1_COUNT = 3
CONS_TIER2_COUNT = 5
CONS_TIER1_PCT = Decimal("0.10")
CONS_TIER2_PCT = Decimal("0.15")

CLAIM_PROVISIONAL_PCT = Decimal("0.50")
CLAIM_DEALER_ERROR_CHARGE_PCT = Decimal("0.60")
FREIGHT_WINDOW_DAYS = 90
DEFECT_WINDOW_DAYS = 365

PRICE_LEVELS = ["L1", "L2", "L3", "L4", "L5"]
CONSTRUCTIONS = ["SLAB", "SHAKER", "RAISED_PANEL", "GLASS"]
SHEENS = ["MATTE", "SATIN", "SEMI_GLOSS", "HIGH_GLOSS"]
COMPONENT_KINDS = ["SHEET_GOODS", "DOOR_BLANK", "HARDWARE"]
LINE_TYPES = ["BOX", "DOOR"]
MOD_CODES = list(MOD_BASE_FEE_CENTS.keys())
REVIEW_DECISIONS = ["APPROVE", "REQUEST_CHANGES", "REJECT"]
CLAIM_TYPES = ["FREIGHT_DAMAGE", "MANUFACTURING_DEFECT", "DEALER_ERROR"]
ADJUDICATION_DECISIONS = ["APPROVE", "DENY"]

ALL_ROLES = {
    "PlantAdmin", "Dealer", "Engineer",
    "FinishSupervisor", "ProductionPlanner", "ShippingCoordinator",
}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def lines_of_order(order_id):
    return [l for l in db.order_lines.values() if l["order_id"] == order_id]


def live_lines(order):
    """Non-cancelled lines of an order."""
    return [l for l in lines_of_order(order["id"]) if l["status"] != "CANCELLED"]


def mods_of_line(line_id):
    return [m for m in db.mods.values() if m["order_line_id"] == line_id]


def sublots_of_line(line_id):
    return [s for s in db.sub_lots.values() if s["order_line_id"] == line_id]


def holds_of_order(order_id):
    return [h for h in db.holds.values() if h["order_id"] == order_id]


def route_orders(route_id):
    return [o for o in db.orders.values() if o["delivery_route_id"] == route_id]


# ---------------------------------------------------------------------------
# Derived fields (computed on read — always reconciled)
# ---------------------------------------------------------------------------

def line_slotted_qty(line_id) -> int:
    """Sum of qty over non-cancelled SubLots covering this line."""
    return sum(s["qty"] for s in sublots_of_line(line_id) if s["status"] != "CANCELLED")


def batch_assigned_door_count(batch_id) -> int:
    return sum(
        l["qty"] for l in db.order_lines.values()
        if l["finish_batch_id"] == batch_id and l["status"] != "CANCELLED"
    )


def route_reserved_cu_ft(route_id, exclude_order_id=None) -> Decimal:
    total = Decimal("0")
    for o in route_orders(route_id):
        if exclude_order_id is not None and o["id"] == exclude_order_id:
            continue
        total += o["cube_ft"]
    return rhu_2dp(total)


def order_hold_status(order_id) -> str:
    for h in db.holds.values():
        if h["order_id"] == order_id and h["status"] == "PLACED":
            return "ON_HOLD"
    return "NONE"


def approved_mod_total(line_id) -> int:
    return sum(
        m["surcharge_cents"] for m in mods_of_line(line_id) if m["status"] == "APPROVED"
    )


def recompute_order_cube(order) -> None:
    """Per-line cube rounded to 2dp first, then summed (order_cube, §1.3)."""
    total = Decimal("0")
    for l in live_lines(order):
        cubic_in = l["width_in"] * l["height_in"] * l["depth_in"] * l["qty"]
        total += rhu_2dp(D(cubic_in) / D(CUBIC_IN_PER_CU_FT))
    order["cube_ft"] = rhu_2dp(total)


# ---------------------------------------------------------------------------
# Compound order posture: auto-transitions (PRD §2.9 / §3.7)
# ---------------------------------------------------------------------------

def reevaluate_order(order) -> None:
    """Auto-evaluate SUBMITTED -> IN_PRODUCTION -> READY_TO_SHIP.

    Gated while ON_HOLD. Each auto-advance increments Order.version by 1.
    """
    if order["status"] == "SUBMITTED" and order_hold_status(order["id"]) == "NONE":
        lines = live_lines(order)
        doors_ok = all(
            l["finish_batch_id"] is not None for l in lines if l["line_type"] == "DOOR"
        )
        boxes_ok = all(
            line_slotted_qty(l["id"]) == l["qty"] for l in lines if l["line_type"] == "BOX"
        )
        if doors_ok and boxes_ok:
            order["status"] = "IN_PRODUCTION"
            touch(order)
    if order["status"] == "IN_PRODUCTION" and order_hold_status(order["id"]) == "NONE":
        lines = live_lines(order)
        if lines and all(l["status"] == "COMPLETED" for l in lines):
            order["status"] = "READY_TO_SHIP"
            touch(order)


# ---------------------------------------------------------------------------
# Holds
# ---------------------------------------------------------------------------

def place_hold(order_id, reason, component_id=None, shortfall_qty=None):
    hold = {
        "id": new_id(),
        "order_id": order_id,
        "component_id": component_id,
        "reason": reason,
        "shortfall_qty": shortfall_qty,
        "status": "PLACED",
    }
    stamp(hold)
    db.holds[hold["id"]] = hold
    return hold


def release_hold(hold) -> None:
    """Release a PLACED hold; recompute posture and re-fire pending
    auto-transitions on the held order."""
    hold["status"] = "RELEASED"
    touch(hold)
    order = db.orders.get(hold["order_id"])
    if order is not None:
        reevaluate_order(order)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def compute_mod_surcharge(line, mod_code, new_dimension_in) -> int:
    """mod_surcharge: base fee -> tiered pct of line list -> min(cap)."""
    if mod_code in ("REDUCED_DEPTH", "INCREASED_DEPTH"):
        delta = abs(new_dimension_in - line["depth_in"])
    elif mod_code in ("REDUCED_WIDTH", "INCREASED_WIDTH"):
        delta = abs(new_dimension_in - line["width_in"])
    else:  # TOE_KICK_NOTCH, CUSTOM_BORE: no comparison dimension
        delta = new_dimension_in
    if delta >= 6:
        tier = MOD_TIER_HIGH
    elif delta >= 3:
        tier = MOD_TIER_MID
    else:
        tier = MOD_TIER_LOW
    raw = MOD_BASE_FEE_CENTS[mod_code] + rhu_int(D(line["line_list_cents"]) * tier)
    cap = rhu_int(D(line["line_list_cents"]) * MOD_MAX_PCT)
    return min(raw, cap)


def volume_tier_rate(merchandise_cents) -> Decimal:
    if merchandise_cents >= TIER2_MIN_CENTS:
        return TIER2_RATE
    if merchandise_cents >= TIER1_MIN_CENTS:
        return TIER1_RATE
    return Decimal("0")


def price_order_provisional(order):
    """VARIANT 1 (submit): multiplier discounts list + upcharge + mods.
    Pure computation — returns (merch, discount, total, {line_id: net}, {line_id: mods}).
    Per-line rounding before summing (§2.5)."""
    mult = MULTIPLIERS[order["price_level_snapshot"]]
    merch = 0
    nets, mods = {}, {}
    for l in live_lines(order):
        mod_total = approved_mod_total(l["id"])
        base = l["line_list_cents"] + l["finish_upcharge_cents"] + mod_total
        net = rhu_int(D(base) * mult)
        nets[l["id"]] = net
        mods[l["id"]] = mod_total
        merch += net
    discount = rhu_int(D(merch) * volume_tier_rate(merch))
    return merch, discount, merch - discount, nets, mods


def price_order_final(order):
    """VARIANT 2 (dispatch): multiplier on list only; upcharge and mods at
    full value. Pure computation — returns (merch, discount, {line_id: net},
    {line_id: mods})."""
    mult = MULTIPLIERS[order["price_level_snapshot"]]
    merch = 0
    nets, mods = {}, {}
    for l in live_lines(order):
        mod_total = approved_mod_total(l["id"])
        net = rhu_int(D(l["line_list_cents"]) * mult) + l["finish_upcharge_cents"] + mod_total
        nets[l["id"]] = net
        mods[l["id"]] = mod_total
        merch += net
    discount = rhu_int(D(merch) * volume_tier_rate(merch))
    return merch, discount, nets, mods


def compute_freight_cents(order, route_order_count: int) -> int:
    """freight_consolidation: cube -> base freight -> consolidation tier read
    from the route's assigned_order_count at the dispatch instant."""
    base = max(
        FREIGHT_FLAT_MIN_CENTS,
        rhu_int(order["cube_ft"] * FREIGHT_RATE_PER_CU_FT_CENTS),
    )
    if route_order_count >= CONS_TIER2_COUNT:
        pct = CONS_TIER2_PCT
    elif route_order_count >= CONS_TIER1_COUNT:
        pct = CONS_TIER1_PCT
    else:
        pct = Decimal("0")
    return rhu_int(D(base) * (Decimal("1") - pct))


def compute_nesting_yield(lines, component):
    """nesting_yield: area, ceil sheets with 12% waste, 2dp utilization."""
    total_area = sum(l["width_in"] * l["height_in"] * l["qty"] for l in lines)
    sheet_area = component["sheet_width_in"] * component["sheet_height_in"]
    # sheets = ceil(total * 1.12 / sheet_area); exact multiple adds no sheet
    sheets = -(-(total_area * 112) // (sheet_area * 100))
    utilization = rhu_2dp(D(100 * total_area) / D(sheets * sheet_area))
    return total_area, sheets, utilization


def part_sequence_key(line):
    """part_seq ordering: height DESC, width DESC, line created_at ASC."""
    return (-line["height_in"], -line["width_in"], line["created_at"], line["_seq"])


def claim_credit_basis(line, dealer, qty) -> int:
    """Basis uses the dealer's price_level CURRENT at claim creation."""
    mult = MULTIPLIERS[dealer["price_level"]]
    return rhu_int(D(line["unit_list_price_cents"]) * mult * qty)


def claim_within_window(claim, order) -> bool:
    """Whole-day windows measured from the original order's shipped_at;
    exactly N days after is within the window (boundary inclusive)."""
    shipped_at = order["shipped_at"]
    days = (now() - shipped_at).days
    if claim["claim_type"] == "FREIGHT_DAMAGE":
        return days <= FREIGHT_WINDOW_DAYS
    if claim["claim_type"] == "MANUFACTURING_DEFECT":
        return days <= DEFECT_WINDOW_DAYS
    return True  # DEALER_ERROR carries no warranty window
