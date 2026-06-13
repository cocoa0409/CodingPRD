"""All calculation rules (SCAFFOLD §1.3 / PRD §2.7, §3).

Money is integer cents; non-integer intermediates rounded half-up ONCE at the
final step. We use Decimal + ROUND_HALF_UP, never float.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# ---- constants (from scaffold calculations.*.constants) ----
TIER1_CAP_CENTS = 1_000_000
TIER2_CAP_CENTS = 5_000_000
TIER1_FLOOR_BPS = 1000
TIER2_FLOOR_BPS = 800
TIER3_FLOOR_BPS = 600
MIN_PREMIUM_CENTS = 10_000

COVERAGE_PCT = {
    "LOW": Decimal("0.10"),
    "MEDIUM": Decimal("0.25"),
    "HIGH": Decimal("0.50"),
}

PROCESSING_FEE_CENTS = 2500
RECOVERY_CREDIT_CENTS = 50_000

MISSED_WEIGHT = 1
FAIL_BASE_WEIGHT = 2
GPS_FAIL_BONUS = 3

GRACE_PERIOD_DAYS = 30
DOCKET_BUFFER_MINUTES = 30
DEVICE_CAPACITY = 1


def _round_half_up(value):
    """Round a Decimal to the nearest integer, half-up. Returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def surety_premium(bail_amount_cents, premium_rate_bps):
    """Marginal tiered surety premium. Bands summed as exact integers*bps before
    the single division+round; then floored at MIN_PREMIUM_CENTS."""
    face = bail_amount_cents
    band1 = min(face, TIER1_CAP_CENTS)
    band2 = min(max(face - TIER1_CAP_CENTS, 0), TIER2_CAP_CENTS - TIER1_CAP_CENTS)
    band3 = max(face - TIER2_CAP_CENTS, 0)
    rate1 = max(premium_rate_bps, TIER1_FLOOR_BPS)
    rate2 = max(premium_rate_bps, TIER2_FLOOR_BPS)
    rate3 = max(premium_rate_bps, TIER3_FLOOR_BPS)
    # exact integer numerator (cents * bps), single division by 10000, round once
    numerator = band1 * rate1 + band2 * rate2 + band3 * rate3
    raw = Decimal(numerator) / Decimal(10000)
    rounded = _round_half_up(raw)
    return max(rounded, MIN_PREMIUM_CENTS)


def required_collateral(bond_type, bail_amount_cents, risk_tier):
    if bond_type == "PR":
        return 0
    if bond_type == "CASH":
        return bail_amount_cents
    # SURETY
    pct = COVERAGE_PCT[risk_tier]
    return _round_half_up(Decimal(bail_amount_cents) * pct)


def collateral_refund_amount(pledged_value_cents):
    """Per-item refund on exoneration: pledged minus flat processing fee, floored 0.
    LedgerEntry amount is the NEGATIVE of this."""
    return max(pledged_value_cents - PROCESSING_FEE_CENTS, 0)


def judgment_amount(bail_amount_cents, liquidated_collateral_cents, passed_recovery_open):
    """NET judgment, sequential: face - liquidated, then (if recovery opened)
    minus recovery credit, floored at 0."""
    net = bail_amount_cents - liquidated_collateral_cents
    if passed_recovery_open:
        net = max(net - RECOVERY_CREDIT_CENTS, 0)
    else:
        net = max(net, 0)
    return net


def remission_credit(judgment_amount_cents, remission_pct):
    """judgment * pct / 100, round half up once. remission_pct may be int/float/Decimal."""
    raw = Decimal(judgment_amount_cents) * Decimal(str(remission_pct)) / Decimal(100)
    return _round_half_up(raw)


def compliance_weight(result, condition_code):
    if result == "PASS":
        return 0
    if result == "MISSED":
        return MISSED_WEIGHT
    if result == "FAIL":
        return FAIL_BASE_WEIGHT + (GPS_FAIL_BONUS if condition_code == "GPS" else 0)
    return 0


def notification_lead_hours(scheduled_dt, now_dt):
    """Whole hours from now to scheduled, floored. Negative if past (floor toward -inf)."""
    delta_seconds = (scheduled_dt - now_dt).total_seconds()
    return math.floor(delta_seconds / 3600)
