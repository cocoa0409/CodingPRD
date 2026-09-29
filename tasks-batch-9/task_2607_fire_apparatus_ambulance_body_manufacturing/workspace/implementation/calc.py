"""Derived quantities (PRD §3, SCAFFOLD §1.3).

Every quantisation in this module is round-half-up on `Decimal`, except the two
places the specification nominates a floor (the percentage-of-rating leg of
payload capacity) and integer division is never used for money.
"""

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from db import by_created_at, db
from timeutil import add_days, add_months, format_like, parse_dt

# -- unit_award_price ------------------------------------------------------
OPTION_UNIT_PREMIUM_PCT = Decimal("3.5")
BOND_TIER_1_MAX_CENTS = 50000000
BOND_TIER_1_RATE_PCT = Decimal("1.25")
BOND_TIER_2_MAX_CENTS = 90000000
BOND_TIER_2_RATE_PCT = Decimal("1.00")
BOND_TIER_3_RATE_PCT = Decimal("0.75")

# -- change_order_price_delta ---------------------------------------------
TAX_RATE_PCT = Decimal("6.5")
MARKUP_CAP_PCT = Decimal("22.0")

# -- axle_load_distribution -----------------------------------------------
PAYLOAD_MODEL = {
    "PUMPER": (3400, Decimal(28)),
    "AERIAL": (1800, Decimal(12)),
    "AMBULANCE": (900, Decimal(20)),
}
FRONT_PAYLOAD_CAP_KG = 450
FRONT_PAYLOAD_SHARE = Decimal("0.25")
CREW_MASS_KG = 80
FRONT_CREW_SEAT_CAP = 2

# -- program_committed_cents ----------------------------------------------
CEILING_SOFT_PCT = Decimal(90)
COMMITTED_BUILD_STATUSES = (
    "SPEC_LOCKED",
    "PRE_CON_HELD",
    "IN_PRODUCTION",
    "MID_CON_HELD",
    "FINAL_INSPECTED",
    "DELIVERED",
    "WARRANTY_ACTIVE",
)

# -- compliance_readiness_score / restrictive_clause_ratio ----------------
MANDATORY_CLAUSE_WEIGHT = 3
OPTIONAL_CLAUSE_WEIGHT = 1
RELEASE_MIN_STRICT_SCORE = Decimal("75.00")
RESTRICTIVE_RATIO_MAX_PCT = Decimal("40.00")

# -- warranty_activation_window -------------------------------------------
REQUIRED_TRAINING_HOURS = Decimal("16.0")
WARRANTY_DEFERRAL_DAYS = 30

# -- slot occupancy --------------------------------------------------------
OCCUPYING_RESERVATION_STATUSES = ("RESERVED", "CONFIRMED", "CONSUMED")

TWO_PLACES = Decimal("0.01")


