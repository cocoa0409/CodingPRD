"""Domain thresholds and derived expectations from PRD rules."""

THRESHOLDS = {
    # Gear serviceability gates (PRD §2.8)
    "MIN_CONDITION_SCORE": 40,
    "MAX_RENTAL_DAYS_SINCE_SERVICE": 30,
    "TRANSIT_BUFFER_DAYS": 1,
    # Deposit tiers, in cents of replacement value (PRD §3.3)
    "DEPOSIT_TIER1_CAP": 200_000,
    "DEPOSIT_TIER2_CAP": 300_000,
    # Insurance surcharge gate (PRD §3.3 / §3.9)
    "INSURANCE_RISK_THRESHOLD": 50,
    # Commission bounds in basis points (PRD §3.8)
    "COMMISSION_BPS_DENOMINATOR": 10_000,
}

# Zone multiplier geography (PRD §3.3): same city 1.00, same region 1.10,
# cross-region 1.25.
REGION_WEST = {"LAX", "SFO", "SEA", "PDX"}
REGION_NORTHEAST = {"NYC", "BOS", "PHI", "DC"}
REGION_MIDSOUTH = {"NASH", "ATL", "MEM"}
REGIONS = (REGION_WEST, REGION_NORTHEAST, REGION_MIDSOUTH)

# Damage severity impact on condition_score (PRD §3.7)
CONDITION_IMPACT = {
    "COSMETIC": 5,
    "MINOR": 15,
    "MAJOR": 35,
    "TOTAL_LOSS": 100,
}

# Risk-score severity weights and 90-day recency doubling (PRD §3.1)
RISK_WEIGHTS = {
    "COSMETIC": 2,
    "MINOR": 5,
    "MAJOR": 12,
    "TOTAL_LOSS": 30,
}
RISK_RECENCY_WINDOW_DAYS = 90
RISK_CAP = 100

TEST_DEFAULTS = {
    "DAILY_RATE_CENTS": 10_000,
    "REPLACEMENT_VALUE_CENTS": 100_000,
    "CAPACITY_KG": 500,
    "HOME_CITY": "LAX",
    "STOP_CITY": "LAX",
    "WEIGHT_KG": 10,
    "LABOR_MINUTES": 10,
    "VENDOR_RATE_CENTS_PER_DAY": 70_000,
    "COMMISSION_BPS": 1_000,
}


def expected_deposit_hold(replacement_value_cents: int) -> int:
    """Tiered deposit hold per PRD §3.3: 20% of the first 200,000 cents,
    15% of the next 300,000, 10% beyond 500,000, rounded half-up once."""
    rv = replacement_value_cents
    raw = (
        0.20 * min(rv, THRESHOLDS["DEPOSIT_TIER1_CAP"])
        + 0.15 * min(max(rv - THRESHOLDS["DEPOSIT_TIER1_CAP"], 0), THRESHOLDS["DEPOSIT_TIER2_CAP"])
        + 0.10 * max(rv - 500_000, 0)
    )
    return _round_half_up(raw)


def zone_multiplier(origin_city: str, dest_city: str) -> float:
    """Cartage zone multiplier per PRD §3.3."""
    if origin_city == dest_city:
        return 1.00
    for region in REGIONS:
        if origin_city in region and dest_city in region:
            return 1.10
    return 1.25


def expected_quoted_fee(daily_rate_cents: int, days: int, origin_city: str,
                        dest_city: str, risk_score: int) -> int:
    """Provisional quote per PRD §3.3: per-component half-up rounding."""
    days = max(1, days)
    base = daily_rate_cents * days
    cartage = _round_half_up(base * (zone_multiplier(origin_city, dest_city) - 1.0))
    insurance = _round_half_up(base * 0.08) if risk_score >= THRESHOLDS["INSURANCE_RISK_THRESHOLD"] else 0
    return base + cartage + insurance


def _round_half_up(value) -> int:
    """Round half away from zero for the non-negative money values used here."""
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
