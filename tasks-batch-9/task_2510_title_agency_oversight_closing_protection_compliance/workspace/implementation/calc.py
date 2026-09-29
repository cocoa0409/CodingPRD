"""Every calculation of PRD Sections 2.5 - 3.9, in integer cents.

Money is never touched by a float: products of cents by a factor are formed as
exact rationals (Decimal / Fraction) and then rounded half up, except for the
four closing-protection coverage caps which floor (PRD 2.5, 3.3).
"""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from fractions import Fraction

# ---------------------------------------------------------------------------
# constants (SCAFFOLD 1.3 / PRD 3.x)
# ---------------------------------------------------------------------------
MIN_EO_LIMIT_CENTS = 25000000
MIN_NET_WORTH_CENTS = 5000000

AUDIT_SPACING_DAYS = 90

REMITTANCE_GRACE_DAYS = 15
LATE_FILING_FEE_CENTS = 25000
UNREPORTED_PENALTY_PCT = Decimal("0.10")

WEIGHT_CRITICAL_FINDING = 25
WEIGHT_HIGH_FINDING = 12
WEIGHT_ADVERSE_CLOSURE = 8
WEIGHT_DEFALCATION_CLAIM = 15
SCORE_CAP = 100
DEFALCATION_RISK_THRESHOLD = 60
ESCROW_WATCH_THRESHOLD = 30

DEFALCATION_WINDOW_DAYS = 365

POSTURE_UNREMITTED_LIMIT_CENTS = 50000000
POSTURE_UNREPORTED_POLICY_LIMIT = 3

CPL_SCOPE_FACTOR = {
    "FULL_SETTLEMENT": Decimal("1.00"),
    "LENDER_ONLY": Decimal("0.80"),
    "SELLER_PROCEEDS": Decimal("0.60"),
}
CPL_RESTRICTED_POSTURE_FACTOR = Decimal("0.50")
CPL_EO_SUBLIMIT_FACTOR = Decimal("0.50")

CLAIM_PARTICIPATION = {
    "TIER_1": Decimal("0.50"),
    "TIER_2": Decimal("0.75"),
    "TIER_3": Decimal("1.00"),
}
CLAIM_CAUSE_FACTOR = {
    "AGENCY_ERROR": Decimal("0.60"),
    "SEARCH_DEFECT": Decimal("0.40"),
    "UNDERWRITING_BREACH": Decimal("0.80"),
    "ESCROW_DEFALCATION": Decimal("1.00"),
}
CLAIM_TIER_1_MAX = Fraction(1, 4)   # 0.25 inclusive
CLAIM_TIER_2_MAX = Fraction(3, 5)   # 0.60 inclusive

SEVERITY_LADDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


