"""Domain thresholds and rate constants from the PRD.

All monetary amounts are integer cents (PRD §2.6). Rates are basis points
over a denominator of ten thousand (PRD §2.6: "8,500 basis points means
85 percent"). Rounding is floor-to-whole-cent, applied exactly once after
the multiplication and division (PRD §2.6).

NOTE: the standing holdback lag constant HOLDBACK_LAG_QUARTERS is named in
PRD §3.6 but its numeric value is never stated, so no constant for it is
defined here and no test may assert a specific release quarter.
"""

BPS_DENOMINATOR = 10000  # PRD §2.6

# Pass-through split rates by commitment level (PRD §3.6).
PLATINUM_PASS_THROUGH_BPS = 8500
STANDARD_PASS_THROUGH_BPS = 7500
BUILDER_PASS_THROUGH_BPS = 6500

PASS_THROUGH_BPS_BY_LEVEL = {
    "PLATINUM": PLATINUM_PASS_THROUGH_BPS,
    "STANDARD": STANDARD_PASS_THROUGH_BPS,
    "BUILDER": BUILDER_PASS_THROUGH_BPS,
}

# Holdback variant rates (PRD §3.6).
FLAT_HOLDBACK_BPS = 1000        # ten percent flat withholding
RISK_HOLDBACK_BPS = 2500        # elevated band for members at/above threshold
MATERIAL_FINDING_THRESHOLD = 2  # inclusive: exactly 2 triggers elevated rate


def apply_bps(amount_cents: int, rate_bps: int) -> int:
    """floor(amount * rate_bps / 10000) — the PRD's single-rounding rule."""
    return (amount_cents * rate_bps) // BPS_DENOMINATOR


def resolve_tier(tier_schedule, eligible_qty: int):
    """Return the applicable tier per PRD §3.3: the last tier whose min_qty
    is <= eligible_qty (inclusive); a synthetic {min_qty:0, rate_bps:0} tier
    when the quantity falls below even the first tier's min_qty."""
    applicable = {"min_qty": 0, "rate_bps": 0}
    for tier in tier_schedule:
        if eligible_qty >= tier["min_qty"]:
            applicable = tier
        else:
            break
    return applicable


def expected_rebate_cents(tier_schedule, eligible_qty: int, eligible_cents: int) -> int:
    """Tier resolution + single floor rounding (PRD §3.3)."""
    tier = resolve_tier(tier_schedule, eligible_qty)
    return apply_bps(eligible_cents, tier["rate_bps"])


# Standard 3-tier schedule used by many scenarios:
#   qty>=0 -> 200bps, qty>=100 -> 500bps, qty>=500 -> 800bps
TIER_SCHEDULE_T1 = [
    {"min_qty": 0, "rate_bps": 200},
    {"min_qty": 100, "rate_bps": 500},
    {"min_qty": 500, "rate_bps": 800},
]

TEST_DEFAULTS = {
    "COOP_NAME": "TestCoop",
    "MEMBER_LEGAL_NAME": "Member Co",
    "SUPPLIER_LEGAL_NAME": "Supplier Co",
    "PROGRAM_CODE": "PROG-1",
    "REPORT_QTY": 120,
    "REPORT_CENTS": 200000,
}
