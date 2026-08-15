"""Calculations (SCAFFOLD calculations table; PRD sections 2.5-2.6 and 3.x).

All score/percentage arithmetic uses Decimal with round-half-up to exactly two
decimal places. Whole-day counts, screening scores and scholarship points are
integers. No float arithmetic anywhere.
"""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from middleware import touch

# --- record_book_score constants ---
W_COMPLETENESS = Decimal("0.30")
W_ACCURACY = Decimal("0.25")
W_FINANCIAL = Decimal("0.25")
W_REFLECTION = Decimal("0.20")
LEADERSHIP_BONUS = Decimal("5")
LATE_PENALTY_PER_DAY = 3
LATE_PENALTY_CAP = 15

# --- record_book_late_days constants ---
RECORD_BOOK_DEADLINE_DATE = date(2026, 7, 15)

# --- award_rubric_score constants ---
W_RECORD = Decimal("0.5")
W_PARTICIPATION = Decimal("0.3")
W_LEADERSHIP = Decimal("0.2")
LEADERSHIP_CAP = 20
TIER_GOLD = Decimal("85")
TIER_SILVER = Decimal("70")
TIER_BRONZE = Decimal("55")

# --- scholarship_points constants ---
BASE_POINTS = Decimal("7")
MULT_A = Decimal("1.5")
MULT_B = Decimal("1.2")
MULT_C = Decimal("1.0")

# --- member_eligibility_posture constants ---
ATTENDANCE_THRESHOLD_PCT = Decimal("75")
LIVESTOCK_TYPES = ("BEEF", "SHEEP", "SWINE")

# --- ownership_days constants ---
FAIR_ENTRY_DEADLINE = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
BEEF_MIN_OWNERSHIP_DAYS = 60
SHEEP_MIN_OWNERSHIP_DAYS = 30
SWINE_MIN_OWNERSHIP_DAYS = 30

# --- volunteer_screening_score constants ---
RISK_FLAG_PENALTY = 10
YEARS_BONUS = 2
CLEARANCE_THRESHOLD = 40


