"""Every priced or counted rule in the specification (PRD 2.6, 3.2, 3.5-3.9).

All money is integer cents.  Every multiplication of a cent amount by a
fraction is rounded half up, and the rounding order stated in the PRD is
reproduced literally: it is load-bearing.
"""

from decimal import Decimal, ROUND_HALF_UP

from util import date_diff_days, inclusive_days, parse_date

# --- contracted_rental_charge -------------------------------------------------
MOVE_PERIOD_FACTOR = Decimal("0.5")
DEPOSIT_PCT = Decimal("0.25")

# --- hold hierarchy ----------------------------------------------------------
RELEASE_LEAD_MONTHS = 3

# --- citywide qualification --------------------------------------------------
CITYWIDE_MIN_ROOM_NIGHTS = 2500

# --- service_order_charge ----------------------------------------------------
UTIL_TIER1_CENTS = Decimal("1200")
UTIL_TIER2_CENTS = Decimal("900")
UTIL_TIER3_CENTS = Decimal("700")
RIG_POINT_CENTS = Decimal("25000")
CLEAN_SQFT_CENTS = Decimal("6")
GUARD_HOUR_CENTS = Decimal("4200")
LATE_ORDER_FACTOR = Decimal("1.35")
VENDOR_PREFERRED_MULT = Decimal("1.10")
VENDOR_OPEN_MULT = Decimal("1.25")
SURCHARGE_CAP = Decimal("1.40")
MIN_ORDER_CENTS = 15000
ADVANCE_CUTOFF_DAYS = 30

# --- fnb_buyout_fee ----------------------------------------------------------
BUYOUT_PCT = Decimal("0.22")
MIN_BUYOUT_CENTS = 250000

# --- facility_service_fee ----------------------------------------------------
FEE_TIER_1_CENTS = 5000000
FEE_TIER_2_CENTS = 20000000
FEE_PCT_LOW = Decimal("0.09")
FEE_PCT_MID = Decimal("0.07")
FEE_PCT_HIGH = Decimal("0.055")

# --- settlement_rental_basis -------------------------------------------------
USAGE_FACTOR = {
    "MOVE_IN": Decimal("0.5"),
    "SHOW": Decimal("1.0"),
    "DARK": Decimal("0.125"),
    "MOVE_OUT": Decimal("0.5"),
    "HOLDOVER": Decimal("1.5"),
}

# --- client_booking_standing -------------------------------------------------
STANDING_THRESHOLD_CENTS = 10000000

# --- round / negotiation ceilings -------------------------------------------
MAX_AMENDMENT_ROUNDS = 3
MAX_SETTLEMENT_REVISIONS = 2
DISPUTE_WINDOW_HOURS = 240


