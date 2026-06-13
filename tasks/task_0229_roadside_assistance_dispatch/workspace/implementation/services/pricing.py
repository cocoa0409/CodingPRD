"""Tiered pricing with pinned rounding regime (PRD §2.6, §3.5, §3.8)."""
from decimal import Decimal, ROUND_HALF_UP


def _round_half_up(value, places):
    q = Decimal(1).scaleb(-places)  # 10^-places
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


def tow_overage_cents(miles, cap_miles, rate_cents_per_mile):
    """Pinned 3-step regime:
      1. overage_miles = max(0, miles - cap); round to 3 decimals (half-up)
      2. multiply by rate
      3. round product to whole cents (half-up)
    """
    overage_miles = Decimal(str(miles)) - Decimal(str(cap_miles))
    if overage_miles < 0:
        overage_miles = Decimal(0)
    overage_miles_r = overage_miles.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    product = overage_miles_r * Decimal(str(rate_cents_per_mile))
    cents = product.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def service_cost_cents(plan, service_type, miles):
    """base (if uncovered) + tow overage (TOW only)."""
    covered = service_type in plan["covered_service_types"]
    base = 0 if covered else int(plan["base_service_fee_cents"])
    if service_type == "TOW":
        overage = tow_overage_cents(
            miles,
            plan["per_incident_mileage_cap_miles"],
            plan["overage_rate_cents_per_mile"],
        )
    else:
        overage = 0
    return base + overage
