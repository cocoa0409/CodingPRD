"""The four calculation rules (PRD 2.6, 3.2, 3.4, 3.5, 3.7; scaffold 1.3).

All money is integer cents. Decimal + ROUND_HALF_UP everywhere a non-integer
intermediate is rounded; rounding is applied exactly where each rule specifies
and only there.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from timeutil import whole_months_between, ceil_months_between


def _round_half_up(value):
    """Round a Decimal/number half-up to a whole integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- #
# Calculation 1: asset_depreciation (straight-line, dual variant)             #
# --------------------------------------------------------------------------- #
def depreciation(asset, as_of, final=False):
    """Compute (accumulated_depreciation_cents, net_book_value_cents).

    Provisional (book) variant: whole months elapsed are floored — a partial
    final month does not count (PRD 3.2).
    Disposal (final) variant: a partial final month counts as a WHOLE month —
    ceil rather than floor (PRD 3.6).
    Both are capped at useful_life_months.

    Rounding (PRD 2.6 / scaffold): round_half_up applied ONCE to the accumulated
    product (straight_line_per_month * capped_months), never per month. The
    accumulated total is then clamped to the depreciable base, and net book
    value = purchase_cost - accumulated (>= salvage by construction).
    """
    purchase = asset["purchase_cost_cents"]
    salvage = asset["salvage_value_cents"]
    life = asset["useful_life_months"]
    in_service = asset["in_service_date"]

    depreciable_base = purchase - salvage

    if final:
        months = ceil_months_between(in_service, as_of)
    else:
        months = whole_months_between(in_service, as_of)
    months = max(0, min(months, life))

    # Exact monthly amount as a rational; round once to the product.
    per_month = Decimal(depreciable_base) / Decimal(life)
    accumulated = _round_half_up(per_month * Decimal(months))
    accumulated = min(accumulated, depreciable_base)
    if accumulated < 0:
        accumulated = 0
    net_book_value = purchase - accumulated
    return accumulated, net_book_value


# --------------------------------------------------------------------------- #
# Calculation 2: required_core_units (per-seat / per-core, frozen at create)  #
# --------------------------------------------------------------------------- #
def required_core_units(product, asset):
    """Units one install consumes once ACTIVE (PRD 3.4, frozen at create).

    PER_SEAT: always 1, regardless of cores.
    PER_CORE: max(min_core_units, ceil(physical_cores * core_factor)). The ceil
    is applied to the product BEFORE the minimum floor; core_factor may be
    fractional, so the ceil matters.
    """
    if product["license_model"] == "PER_SEAT":
        return 1
    cores = asset["physical_cores"]
    core_factor = product["core_factor"]
    min_units = product["min_core_units"]
    raw = math.ceil(cores * core_factor)
    return max(min_units, raw)


# --------------------------------------------------------------------------- #
# Calculation 3: renewal_cost (round-then-sum, order pinned)                  #
# --------------------------------------------------------------------------- #
def renewal_cost_entitlement(entitlement, extend_months, added_units):
    """Renewal cost for an ENTITLEMENT target (PRD 3.5).

    Two line items, EACH rounded half-up to whole cents BEFORE summing:
      line1 = round_half_up(entitled_units * unit_price_cents * extend_months/12)
      line2 = round_half_up(added_units    * unit_price_cents * extend_months/12)
      quoted_cost_cents = line1 + line2
    Rounding order is pinned; sum-then-round can differ by a cent.
    """
    unit_price = Decimal(entitlement["unit_price_cents"])
    fraction = Decimal(extend_months) / Decimal(12)
    line1 = _round_half_up(Decimal(entitlement["entitled_units"]) * unit_price * fraction)
    line2 = _round_half_up(Decimal(added_units) * unit_price * fraction)
    return line1 + line2


def renewal_cost_coverage(coverage, extend_months):
    """Renewal cost for a COVERAGE target: monthly_cost_cents * extend_months,
    rounded half-up (PRD 3.5)."""
    return _round_half_up(Decimal(coverage["monthly_cost_cents"]) * Decimal(extend_months))
