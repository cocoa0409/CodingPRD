"""Pricing calculations (PRD §3.8; calculations session_cost, idle_occupancy_fee,
roaming_settlement_total).

All monetary amounts are integer cents, rounded half up. kWh kept to 3 decimals
before the cents rounding.
"""
from decimal import Decimal

from validation import round_half_up, kwh_3


def idle_fee_cents(idle_minutes, tariff):
    """Idle/occupancy fee: max(0, idle_minutes - grace) * idle_fee_cents_per_min.

    Grace is inclusive: idle_minutes <= grace -> 0; fee applies strictly beyond.
    """
    grace = tariff["idle_grace_minutes"]
    billable = idle_minutes - grace
    if billable < 0:
        billable = 0
    return billable * tariff["idle_fee_cents_per_min"]


def energy_cost_cents(energy_delivered_kwh, tariff):
    """Tiered per-kWh energy cost, rounded half up to whole cents (PRD §3.8)."""
    k = kwh_3(energy_delivered_kwh)
    t1_max = Decimal(str(tariff["energy_tier_1_max_kwh"]))
    t2_max = Decimal(str(tariff["energy_tier_2_max_kwh"]))

    t1 = min(k, t1_max)
    t2 = min(max(k - t1_max, Decimal("0")), t2_max - t1_max)
    t3 = max(k - t2_max, Decimal("0"))

    raw = (t1 * Decimal(tariff["energy_rate_t1_cents"])
           + t2 * Decimal(tariff["energy_rate_t2_cents"])
           + t3 * Decimal(tariff["energy_rate_t3_cents"]))
    return round_half_up(raw)


def session_cost(session, tariff):
    """Return (total_cost_cents, idle_fee_cents) for a session per its tariff mode."""
    idle = idle_fee_cents(session["idle_minutes"], tariff)

    if tariff["pricing_mode"] == "ENERGY_BASED":
        variable = energy_cost_cents(session["energy_delivered_kwh"], tariff)
    else:  # TIME_BASED
        variable = session["charging_minutes"] * tariff["time_rate_cents_per_min"]

    total = variable + idle + tariff["session_fee_cents"]
    return total, idle


def commission_cents(gross_amount_cents, commission_pct):
    """round_half_up(gross * commission_pct)."""
    raw = Decimal(str(gross_amount_cents)) * Decimal(str(commission_pct))
    return round_half_up(raw)
