"""Calculation rules (SCAFFOLD §1.3 / PRD §3).

All money is integer cents; Decimal with ROUND_HALF_UP everywhere except the
pinned exceptions (mission allocation lines round HALF_DOWN; hours 2dp HALF_UP).
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

# ---- calc_provisional_item_value constants ----
CATEGORY_FMV_CENTS = {
    "CLOTHING": 800,
    "FURNITURE": 4500,
    "ELECTRONICS": 3000,
    "HOUSEWARES": 1200,
    "BOOKS_MEDIA": 300,
    "TOYS": 600,
    "COLLECTIBLES": 5000,
}
CONDITION_VALUE_MULT = {
    "NEW_WITH_TAGS": Decimal("1.0"),
    "GOOD": Decimal("0.7"),
    "FAIR": Decimal("0.4"),
    "POOR": Decimal("0.15"),
}

# ---- calc_suggested_price constants ----
CONDITION_PRICE_MULT = {
    "NEW_WITH_TAGS": Decimal("1.0"),
    "GOOD": Decimal("0.8"),
    "FAIR": Decimal("0.6"),
    "POOR": Decimal("0.35"),
}
MIN_PRICE_CENTS = 100
MAX_PRICE_CENTS = 500000
COLLECTIBLES_MULT_FLOOR = Decimal("1.2")

# ---- calc_markdown_price constants ----
MARKDOWN_OFF = {
    1: Decimal("0.25"),
    2: Decimal("0.50"),
    3: Decimal("0.75"),
}
MAX_MARKDOWN_ROUND = 3
HOLD_HOURS = 72

# ---- calc_bale_revenue constants ----
DEFAULT_EST_RATE_CENTS = {"TEXTILES": 12, "PAPER": 6, "EWASTE": 3, "BULK": 2}
BALE_MIN_SEAL_LBS = 100.0

# ---- calc_till_reconciliation constants ----
AUTO_RECONCILE_MAX_CENTS = 500

# ---- calc_shrink_rate constants ----
SHRINK_ALERT_BP = 300

# ---- calc_mission_pool constants ----
RESERVE_TIER_1_MAX_CENTS = 100000
RESERVE_TIER_2_MAX_CENTS = 500000
RESERVE_PCT_T1 = 10
RESERVE_PCT_T2 = 15
RESERVE_PCT_T3 = 20

# ---- calc_transitional_hours constants ----
WEEKLY_CAP_HOURS = Decimal("20.0")
DEFAULT_PROGRAM_CAP_HOURS = 480

# Receipt thresholds (PRD §3.9)
APPRAISAL_THRESHOLD_CENTS = 500000
ITEMIZED_THRESHOLD_CENTS = 25000
ADDRESS_THRESHOLD_CENTS = 50000

# Shrink-alert high-value pricing gate (PRD §3.3)
HIGH_VALUE_PRICE_CENTS = 10000

DONOR_FREQUENT_THRESHOLD = 10

# Category -> salvage mapping and average weights.
# The PRD/scaffold reference these tables symbolically (CATEGORY_TO_SALVAGE,
# CATEGORY_AVG_WEIGHT_LBS) without enumerating values; the only pinned example
# is CLOTHING -> TEXTILES (difficulty-design markdown_pull_cascade). The
# remaining rows follow standard thrift-stream practice.
CATEGORY_TO_SALVAGE = {
    "CLOTHING": "TEXTILES",
    "BOOKS_MEDIA": "PAPER",
    "ELECTRONICS": "EWASTE",
    "FURNITURE": "BULK",
    "HOUSEWARES": "BULK",
    "TOYS": "BULK",
    "COLLECTIBLES": "BULK",
}
CATEGORY_AVG_WEIGHT_LBS = {
    "CLOTHING": 1.0,
    "FURNITURE": 50.0,
    "ELECTRONICS": 10.0,
    "HOUSEWARES": 5.0,
    "BOOKS_MEDIA": 2.0,
    "TOYS": 3.0,
    "COLLECTIBLES": 5.0,
}


def _d(x):
    return Decimal(str(x))


def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calc_provisional_item_value(category, condition):
    raw = _d(CATEGORY_FMV_CENTS[category]) * CONDITION_VALUE_MULT[condition]
    return round_half_up_cents(raw)


def calc_suggested_price(category, condition, guideline):
    mult = CONDITION_PRICE_MULT[condition]
    if category == "COLLECTIBLES":
        mult = max(mult, COLLECTIBLES_MULT_FLOOR)
    raw = _d(guideline["base_cents"]) * mult * _d(guideline["demand_multiplier"])
    clamped = min(max(raw, Decimal(MIN_PRICE_CENTS)), Decimal(MAX_PRICE_CENTS))
    return round_half_up_cents(clamped)


def calc_markdown_price(base_price_cents, entering_round):
    off = MARKDOWN_OFF[entering_round]
    return round_half_up_cents(_d(base_price_cents) * (Decimal("1") - off))


def bale_estimate_pre_seal(category, weight_lbs):
    return round_half_up_cents(_d(weight_lbs) * DEFAULT_EST_RATE_CENTS[category])


def _vendor_brackets(vendor, category):
    for sheet in vendor.get("rates", []):
        if sheet.get("category") == category:
            return sheet.get("brackets", [])
    return None


def bale_estimate_post_seal(vendor, category, weight_lbs):
    """Average-rate-at-tier: the single bracket whose range contains the total
    weight, applied to the whole weight, rounded half up once."""
    brackets = _vendor_brackets(vendor, category)
    w = _d(weight_lbs)
    lower = Decimal("0")
    for br in brackets:
        up_to = br.get("up_to_lbs")
        if up_to is None or w <= _d(up_to):
            return round_half_up_cents(w * _d(br["rate_cents_per_lb"]))
        lower = _d(up_to)
    # weight beyond last bounded bracket (defensive; final bracket should be null)
    return round_half_up_cents(w * _d(brackets[-1]["rate_cents_per_lb"]))


def bale_settlement(vendor, category, actual_weight_lbs):
    """Marginal bracket walk; per-bracket lines rounded half up FIRST, then summed."""
    brackets = _vendor_brackets(vendor, category)
    remaining = _d(actual_weight_lbs)
    lower = Decimal("0")
    total = 0
    for br in brackets:
        if remaining <= 0:
            break
        up_to = br.get("up_to_lbs")
        if up_to is None:
            width = remaining
        else:
            width = _d(up_to) - lower
            if width < 0:
                width = Decimal("0")
        lbs = min(remaining, width)
        total += round_half_up_cents(lbs * _d(br["rate_cents_per_lb"]))
        remaining -= lbs
        if up_to is not None:
            lower = _d(up_to)
    return total


def calc_reserve_pct(gross_pool_cents):
    if gross_pool_cents < RESERVE_TIER_1_MAX_CENTS:
        return RESERVE_PCT_T1
    if gross_pool_cents < RESERVE_TIER_2_MAX_CENTS:
        return RESERVE_PCT_T2
    return RESERVE_PCT_T3


def calc_mission_pool(gross_pool_cents, allocations):
    """Pinned evaluation order (PRD §3.9): tier keyed on gross, reserve half-up,
    allocation lines half-DOWN, remainder to the LAST line in request order."""
    reserve_pct = calc_reserve_pct(gross_pool_cents)
    reserve_cents = round_half_up_cents(
        _d(gross_pool_cents) * _d(reserve_pct) / Decimal("100"))
    net_pool = gross_pool_cents - reserve_cents
    amounts = []
    for line in allocations:
        amt = int((_d(net_pool) * _d(line["pct"]) / Decimal("100"))
                  .quantize(Decimal("1"), rounding=ROUND_DOWN))
        amounts.append({"program": line["program"], "pct": line["pct"],
                        "amount_cents": amt})
    remainder = net_pool - sum(a["amount_cents"] for a in amounts)
    if amounts:
        amounts[-1]["amount_cents"] += remainder
    return reserve_pct, reserve_cents, net_pool, amounts


def shift_duration_hours(shift):
    """Hours at 2 decimal places, round half up."""
    from db import parse_ts
    start = parse_ts(shift["starts_at"])
    end = parse_ts(shift["ends_at"])
    secs = Decimal(str((end - start).total_seconds()))
    hrs = (secs / Decimal("3600")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(hrs)


def calc_shrink_rate_bp(shrink_value_cents, gross_sales_cents):
    denom = shrink_value_cents + gross_sales_cents
    if denom == 0:
        return 0
    return round_half_up_cents(_d(shrink_value_cents) * Decimal("10000") / _d(denom))
