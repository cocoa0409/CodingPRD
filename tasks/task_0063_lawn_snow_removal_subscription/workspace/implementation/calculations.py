from decimal import Decimal, ROUND_HALF_UP
import math

# ---- constants ----
TAX_PCT = Decimal("0.07")
W_HOURS = Decimal("2.0")
W_DISPATCH = Decimal("5.0")
W_AGE = Decimal("0.5")
MAINTENANCE_THRESHOLD = 100
OVERTIME_MULT = Decimal("1.5")
DEPTH_TIER_LOW = Decimal("4.0")
SNOW_BASELINE_IN = Decimal("2.0")
SNOW_RATE_CENTS = 500
FERT_ADDON_CENTS = 2500
SNOW_SKIP_CREDIT_CENTS = 1500
DAYS_IN_BILLING_MONTH = Decimal("30")
LAWN_SKIP_DAYS = 3


def round_half_up(value):
    """Round a Decimal/number half-up to nearest integer."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def equipment_wear_score(equipment):
    hours_since = Decimal(str(equipment["cumulative_runtime_hours"])) - Decimal(
        str(equipment["runtime_at_last_service_hours"]))
    dispatch_since = Decimal(str(equipment["dispatch_count_since_service"]))
    age = Decimal(str(equipment["age_months"]))
    raw = W_HOURS * hours_since + W_DISPATCH * dispatch_since + W_AGE * age
    return round_half_up(raw)


def estimated_wear_score(equipment, in_flight_runtime_hours):
    """Forecast post-completion score: add the in-flight visit's runtime and +1 dispatch."""
    hours_since = (Decimal(str(equipment["cumulative_runtime_hours"]))
                   + Decimal(str(in_flight_runtime_hours))
                   - Decimal(str(equipment["runtime_at_last_service_hours"])))
    dispatch_since = Decimal(str(equipment["dispatch_count_since_service"])) + Decimal("1")
    age = Decimal(str(equipment["age_months"]))
    raw = W_HOURS * hours_since + W_DISPATCH * dispatch_since + W_AGE * age
    return round_half_up(raw)


def stop_minutes(base_service_minutes, travel_minutes, depth):
    d = Decimal(str(depth))
    if d <= 0:
        mult = Decimal("1.0")
    elif d < DEPTH_TIER_LOW:
        mult = Decimal("1.5")
    else:
        mult = Decimal("2.0")
    return round_half_up(Decimal(str(base_service_minutes)) * mult) + int(travel_minutes)


def route_dispatch_load(stops_ordered, depth, capacity):
    """stops_ordered: list of (base_service_minutes, travel_minutes) already ordered."""
    raw = 0
    for base, travel in stops_ordered:
        raw += stop_minutes(base, travel, depth)
    if raw > capacity:
        overage = raw - capacity
        load = capacity + round_half_up(Decimal(str(overage)) * OVERTIME_MULT)
    else:
        load = raw
    return load


def visit_surcharge(visit, fertilization_enabled):
    surcharge = 0
    if visit["service_type"] == "SNOW":
        over = Decimal(str(visit["snow_depth_in"])) - SNOW_BASELINE_IN
        if over > 0:
            whole = int(math.floor(over))
            if whole > 0:
                surcharge += whole * SNOW_RATE_CENTS
    if visit["service_type"] == "FERTILIZATION" or (
            visit["service_type"] == "LAWN" and fertilization_enabled):
        surcharge += FERT_ADDON_CENTS
    return surcharge


def skip_credit(visit, contract):
    if visit["service_type"] == "SNOW":
        return SNOW_SKIP_CREDIT_CENTS
    # LAWN or FERTILIZATION: prorated daily, round-per-day BEFORE multiply
    monthly = Decimal(str(contract["contract_price_cents"])) / Decimal(str(contract["term_months"]))
    daily = round_half_up(monthly / DAYS_IN_BILLING_MONTH)
    return daily * LAWN_SKIP_DAYS


def final_season_invoice(contract, completed_visits_ordered, approved_skips, customer):
    running = contract["contract_price_cents"]
    for v in completed_visits_ordered:
        running += v["surcharge_cents"]
    running -= sum(s["credit_cents"] for s in approved_skips)
    subtotal_cents = running
    tax_cents = round_half_up(Decimal(str(subtotal_cents)) * TAX_PCT)
    wallet_applied = min(customer["wallet_credit_cents"], subtotal_cents + tax_cents)
    total_due_cents = max(0, subtotal_cents + tax_cents - wallet_applied - contract["prepaid_deposit_cents"])
    return subtotal_cents, tax_cents, total_due_cents, wallet_applied