def dec(value):
    """Exact Decimal from an int/float/str without binary float noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal to a whole number of cents, half away from zero."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def one_decimal(value):
    """Crew-hour quantities are carried to one decimal place (PRD 2.6)."""
    quantized = dec(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(quantized)


# --------------------------------------------------------------------------
# contracted_rental_charge (PRD 3.2)
# --------------------------------------------------------------------------
def contracted_rental_charge(space, window, move_in_start, show_start, show_end, move_out_end):
    show_days = inclusive_days(show_start, show_end)
    move_in_days = date_diff_days(show_start, move_in_start)
    move_out_days = date_diff_days(move_out_end, show_end)
    billable_units = dec(show_days) + MOVE_PERIOD_FACTOR * dec(move_in_days + move_out_days)
    gross = round_half_up(dec(space["daily_base_rate_cents"]) * billable_units)
    contracted = round_half_up(dec(gross) * (Decimal("1") - dec(window["rental_discount_pct"])))
    deposit = round_half_up(dec(contracted) * DEPOSIT_PCT)
    return gross, contracted, deposit


def space_days_committed(move_in_start, move_out_end):
    return inclusive_days(move_in_start, move_out_end)


# --------------------------------------------------------------------------
# service_order_charge (PRD 3.5)
# --------------------------------------------------------------------------
def base_units_cents(service_category, quantity):
    q = dec(quantity)
    if service_category == "UTILITIES":
        tier1 = min(q, Decimal("100"))
        tier2 = max(Decimal("0"), min(q, Decimal("400")) - Decimal("100"))
        tier3 = max(Decimal("0"), q - Decimal("400"))
        return tier1 * UTIL_TIER1_CENTS + tier2 * UTIL_TIER2_CENTS + tier3 * UTIL_TIER3_CENTS
    if service_category == "RIGGING":
        return q * RIG_POINT_CENTS
    if service_category == "CLEANING":
        return q * CLEAN_SQFT_CENTS
    if service_category == "SECURITY":
        return q * GUARD_HOUR_CENTS
    return Decimal("0")


def vendor_multiplier(vendor_tier):
    if vendor_tier == "PREFERRED":
        return VENDOR_PREFERRED_MULT
    if vendor_tier == "OPEN":
        return VENDOR_OPEN_MULT
    return Decimal("1.00")


def service_order_charge(order, vendor, quantity):
    base = base_units_cents(order["service_category"], quantity)
    timing_factor = LATE_ORDER_FACTOR if order["order_timing"] == "LATE" else Decimal("1.00")
    combined = min(timing_factor * vendor_multiplier(vendor["vendor_tier"]), SURCHARGE_CAP)
    return max(MIN_ORDER_CENTS, round_half_up(base * combined))


def order_timing(clock_date, show_start_date):
    """ADVANCE only when the clock date is MORE than 30 days before show start."""
    return "ADVANCE" if date_diff_days(show_start_date, clock_date) > ADVANCE_CUTOFF_DAYS else "LATE"


# --------------------------------------------------------------------------
# union labour (PRD 3.6)
# --------------------------------------------------------------------------
def labor_span(call, actualized):
    if actualized:
        return dec(call["actual_end_hour"]) - dec(call["actual_start_hour"])
    return dec(call["scheduled_end_hour"]) - dec(call["scheduled_start_hour"])


def union_crew_hours_committed(call, jurisdiction, actualized):
    span = labor_span(call, actualized)
    hours_per_member = max(dec(jurisdiction["min_call_hours"]), span)
    return one_decimal(dec(call["crew_size"]) * hours_per_member)


def union_labor_charge_estimate(call, jurisdiction):
    span = dec(call["scheduled_end_hour"]) - dec(call["scheduled_start_hour"])
    hours_per_member = max(dec(jurisdiction["min_call_hours"]), span)
    return round_half_up(
        dec(call["crew_size"]) * hours_per_member * dec(jurisdiction["straight_time_rate_cents"])
    )


def union_labor_charge_actual(call, jurisdiction):
    crew = dec(call["crew_size"])
    rate = dec(jurisdiction["straight_time_rate_cents"])
    start = dec(call["actual_start_hour"])
    end = dec(call["actual_end_hour"])
    span = end - start
    st_hours = max(
        Decimal("0"),
        min(end, dec(jurisdiction["st_window_end_hour"]))
        - max(start, dec(jurisdiction["st_window_start_hour"])),
    )
    ot_hours = span - st_hours
    uplift_hours = max(Decimal("0"), dec(jurisdiction["min_call_hours"]) - span)
    band_st = round_half_up(crew * st_hours * rate)
    band_ot = round_half_up(crew * ot_hours * rate * dec(jurisdiction["overtime_multiplier"]))
    band_uplift = round_half_up(crew * uplift_hours * rate)
    return band_st + band_ot + band_uplift


# --------------------------------------------------------------------------
# fnb_buyout_fee (PRD 3.7)
# --------------------------------------------------------------------------
def fnb_buyout_fee(arrangement, basis_cents):
    if arrangement["arrangement_type"] == "IN_HOUSE":
        return 0
    if basis_cents is None:
        return 0
    return max(MIN_BUYOUT_CENTS, round_half_up(dec(basis_cents) * BUYOUT_PCT))


# --------------------------------------------------------------------------
# settlement arithmetic (PRD 3.9)
# --------------------------------------------------------------------------
def settlement_rental_basis(settlement, booking, space, window, usage_records):
    if settlement["basis"] == "CONTRACTED":
        return booking["contracted_rental_cents"]
    ordered = sorted(usage_records, key=lambda r: (r["usage_date"], r["created_at"], r["_seq"]))
    raw = 0
    for record in ordered:
        factor = USAGE_FACTOR.get(record["usage_kind"], Decimal("0"))
        raw += round_half_up(dec(space["daily_base_rate_cents"]) * factor)
    return round_half_up(dec(raw) * (Decimal("1") - dec(window["rental_discount_pct"])))


def settlement_line_extension(line_items):
    ordered = sorted(line_items, key=lambda r: (r["created_at"], r["_seq"]))
    return sum(item["amount_cents"] for item in ordered)


def facility_service_fee(line_subtotal_cents):
    if line_subtotal_cents < FEE_TIER_1_CENTS:
        fee_pct = FEE_PCT_LOW
    elif line_subtotal_cents < FEE_TIER_2_CENTS:
        fee_pct = FEE_PCT_MID
    else:
        fee_pct = FEE_PCT_HIGH
    return round_half_up(dec(line_subtotal_cents) * fee_pct)


def client_booking_standing(outstanding_balance_cents):
    return "HOLD_RESTRICTED" if outstanding_balance_cents > STANDING_THRESHOLD_CENTS else "GOOD"
