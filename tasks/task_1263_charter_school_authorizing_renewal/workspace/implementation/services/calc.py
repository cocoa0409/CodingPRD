"""Calculation rules (SCAFFOLD §1.3 / PRD §2.6, §3).

All scores/indices: 1 decimal, ROUND_HALF_UP. Money: integer cents.
"""
from decimal import Decimal, ROUND_HALF_UP


def _d(value) -> Decimal:
    return Decimal(str(value))


def round1(value: Decimal) -> float:
    """Round to 1 decimal place, half-up; return as float for JSON."""
    q = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(q)


def round0(value: Decimal) -> int:
    """Round to integer, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# §1.3 application_composite_score
# ---------------------------------------------------------------------------
CRITERIA = ["ACADEMIC_PLAN", "FINANCE_PLAN", "GOVERNANCE", "OPERATIONS_PLAN", "COMMUNITY_SUPPORT"]
RUBRIC_WEIGHT = Decimal("0.6")
INTERVIEW_WEIGHT = Decimal("0.4")
APPROVAL_THRESHOLD = 75.0


def compute_rubric(review_scores):
    """Return (rubric_complete, rubric_score or None)."""
    per_criterion = {c: [] for c in CRITERIA}
    for entry in review_scores:
        per_criterion[entry["criterion"]].append(_d(entry["score"]))
    complete = all(len(v) >= 1 for v in per_criterion.values())
    if not complete:
        return False, None
    means = []
    for c in CRITERIA:
        vals = per_criterion[c]
        means.append(sum(vals) / Decimal(len(vals)))
    rubric = round1(sum(means) / Decimal(len(CRITERIA)))
    return True, rubric


def compute_composite(rubric_score, interview_score):
    """PROVISIONAL variant: composite == rubric_score (interview None).
    FINAL variant: 0.6*rubric + 0.4*interview, 1 decimal half-up.
    While the rubric is incomplete (rubric_score None) no composite can be
    formed; an interview scored early flips the variant to FINAL and the
    composite is recomputed once the rubric completes."""
    if rubric_score is None:
        return None, ("FINAL" if interview_score is not None else None)
    if interview_score is None:
        return rubric_score, "PROVISIONAL"
    final = RUBRIC_WEIGHT * _d(rubric_score) + INTERVIEW_WEIGHT * _d(interview_score)
    return round1(final), "FINAL"


# ---------------------------------------------------------------------------
# §1.3 monitoring_compliance_index
# ---------------------------------------------------------------------------
FAILING_BAND = 60
WEIGHT_ACADEMIC = Decimal("0.5")
WEIGHT_FINANCIAL = Decimal("0.25")
WEIGHT_OPERATIONAL = Decimal("0.25")


def compliance_index(academic, financial, operational) -> float:
    pairs = [
        (WEIGHT_ACADEMIC, _d(academic)),
        (WEIGHT_FINANCIAL, _d(financial)),
        (WEIGHT_OPERATIONAL, _d(operational)),
    ]
    weighted_sum = Decimal("0")
    weight_total = Decimal("0")
    for w, s in pairs:
        if s < FAILING_BAND:
            w = w * 2
        weighted_sum += w * s
        weight_total += w
    return round1(weighted_sum / weight_total)


# ---------------------------------------------------------------------------
# §1.3 standing_band_mapping — boundaries inclusive at lower edge
# ---------------------------------------------------------------------------
def standing_band(score) -> str:
    s = _d(score)
    if s >= Decimal("80.0"):
        return "GOOD"
    if s >= Decimal("65.0"):
        return "NOTICE"
    if s >= Decimal("50.0"):
        return "PROBATION"
    return "CRITICAL"


STANDING_LADDER = ["CRITICAL", "PROBATION", "NOTICE", "GOOD"]


def upgrade_one_step(standing: str) -> str:
    """Resolve side effect: upgrade exactly one step; GOOD unchanged."""
    idx = STANDING_LADDER.index(standing)
    return STANDING_LADDER[min(idx + 1, len(STANDING_LADDER) - 1)]


# ---------------------------------------------------------------------------
# §1.3 per_pupil_funding_total + authorizer_fee_billing
# ---------------------------------------------------------------------------
SMALL_CAP_CENTS = 200_000_000
MID_CAP_CENTS = 600_000_000
SUPP_SMALL = Decimal("0.12")
SUPP_MID = Decimal("0.08")
SUPP_LARGE = Decimal("0.05")

TIER1_MAX_ADM = 300
TIER2_MAX_ADM = 800
RATE_TIER1 = Decimal("0.025")
RATE_TIER2 = Decimal("0.020")
RATE_TIER3 = Decimal("0.015")


def supplemental_rate(base_funding_cents: int) -> Decimal:
    if base_funding_cents < SMALL_CAP_CENTS:
        return SUPP_SMALL
    if base_funding_cents <= MID_CAP_CENTS:
        return SUPP_MID
    return SUPP_LARGE


def fee_rate_for_adm(adm: int) -> Decimal:
    if adm <= TIER1_MAX_ADM:
        return RATE_TIER1
    if adm <= TIER2_MAX_ADM:
        return RATE_TIER2
    return RATE_TIER3


def compute_invoice_amounts(adm: int, base_per_pupil_cents: int, qualifying_supplemental_pupils: int):
    """Pinned evaluation order (base-first banding; per-month fee rounding)."""
    base_funding_cents = adm * base_per_pupil_cents
    supp_rate = supplemental_rate(base_funding_cents)
    supplemental_cents = round0(
        Decimal(qualifying_supplemental_pupils) * Decimal(base_per_pupil_cents) * supp_rate
    )
    total_funding_cents = base_funding_cents + supplemental_cents
    fee_rate = fee_rate_for_adm(adm)
    monthly_cents = round0(Decimal(total_funding_cents) * fee_rate / Decimal(12))
    billed_amount_cents = 12 * monthly_cents
    return {
        "base_funding_cents": base_funding_cents,
        "supplemental_cents": supplemental_cents,
        "total_funding_cents": total_funding_cents,
        "fee_rate": float(fee_rate),
        "billed_amount_cents": billed_amount_cents,
    }
