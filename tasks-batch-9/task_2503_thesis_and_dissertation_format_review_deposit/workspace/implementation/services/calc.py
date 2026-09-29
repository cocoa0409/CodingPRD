"""Every declared calculation (SCAFFOLD section 1.3 / PRD sections 2.7, 3.4-3.8)."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import lookup
from timeutil import add_business_days, add_months, business_days_between

# ------------------------------------------------------------------ constants

W_CRITICAL = Decimal("3.4")
W_MAJOR = Decimal("1.65")
W_MINOR = Decimal("0.35")
DENSITY_BASE_PAGES = Decimal(100)
MIN_DENSITY_PAGES = 50
REVISION_MANDATORY_THRESHOLD = Decimal("12.00")

CYCLE1_WINDOW_BDAYS = 10
CYCLE2_WINDOW_BDAYS = 7
CYCLE3_PLUS_WINDOW_BDAYS = 5
LONG_DOC_BONUS_BDAYS = 2
LONG_DOC_PAGE_THRESHOLD = 300

DOCTORAL_MIN_MEMBERS = 5
DOCTORAL_MIN_EXTERNAL = 1
MASTERS_MIN_MEMBERS = 3
MAX_CHAIR_LOAD = 4

MIN_DEFENSE_MINUTES = 30
MAX_DEFENSE_MINUTES = 240

FLAG_THRESHOLD_PCT = Decimal("18.00")

W_ABSTRACT = Decimal("0.30")
W_KEYWORDS = Decimal("0.20")
W_ADVISOR = Decimal("0.15")
W_DEPARTMENT = Decimal("0.15")
W_DEGREE_LEVEL = Decimal("0.10")
W_DOCUMENT_TYPE = Decimal("0.10")
TOTAL_WEIGHT = Decimal("1.00")
ABSTRACT_MIN_WORDS = 150
KEYWORDS_MIN_COUNT = 3
METADATA_MIN_SCORE = Decimal("0.8500")

GRACE_HIGH_TURNAROUND_BDAYS = 15
GRACE_HIGH_BDAYS = 5
GRACE_MID_TURNAROUND_BDAYS = 10
GRACE_MID_BDAYS = 3
DAILY_LATE_FEE_CENTS = 2500
LATE_FEE_CAP_CENTS = 50000

FAIR_USE_MAX_WORDS = 400

EMBARGO_CAPS_DOCTORAL = {
    "PATENT_PENDING": 24,
    "PUBLISHER_AGREEMENT": 12,
    "SENSITIVE_DATA": 36,
    "HUMAN_SUBJECTS": 12,
}

COUNTED_EVENT_STATUSES = (
    "DRAFT",
    "ANNOUNCED",
    "HELD_PASS",
    "HELD_PASS_WITH_REVISIONS",
    "HELD_FAIL",
)

COUNTED_COMMITTEE_STATUSES = ("SUBMITTED", "APPROVED")

CHAIR_ROLES = ("CHAIR", "CO_CHAIR")

TURNAROUND_COUNTED_STATUSES = ("ACCEPTED", "REVISIONS_REQUIRED", "SUPERSEDED")


def round_half_up(value, places):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


# --------------------------------------------------- severity weighted score


def severity_weighted_defect_score(page_count, critical, major, minor):
    density = round_half_up(
        Decimal(max(page_count, MIN_DENSITY_PAGES)) / DENSITY_BASE_PAGES, 4
    )
    term_critical = round_half_up(Decimal(critical) * W_CRITICAL * density, 2)
    term_major = round_half_up(Decimal(major) * W_MAJOR * density, 2)
    term_minor = round_half_up(Decimal(minor) * W_MINOR * density, 2)
    return round_half_up(term_critical + term_major + term_minor, 2)


# -------------------------------------------------------- revision window


def format_revision_window(cycle_number, decided_at, page_count, term):
    if cycle_number == 1:
        base = CYCLE1_WINDOW_BDAYS
    elif cycle_number == 2:
        base = CYCLE2_WINDOW_BDAYS
    else:
        base = CYCLE3_PLUS_WINDOW_BDAYS
    bonus = LONG_DOC_BONUS_BDAYS if page_count >= LONG_DOC_PAGE_THRESHOLD else 0
    raw_due = add_business_days(decided_at, base + bonus)
    deadline = term["format_review_deposit_deadline"]
    return raw_due if raw_due <= deadline else deadline


# ------------------------------------------------------- announcement lead


def defense_announcement_lead(now, scheduled_start):
    return business_days_between(now, scheduled_start)


# ------------------------------------------------------- committee counters


def committee_composition_counts(committee_id):
    seats = lookup.confirmed_seats(committee_id)
    return {
        "member_count": len(seats),
        "external_member_count": sum(
            1 for s in seats if s["role"] == "EXTERNAL_MEMBER"
        ),
        "chair_count": sum(1 for s in seats if s["role"] == "CHAIR"),
        "grad_rep_count": sum(
            1 for s in seats if s["role"] == "GRADUATE_REPRESENTATIVE"
        ),
    }


def composition_satisfies(document_type, counts):
    if document_type == "DISSERTATION":
        return (
            counts["member_count"] >= DOCTORAL_MIN_MEMBERS
            and counts["external_member_count"] >= DOCTORAL_MIN_EXTERNAL
            and counts["chair_count"] == 1
            and counts["grad_rep_count"] == 1
        )
    return (
        counts["member_count"] >= MASTERS_MIN_MEMBERS
        and counts["chair_count"] == 1
        and counts["grad_rep_count"] == 0
    )


def faculty_active_chair_load(faculty_id):
    from db import db

    total = 0
    for seat in db.committee_members.values():
        if seat["faculty_id"] != faculty_id:
            continue
        if seat["status"] != "CONFIRMED":
            continue
        if seat["role"] not in CHAIR_ROLES:
            continue
        committee = db.committees.get(seat["committee_id"])
        if committee is None:
            continue
        if committee["status"] in COUNTED_COMMITTEE_STATUSES:
            total += 1
    return total


# ------------------------------------------------------------ room counters


def event_minutes(event):
    delta = event["scheduled_end"] - event["scheduled_start"]
    return int(delta.total_seconds() // 60)


def room_booked_minutes_total(room_id):
    total = 0
    for event in lookup.events_of_room(room_id):
        if event["status"] in COUNTED_EVENT_STATUSES:
            total += event_minutes(event)
    return total


def room_overlap(new_start, new_end, existing_start, existing_end, buffer_minutes):
    buffer = timedelta(minutes=buffer_minutes)
    return new_start < existing_end + buffer and existing_start < new_end + buffer


def faculty_overlap(new_start, new_end, existing_start, existing_end):
    return new_start < existing_end and existing_start < new_end


# ------------------------------------------------------- integrity screening


def adjusted_similarity_pct(similarity_pct, excluded_quoted_pct):
    adjusted = round_half_up(
        Decimal(str(similarity_pct)) - Decimal(str(excluded_quoted_pct)), 2
    )
    if adjusted < 0:
        adjusted = Decimal("0.00")
    return adjusted


def screening_status_for(adjusted):
    return "FLAGGED" if adjusted >= FLAG_THRESHOLD_PCT else "CLEARED"


# ------------------------------------------------------------ deposit metadata


def metadata_completeness_score(
    abstract_word_count, subject_keywords, advisor_name, department_code
):
    weight = Decimal("0")
    if abstract_word_count >= ABSTRACT_MIN_WORDS:
        weight += W_ABSTRACT
    if len(subject_keywords) >= KEYWORDS_MIN_COUNT:
        weight += W_KEYWORDS
    if isinstance(advisor_name, str) and advisor_name != "":
        weight += W_ADVISOR
    if isinstance(department_code, str) and department_code != "":
        weight += W_DEPARTMENT
    weight += W_DEGREE_LEVEL
    weight += W_DOCUMENT_TYPE
    return round_half_up(weight / TOTAL_WEIGHT, 4)


# ----------------------------------------------------------------- late fee


def analyst_turnaround_bdays_total(thesis_id):
    total = 0
    for review in lookup.reviews_of_thesis(thesis_id):
        if review["decided_at"] is None:
            continue
        if review["status"] not in TURNAROUND_COUNTED_STATUSES:
            continue
        total += review["turnaround_bdays"] or 0
    return total


def deposit_late_fee_cents(thesis, term, now):
    turnaround_total = thesis["analyst_turnaround_bdays_total"]
    if turnaround_total >= GRACE_HIGH_TURNAROUND_BDAYS:
        grace = GRACE_HIGH_BDAYS
    elif turnaround_total >= GRACE_MID_TURNAROUND_BDAYS:
        grace = GRACE_MID_BDAYS
    else:
        grace = 0
    effective_deadline = add_business_days(
        term["format_review_deposit_deadline"], grace
    )
    if now > effective_deadline:
        days_late = business_days_between(effective_deadline, now)
    else:
        days_late = 0
    return min(days_late * DAILY_LATE_FEE_CENTS, LATE_FEE_CAP_CENTS)


# ------------------------------------------------------------------ embargo


def embargo_cap(reason_code, degree_level):
    cap = EMBARGO_CAPS_DOCTORAL[reason_code]
    if degree_level == "MASTERS":
        return cap // 2
    return cap


def governing_embargo_request(thesis_id):
    candidates = [
        row
        for row in lookup.embargoes_of_thesis(thesis_id)
        if row["status"] in ("APPROVED", "PARTIALLY_APPROVED")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r["created_at"], r["version"], r["_seq"]))


def embargo_release_date(governing, deposited_at, term):
    """Returns (release_date, release_anchor)."""
    months = governing["approved_months"] or 0
    if governing["status"] == "APPROVED":
        return add_months(deposited_at, months), "DEPOSIT"
    return add_months(term["degree_conferral_date"], months), "CONFERRAL"


# -------------------------------------------------------- transcript notation


def conferral_notation(document_type, deposited_at, embargo_release):
    from timeutil import date_str

    base = "%s deposited %s" % (document_type, date_str(deposited_at))
    if embargo_release is not None:
        return base + "; access restricted until " + date_str(embargo_release)
    return base


WITHHOLD_NOTATION = "Degree withheld pending academic integrity resolution"
WITHHOLD_REASON = "ACADEMIC_INTEGRITY_FINDING"
COMMITTEE_CHANGE_REASON = "COMMITTEE_COMPOSITION_CHANGED"
