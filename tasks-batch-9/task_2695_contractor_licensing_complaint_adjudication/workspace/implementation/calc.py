"""Pure calculations from PRD section 3 / SCAFFOLD calculations table.

Every money figure is integer cents.  Fractional rates live only inside these
functions and are applied with Decimal + ROUND_HALF_UP.
"""

import math
from datetime import timedelta
from decimal import Decimal

from core import rhu

# ---------------------------------------------------------------------------
# Statutory constants
# ---------------------------------------------------------------------------
EXAM_PASS_SCORE = 70
EXAM_VALIDITY_MONTHS = 48
EXPERIENCE_CEILING_MONTHS = 96
LICENSE_TERM_MONTHS = 24
DELINQUENT_GRACE_DAYS = 90
CE_SHORTFALL_GRACE_HOURS = 4
CE_HOURS_TERM_CEILING = 40
CE_SHORTFALL_CHARGE_CENTS = 5000
FUND_ASSESSMENT_THRESHOLD_CENTS = 100000
MAX_CONCURRENT_QUALIFICATIONS = 2
RMO_MIN_OWNERSHIP_PCT = 10
MAX_DEFICIENCY_ROUNDS = 3
MAX_MEDIATION_ROUNDS = 2
MEDIATION_WINDOW_DAYS = 30
STATUTE_OF_LIMITATIONS_MONTHS = 48
MIN_JURISDICTIONAL_LOSS_CENTS = 50000
APPEAL_WINDOW_DAYS = 15
JUDGMENT_RIPENING_DAYS = 90
STATUTORY_MAX_PENALTY_CENTS = 1500000

EDUCATION_CREDIT_MONTHS = {
    "NONE": 0,
    "APPRENTICESHIP": 12,
    "TWO_YEAR_DEGREE": 18,
    "FOUR_YEAR_DEGREE": 36,
}

SEVERITY_BASE_CENTS = {"MINOR": 50000, "SERIOUS": 250000, "EGREGIOUS": 750000}
SEVERITY_POINTS = {"MINOR": 1, "SERIOUS": 3, "EGREGIOUS": 6}
POSTURE_POINTS = {"COMPLIANT": 0, "CONDITIONAL": 1, "NON_COMPLIANT": 2}


# ---------------------------------------------------------------------------
# calculations.credited_experience_months
# ---------------------------------------------------------------------------
def credited_experience_months(verified_months, education_credential, min_experience_months):
    base = min(int(verified_months), EXPERIENCE_CEILING_MONTHS)
    raw_credit = EDUCATION_CREDIT_MONTHS.get(education_credential or "NONE", 0)
    ceiling = int(math.floor(min_experience_months * 0.5))
    allowed = min(raw_credit, ceiling)
    return min(base + allowed, EXPERIENCE_CEILING_MONTHS)


# ---------------------------------------------------------------------------
# calculations.bond_continuity_gap_days
# ---------------------------------------------------------------------------
def merge_intervals(intervals):
    """Merge half-open [start, end) date intervals; touching intervals merge."""
    spans = sorted([iv for iv in intervals if iv[0] < iv[1]])
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def bond_continuity_gap_days(window_start, window_end_inclusive, bond_spans):
    """Count calendar dates in the inclusive window covered by no bond span."""
    if window_end_inclusive < window_start:
        return 0
    total = (window_end_inclusive - window_start).days + 1
    win_end_exclusive = window_end_inclusive + timedelta(days=1)
    covered = 0
    for start, end in merge_intervals(bond_spans):
        lo = max(start, window_start)
        hi = min(end, win_end_exclusive)
        if hi > lo:
            covered += (hi - lo).days
    return total - covered


