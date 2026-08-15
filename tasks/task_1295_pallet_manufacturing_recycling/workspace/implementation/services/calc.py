"""Calculation rules per scaffold section 1.3. All money is integer cents;
fractional results use Decimal with ROUND_HALF_UP. Never float for money."""

import math
from decimal import Decimal, ROUND_HALF_UP

from db import db, now
from errors import raise_err

# --- pinned constants ---------------------------------------------------------
DECK_FRACTION = Decimal("0.6")
PRICE_BOOK_CENTS = {"NEW": 1500, "A": 1100, "B": 800}
BASE_MULTIPLIER_BP = 10000
POOL_CREDIT_TIER_CENTS = {"A": 700, "B": 350, "SCRAP": 0}
GRADE_A_FACTOR = Decimal("1.00")
GRADE_B_FACTOR = Decimal("0.60")
SCRAP_VALUE_CENTS = 0
SHORTAGE_PENALTY_FACTOR = Decimal("0.25")
LABOR_RATE_CENTS_PER_MIN = 95
ROUTE_COST_PER_MILE_CENTS = 185
STOP_COST_CENTS = 4500
HT_MIN_DURATION_HOURS = 6
MAX_REPAIR_CYCLES = 3


def d(value):
    """Coerce an int/float/str into an exact Decimal (str path avoids float noise)."""
    return Decimal(str(value))


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return d(value).quantize(q, rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    return int(round_half_up(value, 0))


# --- PalletSpec engineering constants ------------------------------------------

def compute_board_feet_per_pallet(length_in, board_count):
    """deck_boards = ceil(board_count * 0.6); stringers take the remainder.
    Deck section 3.5x0.5in, stringer section 3.5x1.5in, 144 in2 per board foot.
    Result rounded half-up to 2 decimal places."""
    deck_boards = math.ceil(board_count * 0.6)
    stringer_boards = board_count - deck_boards
    deck_bf = Decimal(deck_boards) * d(length_in) * Decimal("3.5") * Decimal("0.5") / Decimal(144)
    stringer_bf = Decimal(stringer_boards) * d(length_in) * Decimal("3.5") * Decimal("1.5") / Decimal(144)
    return float(round_half_up(deck_bf + stringer_bf, 2))


def compute_unit_cube_cuft(length_in, width_in, height_in):
    """length*width*height / 1728, rounded half-up to 4 decimal places."""
    cube = d(length_in) * d(width_in) * d(height_in) / Decimal(1728)
    return float(round_half_up(cube, 4))


# --- lumber index lookup --------------------------------------------------------

def find_lumber_index(species, instant):
    """Row whose species matches and effective_from <= instant < effective_to.
    Defensive tie-break: latest effective_from, then latest created_at.
    Returns None when no row covers the instant."""
    matches = [
        row for row in db.lumber_index.values()
        if row["species"] == species
        and row["_effective_from"] <= instant < row["_effective_to"]
    ]
    if not matches:
        return None
    matches.sort(key=lambda r: (r["_effective_from"], r["_created_sort"]), reverse=True)
    return matches[0]


def find_seasonal_index(instant):
    matches = [
        row for row in db.seasonal_index.values()
        if row["_effective_from"] <= instant < row["_effective_to"]
    ]
    if not matches:
        return None
    matches.sort(key=lambda r: (r["_effective_from"], r["_created_sort"]), reverse=True)
    return matches[0]


# --- inventory lot costing -------------------------------------------------------

def new_build_unit_cost_cents(spec, quantity_total, created_at):
    """Lumber index at lot creation x board feet, plus quantity-tiered overhead:
    qty < 100 -> 18%, 100 <= qty < 500 -> 12%, qty >= 500 -> 9%.
    round_half_up to integer cents. ERR_PRICE_INDEX_MISSING when uncovered."""
    idx = find_lumber_index(spec["lumber_species"], created_at)
    if idx is None:
        raise_err(
            "ERR_PRICE_INDEX_MISSING",
            "No lumber index row covers the lot creation timestamp for species %s"
            % spec["lumber_species"],
        )
    price_cents_per_bf = Decimal(idx["price_per_mbf_cents"]) / Decimal(1000)
    raw_cost = d(spec["board_feet_per_pallet"]) * price_cents_per_bf
    if quantity_total < 100:
        overhead = Decimal("0.18")
    elif quantity_total < 500:
        overhead = Decimal("0.12")
    else:
        overhead = Decimal("0.09")
    return round_half_up_int(raw_cost * (Decimal(1) + overhead))


def core_unit_price_cents(batch, grade):
    """Per-grade schedule from the owning batch: A -> 1.00x, B -> 0.60x
    (round half-up per unit), SCRAP -> 0."""
    agreed = Decimal(batch["agreed_unit_price_cents"])
    if grade == "A":
        return round_half_up_int(agreed * GRADE_A_FACTOR)
    if grade == "B":
        return round_half_up_int(agreed * GRADE_B_FACTOR)
    return SCRAP_VALUE_CENTS


def recycled_repair_unit_cost_cents(batch, outcome_grade, parts_cost_cents, actual_labor_minutes):
    """core per-grade price + parts + 95 cents/min of actual labor. No lumber
    index, no overhead tier."""
    core_price = core_unit_price_cents(batch, outcome_grade)
    labor = LABOR_RATE_CENTS_PER_MIN * actual_labor_minutes
    return round_half_up_int(Decimal(core_price + parts_cost_cents + labor))


# --- order pricing ---------------------------------------------------------------

def compute_order_pricing(order, lines, customer):
    """Per-line extended price (rounded per line, then summed), seasonal uplift
    from the band covering order_date (neutral 10000bp when none), pool credit
    capped at invoice value. Returns (subtotal, seasonal_adj, credit_applied, total)."""
    subtotal = 0
    for line in lines:
        extended = round_half_up_int(Decimal(line["quantity"]) * Decimal(line["unit_price_cents"]))
        line["extended_price_cents"] = extended
        subtotal += extended

    band = find_seasonal_index(order["_order_date"])
    multiplier_bp = band["multiplier_bp"] if band is not None else BASE_MULTIPLIER_BP
    seasonal_adjustment = round_half_up_int(
        Decimal(subtotal) * Decimal(multiplier_bp - BASE_MULTIPLIER_BP) / Decimal(10000)
    )
    invoice = subtotal + seasonal_adjustment
    credit_applied = min(customer["pool_credit_balance_cents"], invoice)
    total = invoice - credit_applied
    return subtotal, seasonal_adjustment, credit_applied, total


# --- batch settlement --------------------------------------------------------------

_GRADE_ORDER = {"A": 0, "B": 1, "SCRAP": 2}


def compute_final_settlement(batch, cores):
    """Chronological sweep (created_at asc, tie-break grade A<B<SCRAP), per-grade
    schedule summed, then under-delivery penalty (shortfall * price * 0.25,
    round half-up) deducted; floored at 0."""
    ordered = sorted(cores, key=lambda c: (c["_created_sort"], _GRADE_ORDER.get(c["grade"], 3)))
    total = 0
    for core in ordered:
        total += core_unit_price_cents(batch, core["grade"])
    shortfall = batch["manifest_count"] - batch["received_count"]
    if shortfall > 0:
        penalty = round_half_up_int(
            Decimal(shortfall) * Decimal(batch["agreed_unit_price_cents"]) * SHORTAGE_PENALTY_FACTOR
        )
        total -= penalty
    return max(total, 0)


def compute_grade_yield_variance_bp(batch, cores):
    received = batch["received_count"]
    if received <= 0:
        actual_a_frac = Decimal(0)
    else:
        a_count = sum(1 for c in cores if c["grade"] == "A")
        actual_a_frac = Decimal(a_count) / Decimal(received)
    estimated_a_frac = d(batch["estimated_grade_mix"].get("A", 0))
    return round_half_up_int((actual_a_frac - estimated_a_frac) * Decimal(10000))


# --- allocation selector ------------------------------------------------------------

def select_lot_for_line(line):
    """Candidate filters (all must hold): spec match, AVAILABLE, quality grade
    match, quantity_available >= line.quantity; HT filter per
    heat_treatment_required. Ranked lexicographically: RECYCLED_REPAIR first,
    then lowest unit_cost_cents, then earliest created_at.

    Returns (lot, error_id_or_None): on empty candidates returns
    ERR_INSUFFICIENT_STOCK, or ERR_HT_REQUIRED when candidates exist but all
    fail the heat-treatment filter."""
    base = [
        lot for lot in db.inventory_lots.values()
        if lot["spec_id"] == line["spec_id"]
        and lot["status"] == "AVAILABLE"
        and lot["quality_grade"] == line["quality_grade_requested"]
        and lot["quantity_available"] >= line["quantity"]
    ]
    if line["heat_treatment_required"]:
        candidates = [l for l in base if l["heat_treat_status"] == "HT_CERTIFIED"]
        if not candidates:
            return None, ("ERR_HT_REQUIRED" if base else "ERR_INSUFFICIENT_STOCK")
    else:
        candidates = [
            l for l in base
            if l["heat_treat_status"] in ("NOT_REQUIRED", "HT_CERTIFIED", "PENDING_HT")
        ]
        if not candidates:
            return None, "ERR_INSUFFICIENT_STOCK"
    candidates.sort(
        key=lambda l: (
            0 if l["origin_type"] == "RECYCLED_REPAIR" else 1,
            l["unit_cost_cents"],
            l["_created_sort"],
        )
    )
    return candidates[0], None


# --- route margins ---------------------------------------------------------------------

def route_mileage_cost_cents(planned_miles):
    return round_half_up_int(d(planned_miles) * Decimal(ROUTE_COST_PER_MILE_CENTS))


def compute_provisional_margin(route, stops):
    """Revenue: sum over SCHEDULED DELIVERY/MIXED stops of their order's
    total_cents. Cost: miles*185 (half-up) + 4500 per stop (all stops)."""
    revenue = 0
    for stop in stops:
        if stop["status"] == "SCHEDULED" and stop["stop_type"] in ("DELIVERY", "MIXED"):
            order = db.orders.get(stop["order_id"]) if stop.get("order_id") else None
            if order is not None:
                revenue += order["total_cents"] or 0
    cost = route_mileage_cost_cents(route["planned_miles"]) + STOP_COST_CENTS * len(stops)
    return revenue - cost


def compute_final_margin(route, stops):
    """Only COMPLETED stops deliver revenue (SKIPPED -> zero). Cost adds
    fuel_surcharge_cents and every CREDITED pool return on this route's stops."""
    revenue = 0
    for stop in stops:
        if stop["status"] == "COMPLETED" and stop["stop_type"] in ("DELIVERY", "MIXED"):
            order = db.orders.get(stop["order_id"]) if stop.get("order_id") else None
            if order is not None:
                revenue += order["total_cents"] or 0
    stop_ids = {s["id"] for s in stops}
    pickup_credit = sum(
        pr["total_credit_cents"] or 0
        for pr in db.pool_returns.values()
        if pr.get("route_stop_id") in stop_ids and pr["status"] == "CREDITED"
    )
    cost = (
        route_mileage_cost_cents(route["planned_miles"])
        + STOP_COST_CENTS * len(stops)
        + route["fuel_surcharge_cents"]
        + pickup_credit
    )
    return revenue - cost


# --- grinding ------------------------------------------------------------------------

def compute_yield_ratio(output_fiber_cuyd, input_count):
    return float(round_half_up(d(output_fiber_cuyd) / Decimal(input_count), 4))
