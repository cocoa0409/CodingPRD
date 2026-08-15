"""Calculation rules (SCAFFOLD §1.3 / PRD §2.8, §3.7, §3.8).

All monetary amounts are integer cents; every monetary computation rounds
half-up to 0 decimal places. net_bushels (a quantity, not money) rounds
half-up to one decimal place.
"""

from decimal import Decimal, ROUND_HALF_UP


# --- Constants from scaffold §1.3 ---
TIER1_BUSHELS = Decimal("10000")
VOLUME_DISCOUNT_FACTOR = Decimal("0.9")

SURCHARGE_THRESHOLD = Decimal("0.10")
SURCHARGE_PASS_THROUGH = Decimal("0.5")

MOISTURE_BASE_PCT = Decimal("15.0")
SHRINK_PER_TENTH = Decimal("0.001")
MAX_SHRINK = Decimal("0.20")
MOISTURE_DISCOUNT_PER_TENTH_CENTS = 200

HAULING_RATE_CENTS_PER_BUSHEL = 12


def _dec(value):
    """Exact Decimal conversion for int/float/str inputs."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def round_half_up_cents(value):
    """Round to whole cents (0 dp), ROUND_HALF_UP, returned as int."""
    return int(_dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    """Round to one decimal place, ROUND_HALF_UP, returned as float."""
    q = _dec(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(q)


def excess_tenths(moisture_pct):
    """round_half_up((moisture_pct - 15.0) * 10) as an integer."""
    d = (_dec(moisture_pct) - MOISTURE_BASE_PCT) * Decimal(10)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def moisture_shrink_factor(moisture_pct):
    """Per-bushel shrink factor applied at ticket write time.

    moisture <= 15.0 → 1.0. Otherwise 1 - excess_tenths*0.001, floored at
    1 - MAX_SHRINK = 0.80.
    """
    m = _dec(moisture_pct)
    if m <= MOISTURE_BASE_PCT:
        return Decimal("1.0")
    et = excess_tenths(m)
    factor = Decimal("1.0") - Decimal(et) * SHRINK_PER_TENTH
    floor = Decimal("1.0") - MAX_SHRINK
    if factor < floor:
        factor = floor
    return factor


def compute_net_bushels(gross_bushels, moisture_pct):
    factor = moisture_shrink_factor(moisture_pct)
    return round_half_up_1dp(_dec(gross_bushels) * factor)


def compute_hauling_add_on_cents(gross_bushels, used_our_trucks):
    if used_our_trucks:
        return round_half_up_cents(
            _dec(gross_bushels) * Decimal(HAULING_RATE_CENTS_PER_BUSHEL)
        )
    return 0


def settlement_base_amount(contract, tickets):
    """Tiered pricing per §1.3 settlement_base_amount.

    A = contract.harvested_acres (sum of actual_acres over COMPLETED stops
    at issue time). NB = sum of ticket.net_bushels over all tickets.
    """
    if contract["rate_basis"] == "PER_ACRE":
        a = _dec(contract.get("harvested_acres", 0))
        return round_half_up_cents(a * _dec(contract["rate_cents_per_acre"]))
    # PER_BUSHEL
    nb = Decimal("0")
    for t in tickets:
        nb += _dec(t.get("net_bushels", 0))
    rate = _dec(contract["rate_cents_per_bushel"])
    if nb <= TIER1_BUSHELS:
        return round_half_up_cents(nb * rate)
    tier1 = TIER1_BUSHELS * rate
    tier2 = (nb - TIER1_BUSHELS) * rate * VOLUME_DISCOUNT_FACTOR
    return round_half_up_cents(tier1 + tier2)


def fuel_surcharge_cents(season, base_amount_cents):
    """delta_pct >= 0.10 (inclusive) triggers the surcharge."""
    baseline = _dec(season["diesel_baseline_per_gallon_cents"])
    current = _dec(season["current_diesel_per_gallon_cents"])
    if baseline <= 0:
        return 0
    delta_pct = (current - baseline) / baseline
    if delta_pct < SURCHARGE_THRESHOLD:
        return 0
    return round_half_up_cents(
        Decimal(base_amount_cents) * delta_pct * SURCHARGE_PASS_THROUGH
    )


def moisture_discount_cents(contract, tickets):
    """Only for PER_ACRE; 200 cents per excess tenth per affected ticket."""
    if contract["rate_basis"] != "PER_ACRE":
        return 0
    discount = 0
    for t in tickets:
        if _dec(t["moisture_pct"]) > MOISTURE_BASE_PCT:
            discount += MOISTURE_DISCOUNT_PER_TENTH_CENTS * excess_tenths(
                t["moisture_pct"]
            )
    return discount


def settlement_total(base, fuel, hauling, moisture):
    """base + fuel + hauling - moisture, floored at 0. Hauling added before
    moisture is subtracted so the discount cannot erode hauling recovery."""
    total = base + fuel + hauling - moisture
    return total if total > 0 else 0