# ---------------------------------------------------------------------------
# rounding primitives
# ---------------------------------------------------------------------------
def to_decimal(value):
    """Exact decimal for a JSON number, avoiding binary float artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(cents, factor):
    """cents * factor as an exact rational, rounded half up to whole cents."""
    product = Decimal(int(cents)) * to_decimal(factor)
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_mul(cents, factor):
    """cents * factor with any fraction of a cent discarded downward."""
    product = Decimal(int(cents)) * to_decimal(factor)
    return int(product.quantize(Decimal("1"), rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# escrow three-way variance (PRD 3.6)
# ---------------------------------------------------------------------------
def adjusted_bank_balance(bank_balance_cents, outstanding_items_cents):
    return int(bank_balance_cents) - int(outstanding_items_cents)


def variance_method_for(audit_type):
    return "STRICT_THREE_WAY" if audit_type == "SURPRISE" else "BANK_TO_TRIAL"


def reconciliation_variance(method, adjusted_bank, book, trial):
    if method == "STRICT_THREE_WAY":
        return max(
            abs(adjusted_bank - book),
            abs(adjusted_bank - trial),
            abs(book - trial),
        )
    return abs(adjusted_bank - trial)


# ---------------------------------------------------------------------------
# finding severity (PRD 3.7)
# ---------------------------------------------------------------------------
def base_severity(code, exposure_cents):
    exposure = int(exposure_cents)
    if code == "THREE_WAY_VARIANCE":
        if exposure <= 100000:
            return "LOW"
        if exposure <= 1000000:
            return "MEDIUM"
        if exposure <= 5000000:
            return "HIGH"
        return "CRITICAL"
    if code == "UNIDENTIFIED_FUNDS_AGED":
        return "MEDIUM" if exposure <= 500000 else "HIGH"
    if code == "NEGATIVE_FILE_BALANCE":
        return "HIGH"
    if code == "MISSING_RECONCILIATION":
        return "MEDIUM"
    if code == "COMMINGLING":
        return "CRITICAL"
    return "LOW"


def escalate_severity(severity):
    idx = SEVERITY_LADDER.index(severity)
    if idx >= len(SEVERITY_LADDER) - 1:
        return SEVERITY_LADDER[-1]
    return SEVERITY_LADDER[idx + 1]


def effective_severity(base, is_repeat):
    return escalate_severity(base) if is_repeat else base


# ---------------------------------------------------------------------------
# defalcation score / escrow standing (PRD 3.7)
# ---------------------------------------------------------------------------
def defalcation_score(critical_findings, high_findings, adverse_closures, defalcation_claims):
    raw = (
        WEIGHT_CRITICAL_FINDING * critical_findings
        + WEIGHT_HIGH_FINDING * high_findings
        + WEIGHT_ADVERSE_CLOSURE * adverse_closures
        + WEIGHT_DEFALCATION_CLAIM * defalcation_claims
    )
    return min(SCORE_CAP, raw)


def escrow_standing_for(score):
    if score >= DEFALCATION_RISK_THRESHOLD:
        return "DEFALCATION_RISK"
    if score >= ESCROW_WATCH_THRESHOLD:
        return "WATCH"
    return "COMPLIANT"


# ---------------------------------------------------------------------------
# oversight posture (PRD 2.6)
# ---------------------------------------------------------------------------
def oversight_posture(agency):
    if agency["appointment_status"] in ("SUSPENDED", "TERMINATED"):
        return "FROZEN"
    if agency["escrow_standing"] == "DEFALCATION_RISK":
        return "FROZEN"
    if agency["appointment_status"] == "PENDING_REVIEW":
        return "RESTRICTED"
    if agency["financial_review_status"] != "ACCEPTED":
        return "RESTRICTED"
    if agency["escrow_standing"] == "WATCH":
        return "RESTRICTED"
    if agency["open_critical_finding_count"] >= 1:
        return "RESTRICTED"
    if agency["unreported_policy_count"] >= POSTURE_UNREPORTED_POLICY_LIMIT:
        return "RESTRICTED"
    if agency["unremitted_premium_cents"] > POSTURE_UNREMITTED_LIMIT_CENTS:
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# closing protection letters (PRD 3.3)
# ---------------------------------------------------------------------------
def cpl_referral_reason(complex_title_flag, requested_coverage_cents,
                        counsel_referral_threshold_cents,
                        underwriting_authority_limit_cents, posture):
    """Fixed order, evaluation stops at the first match."""
    if complex_title_flag:
        return "COMPLEX_TITLE"
    if requested_coverage_cents > counsel_referral_threshold_cents:
        return "STATE_REFERRAL_THRESHOLD"
    if requested_coverage_cents > underwriting_authority_limit_cents:
        return "AUTHORITY_LIMIT"
    if posture == "RESTRICTED":
        return "RESTRICTED_POSTURE"
    return None


def cpl_approved_coverage(requested_coverage_cents, coverage_scope,
                          cpl_coverage_cap_cents, posture, eo_policy_limit_cents):
    scope_factor = CPL_SCOPE_FACTOR[coverage_scope]
    state_cap = floor_mul(cpl_coverage_cap_cents, scope_factor)
    if posture == "OPEN":
        posture_cap = state_cap
    else:
        posture_cap = floor_mul(state_cap, CPL_RESTRICTED_POSTURE_FACTOR)
    eo_sublimit = floor_mul(eo_policy_limit_cents, CPL_EO_SUBLIMIT_FACTOR)
    return min(int(requested_coverage_cents), state_cap, posture_cap, eo_sublimit)


# ---------------------------------------------------------------------------
# policy files (PRD 3.4)
# ---------------------------------------------------------------------------
def policy_referral_required(complex_title_flag, liability_amount_cents,
                            underwriting_authority_limit_cents,
                            counsel_referral_threshold_cents):
    if complex_title_flag:
        return True
    if liability_amount_cents > underwriting_authority_limit_cents:
        return True
    if liability_amount_cents > counsel_referral_threshold_cents:
        return True
    return False


def issuance_landing(elapsed_days, policy_issuance_deadline_days):
    return "ISSUED" if elapsed_days <= policy_issuance_deadline_days else "LATE_ISSUED"


# ---------------------------------------------------------------------------
# remittance (PRD 3.5)
# ---------------------------------------------------------------------------
def line_split(reported_gross_premium_cents, premium_split_agency_pct):
    """Retention is rounded first; the underwriter share is the remainder."""
    retention = round_half_up(reported_gross_premium_cents, premium_split_agency_pct)
    share = int(reported_gross_premium_cents) - retention
    return retention, share


def late_fee(unreported_premium_cents, filing_late):
    filing_fee = LATE_FILING_FEE_CENTS if filing_late else 0
    penalty = round_half_up(unreported_premium_cents, UNREPORTED_PENALTY_PCT)
    return filing_fee + penalty


# ---------------------------------------------------------------------------
# claims (PRD 3.8)
# ---------------------------------------------------------------------------
def recourse_tier(loss_amount_cents, eo_policy_limit_cents):
    ratio = Fraction(int(loss_amount_cents), int(eo_policy_limit_cents))
    if ratio <= CLAIM_TIER_1_MAX:
        return "TIER_1"
    if ratio <= CLAIM_TIER_2_MAX:
        return "TIER_2"
    return "TIER_3"


def claim_waterfall(loss_amount_cents, eo_policy_limit_cents, cause_code):
    """Returns (tier, indemnity_offset, recourse_amount, net_exposure)."""
    tier = recourse_tier(loss_amount_cents, eo_policy_limit_cents)
    indemnity = round_half_up(loss_amount_cents, CLAIM_PARTICIPATION[tier])
    indemnity = min(indemnity, int(eo_policy_limit_cents))
    recourse = round_half_up(indemnity, CLAIM_CAUSE_FACTOR[cause_code])
    net = int(loss_amount_cents) - indemnity
    return tier, indemnity, recourse, net
