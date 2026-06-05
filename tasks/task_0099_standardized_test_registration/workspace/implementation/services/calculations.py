"""All calculation rules (SCAFFOLD §1.3, PRD §3).

Money/fractional cents use Decimal with ROUND_HALF_UP. Never float.
"""
from decimal import Decimal

from services.common import round_half_up_cents, D, parse_test_date_start_utc

# --- Constants ---
SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600

# tiered_refund (SCAFFOLD §1.3 / PRD §3.7)
FULL_REFUND_DAYS = 60
PARTIAL_75_DAYS = 14
PARTIAL_50_DAYS = 1
PCT_75 = Decimal("0.75")
PCT_50 = Decimal("0.50")

# standby_promotion_score (SCAFFOLD §1.3 / PRD §3.6)
TIER_WEIGHT = {"FEE_WAIVER": 300, "SCHOOL_DAY": 200, "GENERAL": 100}
RECENCY_CAP_HOURS = 48

# allotted_minutes (SCAFFOLD §1.3 / PRD §3.5)
BASE_MINUTES = {"SAT": 134, "ACT": 175, "AP": 180}
TIME_MULTIPLIER = {
    "EXTENDED_TIME_50": Decimal("1.5"),
    "EXTENDED_TIME_100": Decimal("2.0"),
    "SEPARATE_ROOM": Decimal("1.0"),
    "BREAKS_ONLY": Decimal("1.0"),
}

# clep_credit (SCAFFOLD §1.3 / PRD §3.9)
CLEP_PASS_THRESHOLD = 50

# rest separation (SCAFFOLD validation 11 / PRD §3.5)
REST_BUFFER_HOURS = 3

# exam section sets
SAT_SECTIONS = ["READING_WRITING", "MATH"]
ACT_SECTIONS = ["ENGLISH", "MATH", "READING", "SCIENCE"]


# ---------------------------------------------------------------------------
# sitting_composite
# ---------------------------------------------------------------------------
def sitting_composite(exam_type, section_scores):
    """Composite for THIS sitting only (SCAFFOLD sitting_composite)."""
    if exam_type == "SAT":
        return int(section_scores["READING_WRITING"] + section_scores["MATH"])
    elif exam_type == "ACT":
        total = (section_scores["ENGLISH"] + section_scores["MATH"]
                 + section_scores["READING"] + section_scores["SCIENCE"])
        # round_half_up(mean of four)
        return round_half_up_cents(D(total) / D(4))
    raise ValueError(f"Unsupported exam_type for sitting_composite: {exam_type}")


# ---------------------------------------------------------------------------
# super_score: per-section max across qualifying sittings, THEN composite.
# ---------------------------------------------------------------------------
def super_composite(exam_type, qualifying_reports):
    """qualifying_reports: list of ScoreReport dicts (RELEASED, same candidate+exam)."""
    if not qualifying_reports:
        return None
    sections = SAT_SECTIONS if exam_type == "SAT" else ACT_SECTIONS
    best = {}
    for sec in sections:
        vals = []
        for r in qualifying_reports:
            ss = r.get("section_scores") or {}
            if sec in ss and ss[sec] is not None:
                vals.append(ss[sec])
        if vals:
            best[sec] = max(vals)
        else:
            best[sec] = 0
    if exam_type == "SAT":
        return int(best["READING_WRITING"] + best["MATH"])
    elif exam_type == "ACT":
        total = best["ENGLISH"] + best["MATH"] + best["READING"] + best["SCIENCE"]
        return round_half_up_cents(D(total) / D(4))
    raise ValueError(f"Unsupported exam_type for super_composite: {exam_type}")


# ---------------------------------------------------------------------------
# tiered_refund
# ---------------------------------------------------------------------------
def days_before(test_date_str, clock_now):
    """floor((test_date 00:00:00Z - clock_now) / 86400 seconds)."""
    test_start = parse_test_date_start_utc(test_date_str)
    delta_seconds = (test_start - clock_now).total_seconds()
    # floor toward negative infinity
    import math
    return math.floor(delta_seconds / SECONDS_PER_DAY)


def tiered_refund(amount_paid_cents, test_date_str, clock_now):
    """Returns (tier_label, refund_cents)."""
    db = days_before(test_date_str, clock_now)
    if db >= FULL_REFUND_DAYS:
        return "FULL", int(amount_paid_cents)
    elif db >= PARTIAL_75_DAYS:
        return "PARTIAL_75", round_half_up_cents(D(amount_paid_cents) * PCT_75)
    elif db >= PARTIAL_50_DAYS:
        return "PARTIAL_50", round_half_up_cents(D(amount_paid_cents) * PCT_50)
    else:
        return "NONE", 0


# ---------------------------------------------------------------------------
# standby_promotion_score
# ---------------------------------------------------------------------------
def standby_promotion_score(priority_tier, created_at_dt, clock_now):
    """TIER_WEIGHT + min(floor(waited_hours), 48), bounded >= 0."""
    import math
    tier_weight = TIER_WEIGHT[priority_tier]
    waited_seconds = (clock_now - created_at_dt).total_seconds()
    waited_hours = math.floor(waited_seconds / SECONDS_PER_HOUR)
    recency_bonus = min(waited_hours, RECENCY_CAP_HOURS)
    recency_bonus = max(recency_bonus, 0)
    return tier_weight + recency_bonus


# ---------------------------------------------------------------------------
# allotted_minutes
# ---------------------------------------------------------------------------
def allotted_minutes(exam_type, accommodation_type=None):
    """floor(BASE_MINUTES[exam] * multiplier). No accommodation -> base (mult 1.0)."""
    base = BASE_MINUTES[exam_type]
    if accommodation_type is None:
        mult = Decimal("1.0")
    else:
        mult = TIME_MULTIPLIER[accommodation_type]
    import math
    return math.floor(Decimal(base) * mult)


# ---------------------------------------------------------------------------
# ap_fee_settlement: round each line then sum (pinned order).
# ---------------------------------------------------------------------------
def ap_fee_settlement(line_base_fees, fee_reduction_pct):
    """line_base_fees: list of base_fee_cents per line item.
    Apply reduction per line, round_half_up each line, THEN sum.
    """
    pct = D(fee_reduction_pct)
    total = 0
    for base in line_base_fees:
        per_line = round_half_up_cents(D(base) * (Decimal("1") - pct))
        total += per_line
    return total


# ---------------------------------------------------------------------------
# id_verification
# ---------------------------------------------------------------------------
def id_verification(presented_first, presented_last, presented_id_state,
                    center_state, legal_first, legal_last):
    """Returns (cross_state: bool, outcome: 'MATCH'|'MISMATCH')."""
    cross_state = (presented_id_state != center_state)
    if cross_state:
        name_exact = (presented_first == legal_first and presented_last == legal_last)
        outcome = "MATCH" if name_exact else "MISMATCH"
    else:
        name_ci = (presented_first.lower() == legal_first.lower()
                   and presented_last.lower() == legal_last.lower())
        outcome = "MATCH" if name_ci else "MISMATCH"
    return cross_state, outcome


# ---------------------------------------------------------------------------
# clep_credit
# ---------------------------------------------------------------------------
def clep_credit(clep_scaled_score):
    """Recommended credit hours from scaled score (ACE step schedule)."""
    if clep_scaled_score < 50:
        return 0
    elif clep_scaled_score < 60:
        return 3
    elif clep_scaled_score < 70:
        return 6
    else:
        return 9
