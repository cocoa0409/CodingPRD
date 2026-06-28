"""Contraindication score (PRD §3.5 / scaffold calc contraindication_score).

Weighted sum of active flags; +10 when patient is >= 70 at start_at.
G6PD flag only counts when the booked drip is g6pd_sensitive.
Outcome tiers: >=60 BLOCKED, 40..59 REQUIRES_MD_REVIEW, <40 CLEARED.
"""

W_PREGNANCY = 40
W_RENAL = 30
W_CARDIAC = 25
W_G6PD = 35
W_ADVERSE = 20
W_AGE = 10
BLOCK_THRESHOLD = 60
REVIEW_THRESHOLD = 40


def _age_over_70(date_of_birth, start_at):
    """True iff elapsed time from date_of_birth to start_at is >= 70 years.

    Uses calendar-year arithmetic against the logical start_at instant.
    """
    years = start_at.year - date_of_birth.year
    # Subtract a year if start_at has not yet reached the birth month/day.
    if (start_at.month, start_at.day, start_at.hour, start_at.minute,
            start_at.second, start_at.microsecond) < (
            date_of_birth.month, date_of_birth.day, date_of_birth.hour,
            date_of_birth.minute, date_of_birth.second, date_of_birth.microsecond):
        years -= 1
    return years >= 70


def compute_score(screening, menu_item, patient, start_at):
    score = 0
    if screening["pregnancy"]:
        score += W_PREGNANCY
    if screening["renal_impairment"]:
        score += W_RENAL
    if screening["cardiac_history"]:
        score += W_CARDIAC
    if screening["recent_adverse_event"]:
        score += W_ADVERSE
    if screening["g6pd_deficiency"] and menu_item["g6pd_sensitive"]:
        score += W_G6PD
    if _age_over_70(patient["date_of_birth"], start_at):
        score += W_AGE
    return score


def outcome_for(score):
    if score >= BLOCK_THRESHOLD:
        return "BLOCKED"
    if score >= REVIEW_THRESHOLD:
        return "REQUIRES_MD_REVIEW"
    return "CLEARED"