def rhu(value):
    """Quantise to a whole unit with round-half-up."""
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Quantise to two decimal places with round-half-up."""
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_DOWN))


def dec(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


# ==========================================================================
# unit_award_price — the seven pinned steps
# ==========================================================================


def _bond_rate(subtotal_cents):
    if subtotal_cents <= BOND_TIER_1_MAX_CENTS:
        return BOND_TIER_1_RATE_PCT
    if subtotal_cents <= BOND_TIER_2_MAX_CENTS:
        return BOND_TIER_2_RATE_PCT
    return BOND_TIER_3_RATE_PCT


def _price_from_escalated_base(escalated_base_cents, option_unit):
    # Step 3 — the option premium, rounded on its own.
    if option_unit:
        premium = rhu(
            Decimal(escalated_base_cents) * OPTION_UNIT_PREMIUM_PCT / Decimal(100)
        )
    else:
        premium = 0
    # Step 4 — the subtotal is NOT rounded; both addends are whole cents.
    subtotal = escalated_base_cents + premium
    # Step 5 — the bond tier is keyed on the subtotal, never on the total.
    rate = _bond_rate(subtotal)
    # Step 6 — the bond fee is rounded.
    fee = rhu(Decimal(subtotal) * rate / Decimal(100))
    # Step 7 — no further rounding.
    return subtotal + fee


def award_year_locked_price(program, award_year, option_unit):
    """`UnitOrder.price_cents`: compounded over whole years elapsed."""
    years_elapsed = int(award_year) - int(program["base_year"])
    if years_elapsed < 0:
        years_elapsed = 0
    index = dec(program["escalation_index_pct_per_year"])
    factor = (Decimal(1) + index / Decimal(100)) ** years_elapsed
    escalated_base = rhu(Decimal(program["base_unit_price_cents"]) * factor)
    return _price_from_escalated_base(escalated_base, option_unit)


def delivery_year_actual_price(program, delivery_raw, option_unit):
    """`WarrantyStartup.final_price_cents`: simple pro-rata over whole months."""
    delivered = parse_dt(delivery_raw)
    months_elapsed = (delivered.year - int(program["base_year"])) * 12 + (
        delivered.month - 1
    )
    index = dec(program["escalation_index_pct_per_year"])
    factor = Decimal(1) + (index / Decimal(100)) * (
        Decimal(months_elapsed) / Decimal(12)
    )
    escalated_base = rhu(Decimal(program["base_unit_price_cents"]) * factor)
    return _price_from_escalated_base(escalated_base, option_unit)


# ==========================================================================
# change_order_price_delta — round per line, then sum
# ==========================================================================


def change_order_price_delta(items):
    total = 0
    for item in items:
        base = int(item["quantity"]) * int(item["unit_cost_cents"])
        marked = rhu(
            Decimal(base) * (Decimal(1) + dec(item["markup_pct"]) / Decimal(100))
        )
        if item["is_taxable"]:
            tax = rhu(Decimal(marked) * TAX_RATE_PCT / Decimal(100))
        else:
            tax = 0
        total += marked + tax
    return total


# ==========================================================================
# axle_load_distribution
# ==========================================================================


def approved_weight_deltas(unit_id):
    front = 0
    rear = 0
    for change_order in db.change_orders.values():
        if change_order["unit_order_id"] != unit_id:
            continue
        if change_order["status"] != "APPROVED":
            continue
        front += int(change_order["weight_delta_front_kg"])
        rear += int(change_order["weight_delta_rear_kg"])
    return front, rear


def axle_load_distribution(unit):
    cap_kg, pct = PAYLOAD_MODEL[unit["unit_type"]]
    gvwr = int(unit["gvwr_kg"])
    pct_leg = floor_int(Decimal(gvwr) * pct / Decimal(100))
    payload = min(cap_kg, pct_leg)

    front_payload = min(
        FRONT_PAYLOAD_CAP_KG, rhu(Decimal(payload) * FRONT_PAYLOAD_SHARE)
    )
    rear_payload = payload - front_payload

    seats = int(unit["crew_seat_count"])
    front_crew = min(seats, FRONT_CREW_SEAT_CAP) * CREW_MASS_KG
    rear_crew = max(seats - FRONT_CREW_SEAT_CAP, 0) * CREW_MASS_KG

    co_front, co_rear = approved_weight_deltas(unit["id"])

    front_load = int(unit["base_curb_front_kg"]) + front_payload + front_crew + co_front
    rear_load = int(unit["base_curb_rear_kg"]) + rear_payload + rear_crew + co_rear
    gross = front_load + rear_load

    if gross > gvwr:
        verdict = "OVER_GVWR"
    elif front_load > int(unit["front_axle_rating_kg"]):
        verdict = "OVER_FRONT"
    elif rear_load > int(unit["rear_axle_rating_kg"]):
        verdict = "OVER_REAR"
    else:
        verdict = "WITHIN_LIMITS"

    return front_load, rear_load, gross, verdict


def apply_axle_loads(unit):
    front, rear, gross, verdict = axle_load_distribution(unit)
    unit["front_axle_load_kg"] = front
    unit["rear_axle_load_kg"] = rear
    unit["gross_weight_kg"] = gross
    unit["weight_status"] = verdict
    return unit


# ==========================================================================
# unit_change_order_total / open_change_order_count
# ==========================================================================

OPEN_CHANGE_ORDER_STATUSES = ("DRAFT", "SUBMITTED", "IN_NEGOTIATION")


def unit_change_order_total(unit_id):
    total = 0
    for change_order in db.change_orders.values():
        if change_order["unit_order_id"] == unit_id and change_order["status"] == "APPROVED":
            total += int(change_order["price_delta_cents"])
    return total


def unit_open_change_order_count(unit_id):
    count = 0
    for change_order in db.change_orders.values():
        if (
            change_order["unit_order_id"] == unit_id
            and change_order["status"] in OPEN_CHANGE_ORDER_STATUSES
        ):
            count += 1
    return count


# ==========================================================================
# program ledger
# ==========================================================================


def soft_ceiling_cents(program):
    return rhu(
        Decimal(program["contract_ceiling_cents"]) * CEILING_SOFT_PCT / Decimal(100)
    )


def program_committed_cents(program_id, overrides=None):
    """Sum price + approved change-order total over every non-CANCELLED unit.

    `overrides` lets a caller price a prospective write (an award not yet
    persisted, an approval not yet applied) without mutating a single row, which
    is what rung 52 needs: a hard-ceiling breach must persist nothing at all.
    """
    overrides = overrides or {}
    total = 0
    for unit in db.unit_orders.values():
        if unit["program_id"] != program_id:
            continue
        if unit["build_status"] not in COMMITTED_BUILD_STATUSES:
            continue
        delta = overrides.get(unit["id"])
        if delta is None:
            total += int(unit["price_cents"]) + int(unit["change_order_total_cents"])
        else:
            total += delta
    for extra in overrides.get("_extra", []):
        total += extra
    return total


# ==========================================================================
# slot line occupancy
# ==========================================================================


def slot_line_occupancy(line_id):
    reserved = 0
    for reservation in db.reservations.values():
        if (
            reservation["slot_line_id"] == line_id
            and reservation["status"] in OCCUPYING_RESERVATION_STATUSES
        ):
            reserved += 1
    return reserved


# ==========================================================================
# bay concurrent load — closed intervals, aggregate capacity
# ==========================================================================


def windows_intersect(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def bay_occupied_visitors(plant_bay_id, start_raw, end_raw, exclude_trip_id=None):
    start = parse_dt(start_raw)
    end = parse_dt(end_raw)
    occupied = 0
    for trip in db.trips.values():
        if trip["plant_bay_id"] != plant_bay_id:
            continue
        if trip["status"] not in ("SCHEDULED", "HELD"):
            continue
        if exclude_trip_id is not None and trip["id"] == exclude_trip_id:
            continue
        if windows_intersect(
            parse_dt(trip["scheduled_start"]),
            parse_dt(trip["scheduled_end"]),
            start,
            end,
        ):
            occupied += int(trip["committee_size"])
    return occupied


# ==========================================================================
# slot window conflict — half-open intervals, pairwise, buffered
# ==========================================================================


def slot_window_conflicts(line, start_raw, end_raw):
    new_start = parse_dt(start_raw)
    new_end = parse_dt(end_raw)
    buffer_days = int(line["changeover_buffer_days"])
    for reservation in by_created_at(list(db.reservations.values())):
        if reservation["slot_line_id"] != line["id"]:
            continue
        if reservation["status"] not in OCCUPYING_RESERVATION_STATUSES:
            continue
        inflated_start = add_days(parse_dt(reservation["slot_start_date"]), -buffer_days)
        inflated_end = add_days(parse_dt(reservation["slot_end_date"]), buffer_days)
        if new_start < inflated_end and inflated_start < new_end:
            return True
    return False


# ==========================================================================
# compliance readiness scores and the restrictive-clause ratio
# ==========================================================================


def _clause_weight(clause):
    return MANDATORY_CLAUSE_WEIGHT if clause["mandatory"] else OPTIONAL_CLAUSE_WEIGHT


def spec_clauses(specification_id):
    return by_created_at(
        [c for c in db.clauses.values() if c["specification_id"] == specification_id]
    )


def spec_entries(specification_id):
    return by_created_at(
        [
            e
            for e in db.compliance_entries.values()
            if e["specification_id"] == specification_id
        ]
    )


def _entry_for(specification_id, clause_id):
    for entry in spec_entries(specification_id):
        if entry["clause_id"] == clause_id:
            return entry
    return None


def _compliant(entry, provisional):
    if entry is None:
        return False
    if entry["response"] == "COMPLY":
        return True
    if entry["response"] in ("EXCEPTION", "ALTERNATE"):
        if provisional:
            return entry["disposition"] in ("PENDING", "ACCEPTED")
        return entry["disposition"] == "ACCEPTED"
    return False


def compliance_readiness_score(specification_id, provisional):
    clauses = spec_clauses(specification_id)
    total_weight = sum(_clause_weight(c) for c in clauses)
    if total_weight == 0:
        return Decimal("0.00")
    compliant_weight = 0
    for clause in clauses:
        entry = _entry_for(specification_id, clause["id"])
        if _compliant(entry, provisional):
            compliant_weight += _clause_weight(clause)
    return rhu2(Decimal(100) * Decimal(compliant_weight) / Decimal(total_weight))


def restrictive_clause_ratio(specification_id):
    mandatory = [c for c in spec_clauses(specification_id) if c["mandatory"]]
    if not mandatory:
        return Decimal("0.00")
    restrictive = sum(1 for c in mandatory if c["is_restrictive"])
    return rhu2(Decimal(100) * Decimal(restrictive) / Decimal(len(mandatory)))


# ==========================================================================
# warranty window
# ==========================================================================


def warranty_window(delivery_raw, months, deferred):
    """Returns (start_raw, end_raw) rendered in the delivery date's own style."""
    delivered = parse_dt(delivery_raw)
    start = add_days(delivered, WARRANTY_DEFERRAL_DAYS) if deferred else delivered
    end = add_months(start, months)
    start_raw = delivery_raw if not deferred else format_like(delivery_raw, start)
    return start_raw, format_like(delivery_raw, end)
