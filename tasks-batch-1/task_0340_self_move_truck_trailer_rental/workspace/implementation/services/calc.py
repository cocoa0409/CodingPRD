"""Calculation engines: reservation_quote, contract_settlement,
window-overlap, availability counts (PRD §3.5, §3.7, §3.8, §2.6/§2.8).

All money is integer cents. Rounding is round-half-up via Decimal.
"""
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---- Constants (SCAFFOLD §1.3) ----
ESTIMATED_ROUND_TRIP_MILES = 60
MILEAGE_DISCOUNT_BY_TIER = {"STANDARD": Decimal("0.00"),
                            "SILVER": Decimal("0.10"),
                            "GOLD": Decimal("0.20")}
ADDON_RATES = {"UTILITY_DOLLY": 700, "APPLIANCE_DOLLY": 1000, "FURNITURE_PAD_DOZEN": 500}

FUEL_PRICE_PER_GALLON_CENTS = 600
REFUEL_SERVICE_FEE_CENTS = 3000
LATE_GRACE_MINUTES = 119
LATE_FEE_PER_DAY_CENTS = 4000
SUPPLY_REFUND_PCT = Decimal("0.50")
TURNAROUND_HOURS = 3


def round_half_up(value):
    """Round a Decimal/number half-up to a whole integer (cents)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_iso(s):
    if s is None:
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ceil_days(start_dt, end_dt):
    """ceil((end - start) / 24h), minimum 1."""
    seconds = (end_dt - start_dt).total_seconds()
    if seconds <= 0:
        return 1
    days = math.ceil(seconds / (24 * 3600))
    return max(1, days)


# ===========================================================================
# Reservation quote (forward-looking estimate) — PRD §3.5
# ===========================================================================
def reservation_quote(reservation, klass, customer, coverage_plan, addon_rows, supply_rows):
    pickup = parse_iso(reservation["scheduled_pickup_at"])
    ret = parse_iso(reservation["scheduled_return_at"])
    planned_days = ceil_days(pickup, ret)

    base = klass["daily_rate_cents"] * planned_days

    if reservation["trip_type"] == "ONE_WAY":
        trip_component = klass["one_way_flat_cents"]
    else:
        if klass["category"] == "TRUCK":
            raw_mileage = klass["mileage_rate_cents"] * ESTIMATED_ROUND_TRIP_MILES
        else:
            raw_mileage = 0
        disc = MILEAGE_DISCOUNT_BY_TIER[customer["loyalty_tier"]]
        trip_component = round_half_up(Decimal(raw_mileage) * (Decimal(1) - disc))

    addons = sum(a["daily_rate_cents"] * a["quantity"] * planned_days for a in addon_rows)

    if reservation["coverage_choice"] == "SELECTED" and coverage_plan is not None:
        coverage = coverage_plan["daily_fee_cents"] * planned_days
    else:
        coverage = 0

    supplies = sum(s["unit_price_cents"] * s["quantity"] for s in supply_rows)

    return base + trip_component + addons + coverage + supplies


# ===========================================================================
# Contract settlement (chronological / actuals) — PRD §3.7
# Returns (settlement_total_cents, damage_charge_cents, ledger_components)
# ledger_components: ordered list of (kind, amount_cents)
# ===========================================================================
def contract_settlement(contract, reservation, klass, customer, coverage_plan,
                        addon_rows, supply_rows, damage_rows):
    pickup = parse_iso(reservation["scheduled_pickup_at"])
    actual_return = parse_iso(contract["actual_return_at"])
    scheduled_return = parse_iso(reservation["scheduled_return_at"])

    rental_days = ceil_days(pickup, actual_return)

    base = klass["daily_rate_cents"] * rental_days

    is_one_way = reservation["trip_type"] == "ONE_WAY"
    if is_one_way:
        trip_component = klass["one_way_flat_cents"]
        trip_kind = "ONE_WAY_FLAT"
    else:
        if klass["category"] == "TRUCK":
            raw_mileage = klass["mileage_rate_cents"] * contract["miles_driven"]
        else:
            raw_mileage = 0
        disc = MILEAGE_DISCOUNT_BY_TIER[customer["loyalty_tier"]]
        trip_component = round_half_up(Decimal(raw_mileage) * (Decimal(1) - disc))
        trip_kind = "MILEAGE"

    addons = sum(a["daily_rate_cents"] * a["quantity"] * rental_days for a in addon_rows)

    if reservation["coverage_choice"] == "SELECTED" and coverage_plan is not None:
        coverage = coverage_plan["daily_fee_cents"] * rental_days
    else:
        coverage = 0

    # Fuel shortfall
    missing_eighths = max(0, contract["pickup_fuel_eighths"] - contract["return_fuel_eighths"])
    if missing_eighths > 0:
        gallons_short = (Decimal(str(klass["fuel_capacity_gallons"])) / Decimal(8)) * Decimal(missing_eighths)
        fuel_shortfall = round_half_up(gallons_short * Decimal(FUEL_PRICE_PER_GALLON_CENTS)) + REFUEL_SERVICE_FEE_CENTS
    else:
        fuel_shortfall = 0

    # Late return
    late_seconds = (actual_return - scheduled_return).total_seconds()
    late_minutes = late_seconds / 60.0 if late_seconds > 0 else 0
    if late_minutes <= LATE_GRACE_MINUTES:
        late_days = 0
    else:
        late_days = math.ceil((late_minutes - LATE_GRACE_MINUTES) / (24 * 60))
    late_fee = late_days * LATE_FEE_PER_DAY_CENTS

    # Damage
    if contract["status"] == "RETURNED_DAMAGED":
        gross_damage = sum(d["assessed_cost_cents"] for d in damage_rows)
        if reservation["coverage_choice"] == "SELECTED" and coverage_plan is not None:
            damage_charge = max(0, gross_damage - coverage_plan["damage_deductible_cents"])
        else:
            damage_charge = gross_damage
    else:
        damage_charge = 0

    # Supplies net of returnable refunds
    supplies = sum(s["unit_price_cents"] * s["quantity"] for s in supply_rows)

    # Per-line refund: returnable lines, refunded_units == quantity, each rounded then summed.
    supply_refund = 0
    refund_assignments = []  # (supply_line_id, refunded_units)
    for s in supply_rows:
        # returnable flag was snapshotted onto the line at settlement evaluation
        if s.get("_returnable"):
            refunded_units = s["quantity"]
            refund_assignments.append((s["id"], refunded_units))
            per_line = round_half_up(Decimal(s["unit_price_cents"]) * Decimal(refunded_units) * SUPPLY_REFUND_PCT)
            supply_refund += per_line
        else:
            refund_assignments.append((s["id"], 0))

    settlement_total = (base + trip_component + addons + coverage
                        + fuel_shortfall + late_fee + damage_charge
                        + supplies - supply_refund)

    # Ordered ledger components (PRD §3.7 emission order).
    components = []
    components.append(("BASE_DAYS", base))
    components.append((trip_kind, trip_component))
    components.append(("ADDON", addons))
    components.append(("COVERAGE", coverage))
    components.append(("FUEL_SHORTFALL", fuel_shortfall))
    components.append(("LATE_RETURN", late_fee))
    if contract["status"] == "RETURNED_DAMAGED":
        components.append(("DAMAGE", damage_charge))
    components.append(("SUPPLY", supplies))
    if supply_refund > 0:
        components.append(("SUPPLY_REFUND", -supply_refund))

    return {
        "settlement_total_cents": settlement_total,
        "damage_charge_cents": damage_charge,
        "components": components,
        "refund_assignments": refund_assignments,
    }


# ===========================================================================
# Buffered reservation-window overlap — PRD §3.8
# ===========================================================================
def windows_overlap(r_pickup, r_return, o_pickup, o_return):
    """Half-open, right-extended by TURNAROUND_HOURS. Touch at buffered
    boundary does NOT overlap (strict <)."""
    buf = timedelta(hours=TURNAROUND_HOURS)
    return (r_pickup < (o_return + buf)) and (o_pickup < (r_return + buf))
