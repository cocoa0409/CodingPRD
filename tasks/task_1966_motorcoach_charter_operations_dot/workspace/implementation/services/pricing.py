"""Pricing, deposit, cancellation, fuel surcharge, breakdown compensation calcs."""

import math
from decimal import Decimal, ROUND_HALF_UP


OVERNIGHT_RATE_PER_NIGHT_CENTS = 25000
RELIEF_DRIVER_FLAT_CENTS = 45000
ADA_SURCHARGE_PCT = Decimal("0.05")
TAX_RATE = Decimal("0.0825")

VEHICLE_CLASS_RATES = {
    "STANDARD": {"mileage_rate_cents": 250, "hourly_rate_cents": 15000, "included_hours": 5, "included_miles": 100},
    "PREMIUM": {"mileage_rate_cents": 350, "hourly_rate_cents": 20000, "included_hours": 5, "included_miles": 100},
    "EXECUTIVE": {"mileage_rate_cents": 500, "hourly_rate_cents": 30000, "included_hours": 5, "included_miles": 100},
}

MAINTENANCE_INTERVAL_MILES = 10000


def round_half_up_cents(value) -> int:
    """Round a numeric to integer cents using ROUND_HALF_UP."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value) -> float:
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def compute_requires_overnight(estimated_hours: float, trip_date, return_date) -> bool:
    if estimated_hours > 10:
        return True
    # crosses midnight?
    if trip_date is not None and return_date is not None:
        if trip_date.date() != return_date.date():
            return True
    return False


def compute_requires_relief_driver(estimated_hours: float) -> bool:
    # single-driver HOS driving limit is 11 hours
    return estimated_hours > 11.0


def calc_quote_pricing(quote: dict, customer: dict) -> dict:
    estimated_miles = quote["estimated_miles"]
    estimated_hours = float(quote["estimated_hours"])

    ratio = estimated_miles / estimated_hours if estimated_hours else 0.0
    variant = "MILEAGE_PRIMARY" if ratio >= 55.0 else "HOURLY_PRIMARY"

    rate_table = VEHICLE_CLASS_RATES[quote["vehicle_class_requested"]]
    mileage_rate_cents = rate_table["mileage_rate_cents"]
    hourly_rate_cents = rate_table["hourly_rate_cents"]

    if variant == "MILEAGE_PRIMARY":
        base_cents = estimated_miles * mileage_rate_cents
        hours_credit_cents = 0
        if estimated_hours > rate_table["included_hours"]:
            extra_billable_hours = Decimal(str(estimated_hours - rate_table["included_hours"]))
            hours_credit_cents = round_half_up_cents(extra_billable_hours * Decimal(hourly_rate_cents) * Decimal("0.5"))
        subtotal_before_fees = base_cents + hours_credit_cents
    else:
        base_cents = round_half_up_cents(Decimal(str(estimated_hours)) * Decimal(hourly_rate_cents))
        miles_credit_cents = 0
        if estimated_miles > rate_table["included_miles"]:
            extra_billable_miles = estimated_miles - rate_table["included_miles"]
            miles_credit_cents = round_half_up_cents(Decimal(extra_billable_miles) * Decimal(mileage_rate_cents) * Decimal("0.5"))
        subtotal_before_fees = base_cents + miles_credit_cents

    overnight_fee_cents = 0
    if quote["requires_overnight"]:
        num_nights = math.ceil(estimated_hours / 24.0)
        overnight_fee_cents = num_nights * OVERNIGHT_RATE_PER_NIGHT_CENTS

    relief_driver_fee_cents = 0
    if quote["requires_relief_driver"]:
        relief_driver_fee_cents = RELIEF_DRIVER_FLAT_CENTS

    ada_surcharge_cents = 0
    if quote.get("ada_required"):
        ada_surcharge_cents = round_half_up_cents(Decimal(subtotal_before_fees) * ADA_SURCHARGE_PCT)

    subtotal_cents = subtotal_before_fees + overnight_fee_cents + relief_driver_fee_cents + ada_surcharge_cents

    if customer.get("tax_exempt"):
        tax_cents = 0
    else:
        tax_cents = round_half_up_cents(Decimal(subtotal_cents) * TAX_RATE)

    total_cents = subtotal_cents + tax_cents

    return {
        "pricing_variant": variant,
        "mileage_rate_cents": mileage_rate_cents,
        "hourly_rate_cents": hourly_rate_cents,
        "overnight_fee_cents": overnight_fee_cents,
        "relief_driver_fee_cents": relief_driver_fee_cents,
        "subtotal_cents": subtotal_cents,
        "tax_cents": tax_cents,
        "total_cents": total_cents,
    }


def calc_deposit_tier(total_cents: int, trip_date, now) -> int:
    lead = (trip_date - now).total_seconds() / 3600.0
    if lead >= 720:
        pct = Decimal("0.10")
    elif lead >= 336:
        pct = Decimal("0.25")
    elif lead >= 168:
        pct = Decimal("0.50")
    elif lead >= 48:
        pct = Decimal("0.75")
    else:
        pct = Decimal("1.00")
    return round_half_up_cents(Decimal(total_cents) * pct)


def calc_cancellation_fee(deposit_paid_cents: int, trip_date, now) -> tuple:
    """Returns (fee_cents, refund_cents)."""
    lead = (trip_date - now).total_seconds() / 3600.0
    if lead >= 720:
        pct = Decimal("0.0")
    elif lead >= 336:
        pct = Decimal("0.10")
    elif lead >= 168:
        pct = Decimal("0.25")
    elif lead >= 72:
        pct = Decimal("0.50")
    elif lead >= 24:
        pct = Decimal("0.75")
    else:
        pct = Decimal("1.00")
    fee = round_half_up_cents(Decimal(deposit_paid_cents) * pct)
    refund = deposit_paid_cents - fee
    return fee, refund


def calc_fuel_surcharge(actual_miles: int, quoted_subtotal_cents: int) -> int:
    if actual_miles <= 100:
        return 0
    elif actual_miles <= 300:
        return round_half_up_cents(Decimal(quoted_subtotal_cents) * Decimal("0.03"))
    elif actual_miles <= 600:
        return round_half_up_cents(Decimal(quoted_subtotal_cents) * Decimal("0.05"))
    else:
        return round_half_up_cents(Decimal(quoted_subtotal_cents) * Decimal("0.08"))


def calc_breakdown_compensation(delay_minutes: int, quoted_subtotal_cents: int, deposit_paid_cents: int) -> int:
    if delay_minutes < 60:
        c = 0
    elif delay_minutes < 120:
        c = round_half_up_cents(Decimal(quoted_subtotal_cents) * Decimal("0.05"))
    elif delay_minutes < 240:
        c = round_half_up_cents(Decimal(quoted_subtotal_cents) * Decimal("0.10"))
    elif delay_minutes < 480:
        c = round_half_up_cents(Decimal(quoted_subtotal_cents) * Decimal("0.20"))
    else:
        c = round_half_up_cents(Decimal(quoted_subtotal_cents) * Decimal("0.35"))
    return min(c, deposit_paid_cents)


def calc_hos_feasibility(driver: dict, trip_hours: float, requires_relief_driver: bool):
    """Returns (ok, error_id_or_None)."""
    if requires_relief_driver:
        return True, None
    max_driving = 11.0 - float(driver.get("current_driving_hours_today", 0.0))
    if trip_hours > max_driving:
        return False, "ERR_HOS_DRIVING_LIMIT"
    max_on_duty = 14.0 - float(driver.get("current_on_duty_hours_today", 0.0))
    if trip_hours > max_on_duty:
        return False, "ERR_HOS_ON_DUTY_WINDOW"
    cycle_limit = 70.0 if driver.get("hos_cycle_type") == "CYCLE_70_8" else 60.0
    remaining_cycle = cycle_limit - float(driver.get("current_cycle_hours", 0.0))
    if trip_hours > remaining_cycle:
        return False, "ERR_HOS_CYCLE_LIMIT"
    return True, None
