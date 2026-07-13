"""Pure calculation functions (PRD 3.3, 3.5, 3.6, and response deadline)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# risk_score weights / constants
W_ISOLATION = 10
W_COGNITIVE = 12
W_FINANCIAL_VULN = 9
W_CAREGIVER_DEP = 8
W_PRIOR_REPORT = 4
PRIOR_REPORT_CAP = 5
SCORE_CAP = 100
HIGH_THRESHOLD = 70
MODERATE_THRESHOLD = 40

# response_deadline SLA (hours)
SLA_HOURS = {"EMERGENCY": 24, "PRIORITY": 72, "ROUTINE": 240}

# financial exposure threshold gating mandatory cross-report
MANDATORY_CROSS_REPORT_THRESHOLD_CENTS = 5000000


def risk_score(isolation, cognitive, financial_vuln, caregiver_dep, prior_report_count):
    """Returns (score, tier). Fixed order: raw -> cap -> tier. Integer arithmetic."""
    raw = (W_ISOLATION * isolation
           + W_COGNITIVE * cognitive
           + W_FINANCIAL_VULN * financial_vuln
           + W_CAREGIVER_DEP * caregiver_dep
           + W_PRIOR_REPORT * min(prior_report_count, PRIOR_REPORT_CAP))
    score = min(raw, SCORE_CAP)
    if score >= HIGH_THRESHOLD:
        tier = "HIGH"
    elif score >= MODERATE_THRESHOLD:
        tier = "MODERATE"
    else:
        tier = "LOW"
    return score, tier


def response_due_at(created_at, priority):
    return created_at + timedelta(hours=SLA_HOURS[priority])


def _round_half_up(numerator, denominator):
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(q)


def distribute_recovery(recovered, accounts):
    """Waterfall allocation (PRD 3.6).

    `accounts` must already be ordered by created_at ASC (insertion order tie-break;
    id never used). Returns {account_id: share_cents}. Per-account round_half_up first,
    then the remainder goes to the largest flagged_amount_cents (tie: earliest order).
    """
    total_flagged = sum(a["flagged_amount_cents"] for a in accounts)
    shares = {}
    if total_flagged > 0:
        for a in accounts:
            shares[a["id"]] = _round_half_up(recovered * a["flagged_amount_cents"], total_flagged)
    else:
        for a in accounts:
            shares[a["id"]] = 0
    remainder = recovered - sum(shares.values())
    # target: largest flagged_amount_cents; tie-break earliest (accounts already
    # ordered by created_at ASC, so first max wins).
    target = accounts[0]
    for a in accounts[1:]:
        if a["flagged_amount_cents"] > target["flagged_amount_cents"]:
            target = a
    shares[target["id"]] += remainder
    return shares