def q2(value):
    """Round-half-up to exactly two decimal places; returned as Decimal."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# volunteer_screening_score (PRD 3.2): pinned three-step order; the cap on
# credited service depends only on base_clearance, never on the score itself.
# ---------------------------------------------------------------------------
def volunteer_screening_score(base_clearance, risk_flags, years_service):
    years_cap = base_clearance // 10                      # (1) floor division
    effective_years = min(years_service, years_cap)       # (2)
    return base_clearance - risk_flags * RISK_FLAG_PENALTY + effective_years * YEARS_BONUS  # (3)


# ---------------------------------------------------------------------------
# record_book_late_days (PRD 3.5): whole calendar dates by which the UTC date
# of submitted_at falls after 2026-07-15; 0 when on or before it.
# ---------------------------------------------------------------------------
def record_book_late_days(submitted_at_dt):
    submitted_date = submitted_at_dt.astimezone(timezone.utc).date()
    return max(0, (submitted_date - RECORD_BOOK_DEADLINE_DATE).days)


# ---------------------------------------------------------------------------
# record_book_score (PRD 3.5)
#   provisional variant: plain weighted sum, no bonus, no penalty.
#   final variant, pinned order: weighted sum -> add leadership bonus and cap
#   at 100 -> subtract late penalty (3/late day, penalty capped at 15) -> floor 0.
# ---------------------------------------------------------------------------
def record_book_weighted_sum(completeness, accuracy, financial, reflection):
    return (Decimal(str(completeness)) * W_COMPLETENESS
            + Decimal(str(accuracy)) * W_ACCURACY
            + Decimal(str(financial)) * W_FINANCIAL
            + Decimal(str(reflection)) * W_REFLECTION)


def record_book_provisional_score(completeness, accuracy, financial, reflection):
    return q2(record_book_weighted_sum(completeness, accuracy, financial, reflection))


def record_book_final_score(weighted_sum, is_club_officer, late_days):
    bonus = LEADERSHIP_BONUS if is_club_officer else Decimal("0")
    capped = min(Decimal("100"), Decimal(weighted_sum) + bonus)
    penalty = Decimal(min(late_days * LATE_PENALTY_PER_DAY, LATE_PENALTY_CAP))
    return q2(max(Decimal("0"), capped - penalty))


# ---------------------------------------------------------------------------
# award_rubric_score (PRD 3.9):
#   leadership_norm = min(20, leadership_pts) / 20 * 100
#   rubric = 0.5*record_book_final + 0.3*participation_pct + 0.2*leadership_norm
#   tiers on the rounded score; boundaries inclusive (85.00 exactly is GOLD).
# ---------------------------------------------------------------------------
def award_rubric_score(record_book_final, participation_pct, leadership_pts):
    leadership_norm = Decimal(min(LEADERSHIP_CAP, leadership_pts)) / Decimal(20) * Decimal(100)
    raw = (Decimal(str(record_book_final)) * W_RECORD
           + Decimal(str(participation_pct)) * W_PARTICIPATION
           + leadership_norm * W_LEADERSHIP)
    score = q2(raw)
    if score >= TIER_GOLD:
        tier = "GOLD"
    elif score >= TIER_SILVER:
        tier = "SILVER"
    elif score >= TIER_BRONZE:
        tier = "BRONZE"
    else:
        tier = "NONE"
    return score, tier


# ---------------------------------------------------------------------------
# scholarship_points (PRD 3.9): per-project value rounded half-up to an integer
# FIRST, then summed. Sum-then-round is a rejected alternative.
#   A: 7 * 1.5 = 10.5 -> 11 ; B: 7 * 1.2 = 8.4 -> 8 ; C: 7 * 1.0 = 7
# ---------------------------------------------------------------------------
def scholarship_points(member_id):
    total = 0
    for project in db.table("projects").values():
        if project["member_id"] != member_id:
            continue
        if project["status"] != "COMPLETED":
            continue
        grade = project["grade"]
        mult = {"A": MULT_A, "B": MULT_B, "C": MULT_C}.get(grade)
        if mult is None:
            continue
        per_project = (BASE_POINTS * mult).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        total += int(per_project)
    return total


# ---------------------------------------------------------------------------
# member_eligibility_posture (PRD 3.7)
# ---------------------------------------------------------------------------
def member_attendance_pct(member_id):
    """PRESENT / (PRESENT + ABSENT) * 100, EXCUSED excluded from both. Returns
    None when the denominator is zero (threshold treated as not met)."""
    present = 0
    absent = 0
    for row in db.table("attendance").values():
        if row["member_id"] != member_id:
            continue
        if row["attendance_status"] == "PRESENT":
            present += 1
        elif row["attendance_status"] == "ABSENT":
            absent += 1
    denom = present + absent
    if denom == 0:
        return None
    return q2(Decimal(present) * Decimal(100) / Decimal(denom))


def member_has_approved_record_book(member_id):
    project_ids = {p["id"] for p in db.table("projects").values()
                   if p["member_id"] == member_id}
    return any(rb["project_id"] in project_ids and rb["status"] == "APPROVED"
               for rb in db.table("record_books").values())


def member_has_verified_tags(member_id):
    """Required only when the member carries at least one BEEF/SHEEP/SWINE
    project: every such livestock project must have >= 1 VERIFIED animal tag.
    Vacuously satisfied for members with no livestock projects."""
    livestock_ids = [p["id"] for p in db.table("projects").values()
                     if p["member_id"] == member_id
                     and p["project_type"] in LIVESTOCK_TYPES]
    if not livestock_ids:
        return True
    for pid in livestock_ids:
        if not any(t["project_id"] == pid and t["tagging_status"] == "VERIFIED"
                   for t in db.table("animal_tags").values()):
            return False
    return True


def compute_member_eligibility_posture(member_id):
    pct = member_attendance_pct(member_id)
    attendance_ok = pct is not None and pct >= ATTENDANCE_THRESHOLD_PCT
    book_ok = member_has_approved_record_book(member_id)
    tags_ok = member_has_verified_tags(member_id)
    if attendance_ok and book_ok and tags_ok:
        return "ELIGIBLE"
    if attendance_ok and (book_ok != tags_ok):
        return "CONDITIONAL"
    return "INELIGIBLE"


def recompute_member_posture(member, bump=True):
    """Event-driven recomputation (PRD 3.7). A derived-field change is a
    mutation: it advances the member's own version and updated_at (PRD 2.4).
    When the recompute is part of the member's own lifecycle transition the
    caller passes bump=False and applies the single declared increment itself."""
    new_posture = compute_member_eligibility_posture(member["id"])
    if new_posture != member["eligibility_posture"]:
        member["eligibility_posture"] = new_posture
        if bump:
            touch(member)


# ---------------------------------------------------------------------------
# ownership_days (PRD 3.8): primary animal = earliest-created VERIFIED tag on
# the project (tie-break: smallest created_at, then smallest tag_number
# lexicographically); whole days between owned_since and 2026-08-01T00:00:00Z.
# ---------------------------------------------------------------------------
def primary_animal_tag(project_id):
    verified = [t for t in db.table("animal_tags").values()
                if t["project_id"] == project_id and t["tagging_status"] == "VERIFIED"]
    if not verified:
        return None
    return min(verified, key=lambda t: (t["created_at"], t["tag_number"]))


def ownership_days_at_entry(project_id):
    primary = primary_animal_tag(project_id)
    if primary is None:
        return None
    owned_since = primary["_owned_since_dt"]
    delta = FAIR_ENTRY_DEADLINE - owned_since
    return int(delta.total_seconds() // 86400)


def species_min_ownership_days(species):
    return BEEF_MIN_OWNERSHIP_DAYS if species == "BEEF" else SWINE_MIN_OWNERSHIP_DAYS
