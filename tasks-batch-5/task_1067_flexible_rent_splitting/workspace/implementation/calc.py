"""Calculation rules (PRD §3.2, §3.4, §3.7, §3.8, §3.9)."""
from decimal import Decimal, ROUND_HALF_UP

# Underwriting constants
W_RATIO = Decimal("0.5")
W_SPLIT = Decimal("0.2")
W_DELINQ = Decimal("0.3")
LIMIT_MULT = {"LOW": 3, "MEDIUM": 2, "HIGH": 1}
INCOME_LIMIT_PCT = Decimal("0.5")
DECLINE_SCORE_THRESHOLD = 50
MIN_RATIO = Decimal("1.5")

# Installment schedule constants
SPLIT_STEP_DAYS = {2: 14, 3: 10, 4: 7}
MIN_SPLIT_COUNT = 2
MAX_SPLIT_COUNT = 4
MIN_INSTALLMENT_GAP_DAYS = 5
MAX_DEFER_DAYS = 25

# Flex fee constants
MEMBERSHIP_FEE_BY_BAND = {"LOW": 1500, "MEDIUM": 2500, "HIGH": 4000}
PER_EXTRA_SPLIT_FEE_CENTS = 500
DEFER_DAILY_BPS = 30

# Late fee / delinquency constants
GRACE_DAYS = 5
LATE_FEE_FLAT_CENTS = 2500
LATE_FEE_ROUND_CENTS = 1000
SETTLEMENT_ADMIN_FEE_CENTS = 1500
RECOVERY_MIN_DAYS = 30
PROMISE_MAX_DAYS = 14

# Retry / attempts
MAX_ATTEMPTS = 3


def round_half_up(dec_value):
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Underwriting risk score (§3.2)
# ---------------------------------------------------------------------------
def underwrite(income_cents, portion_cents, requested_split_count, prior_delinq):
    ratio = Decimal(income_cents) / Decimal(portion_cents)
    if ratio >= Decimal("3.0"):
        ratio_score = 100
    elif ratio >= Decimal("2.0"):
        ratio_score = 70
    elif ratio >= Decimal("1.5"):
        ratio_score = 40
    else:
        ratio_score = 10

    if requested_split_count <= 2:
        split_score = 100
    elif requested_split_count == 3:
        split_score = 70
    else:
        split_score = 40

    if prior_delinq == 0:
        delinq_score = 100
    elif prior_delinq == 1:
        delinq_score = 60
    else:
        delinq_score = 20

    risk_score = round_half_up(
        W_RATIO * ratio_score + W_SPLIT * split_score + W_DELINQ * delinq_score)

    if risk_score >= 75:
        risk_band = "LOW"
    elif risk_score >= 50:
        risk_band = "MEDIUM"
    else:
        risk_band = "HIGH"

    band_ceiling = portion_cents * LIMIT_MULT[risk_band]
    income_ceiling = round_half_up(Decimal(income_cents) * INCOME_LIMIT_PCT)
    approved_limit = min(band_ceiling, income_ceiling)

    return {
        "ratio": ratio,
        "risk_score": risk_score,
        "risk_band": risk_band,
        "approved_limit_cents": approved_limit,
    }


# ---------------------------------------------------------------------------
# Flex fee (§3.7)
# ---------------------------------------------------------------------------
def flex_fee(risk_band, mode, split_count, deferred_amount_cents, defer_days):
    membership = MEMBERSHIP_FEE_BY_BAND[risk_band]
    split_component = max(0, split_count - 1) * PER_EXTRA_SPLIT_FEE_CENTS
    if mode == "DEFER":
        defer_carry = round_half_up(
            Decimal(deferred_amount_cents) * DEFER_DAILY_BPS * defer_days / Decimal(10000))
    else:
        defer_carry = 0
    return membership + split_component + defer_carry


# ---------------------------------------------------------------------------
# Installment schedule allocation (§3.4)
# ---------------------------------------------------------------------------
def split_amounts(portion_cents, n):
    base = portion_cents // n
    remainder = portion_cents - base * n
    return [base + (1 if k <= remainder else 0) for k in range(1, n + 1)]