# ---------------------------------------------------------------------------
# calculations.renewal_fee (three ordered stages; rounded at each stage)
# ---------------------------------------------------------------------------
def renewal_fee(base_fee_cents, required_ce_hours, ce_hours_completed, delinquent):
    shortfall = required_ce_hours - ce_hours_completed
    if shortfall < 0:
        shortfall = 0
    whole_hours = int(math.floor(shortfall))
    stage1 = int(base_fee_cents) + whole_hours * CE_SHORTFALL_CHARGE_CENTS

    if delinquent:
        stage2 = stage1 + rhu(Decimal(stage1) * Decimal("0.5"))
    else:
        stage2 = stage1

    rate = Decimal("0.15") if stage2 >= FUND_ASSESSMENT_THRESHOLD_CENTS else Decimal("0.10")
    stage3 = stage2 + rhu(Decimal(stage2) * rate)
    return stage3


# ---------------------------------------------------------------------------
# calculations.citation_civil_penalty
# ---------------------------------------------------------------------------
def citation_civil_penalty(severity, subject_type, hazard_tier, prior_final_citation_count,
                           mitigation=False):
    base = Decimal(SEVERITY_BASE_CENTS[severity])
    subject = Decimal(2) if subject_type == "UNLICENSED" else Decimal(1)
    hazard = Decimal(1) + Decimal("0.25") * Decimal(int(hazard_tier) - 1)
    priors = min(int(prior_final_citation_count), 3)
    recidivism = Decimal(1) + Decimal("0.20") * Decimal(priors)
    mitig = Decimal("0.75") if mitigation else Decimal(1)
    product = base * subject * hazard * recidivism * mitig
    cents = rhu(product)
    return min(cents, STATUTORY_MAX_PENALTY_CENTS)


# ---------------------------------------------------------------------------
# calculations.sanction_points
# ---------------------------------------------------------------------------
def sanction_points(severity, prior_final_citation_count, posture, subject_type,
                    has_recovery_debt):
    points = SEVERITY_POINTS[severity]
    points += 2 * min(int(prior_final_citation_count), 3)
    if subject_type == "LICENSED" and posture is not None:
        points += POSTURE_POINTS.get(posture, 0)
    if subject_type == "UNLICENSED":
        points += 3
    if has_recovery_debt:
        points += 2
    return points


def sanction_tier(points):
    if points <= 2:
        return "LETTER_OF_REPRIMAND"
    if points <= 5:
        return "PROBATION"
    if points <= 8:
        return "SUSPENSION_30"
    if points <= 11:
        return "SUSPENSION_90"
    return "REVOCATION"


# ---------------------------------------------------------------------------
# calculations.recovery_award
# ---------------------------------------------------------------------------
def recovery_preliminary_estimate(claimed_amount_cents, per_claim_cap_cents):
    return min(int(claimed_amount_cents), int(per_claim_cap_cents))


def recovery_final_award(basis, claimed_amount_cents, judgment_amount_cents,
                         settlement_amount_cents, per_claim_cap_cents,
                         per_license_aggregate_cap_cents, recovery_encumbered_cents):
    if basis == "COURT_JUDGMENT":
        gross = min(int(claimed_amount_cents), int(judgment_amount_cents or 0))
    else:
        gross = int(claimed_amount_cents)
    net = gross - int(settlement_amount_cents or 0)
    if net < 0:
        net = 0
    net = min(net, int(per_claim_cap_cents))
    room = int(per_license_aggregate_cap_cents) - int(recovery_encumbered_cents)
    if room < 0:
        room = 0
    return min(net, room)


# ---------------------------------------------------------------------------
# calculations.recovery_prorata_distribution
# ---------------------------------------------------------------------------
def recovery_prorata_distribution(awards, balance_cents):
    """awards: list of awarded_amount_cents in created_at ASC cohort order."""
    total = sum(awards)
    if total <= 0:
        return [0 for _ in awards]
    if balance_cents >= total:
        return list(awards)
    shares = [(a * balance_cents) // total for a in awards]
    residual = balance_cents - sum(shares)
    i = 0
    while residual > 0 and shares:
        shares[i % len(shares)] += 1
        residual -= 1
        i += 1
    return shares
