"""Derived-field recomputation + calculation rules (SCAFFOLD 1.3).

All derived counters are computed on read from live state, so every
"recompute" side effect in the spec happens automatically.
"""

import math
from datetime import timedelta
from decimal import Decimal

import db
from util import parse_iso, to_d, q2, q4

PROGRAMS = ("NONE", "IEP", "ELL", "GIFTED", "ATHLETE")

GRADE_PACE = {9: Decimal("6.0"), 10: Decimal("12.0"),
              11: Decimal("18.0"), 12: Decimal("22.0")}
SUBJECT_MINIMUMS = (("ENGLISH", Decimal("1.0")), ("MATH", Decimal("1.0")),
                    ("SCIENCE", Decimal("0.5")), ("SOCIAL_STUDIES", Decimal("0.5")))
CREDIT_LOAD_CEILING = Decimal("8.0")

FREEZE_THRESHOLD = 3
LOOKBACK_DAYS = 90
WEEKDAY_MINUTES = 360
BUFFER_MINUTES = 10


# ---------------------------------------------------------------------------
# Derived counters
# ---------------------------------------------------------------------------

def enrolled_entries(section_id):
    return [e for e in db.schedule_entries.values()
            if e["section_id"] == section_id and e["state"] == "ENROLLED"]


def section_enrolled_count(section_id):
    return len(enrolled_entries(section_id))


def section_cohort_counts(section_id):
    counts = {}
    for e in enrolled_entries(section_id):
        stu = db.students.get(e["student_id"])
        prog = stu["special_program"] if stu else "NONE"
        counts[prog] = counts.get(prog, 0) + 1
    return counts


def cohort_half_cap(capacity):
    return math.ceil(0.5 * capacity)


def section_under_enrolled(section):
    cap = section.get("capacity")
    if not cap:
        return False
    return section_enrolled_count(section["id"]) < cohort_half_cap(cap)


def student_enrolled_entries(student_id, term_id=None):
    out = [e for e in db.schedule_entries.values()
           if e["student_id"] == student_id and e["state"] == "ENROLLED"]
    if term_id is not None:
        out = [e for e in out if e["term_id"] == term_id]
    return out


def student_planned_credit_load(student_id, term_id=None):
    total = Decimal("0")
    for e in student_enrolled_entries(student_id, term_id):
        sec = db.sections.get(e["section_id"])
        course = db.courses.get(sec["course_id"]) if sec else None
        if course:
            total += to_d(course["credits"])
    return q2(total)


def counselor_caseload_count(counselor_id):
    return sum(1 for s in db.students.values() if s["counselor_id"] == counselor_id)


def teacher_assigned_section_count(teacher_id):
    return sum(1 for s in db.sections.values()
               if s.get("teacher_id") == teacher_id
               and s["state"] in ("SCHEDULED", "PUBLISHED"))


def request_tally_weight(req):
    if req["state"] in ("SUBMITTED", "LOCKED"):
        return 0.5 if req["is_alternate"] else 1.0
    return 0


def term_total_requested_seats(term_id):
    return sum(1 for r in db.course_requests.values()
               if r["term_id"] == term_id and r["state"] in ("SUBMITTED", "LOCKED"))


def latest_audit(student_id, term_id=None):
    rows = [a for a in db.credit_audits.values() if a["student_id"] == student_id]
    if term_id is not None:
        rows = [a for a in rows if a["term_id"] == term_id]
    if not rows:
        return None
    return max(rows, key=lambda a: (a["audit_epoch"], a["created_at"], a["_seq"]))


def student_credit_deficient(student_id):
    a = latest_audit(student_id)
    if a is None:
        return False
    return to_d(a["deficiency_credits"]) > 0


def student_enrolled_periods(student_id, term_id, exclude_entry_id=None):
    periods = set()
    for e in student_enrolled_entries(student_id, term_id):
        if exclude_entry_id and e["id"] == exclude_entry_id:
            continue
        sec = db.sections.get(e["section_id"])
        if sec and sec.get("period") is not None:
            periods.add(sec["period"])
    return periods


def student_singleton_count(student_id, term_id, exclude_entry_id=None):
    n = 0
    for e in student_enrolled_entries(student_id, term_id):
        if exclude_entry_id and e["id"] == exclude_entry_id:
            continue
        sec = db.sections.get(e["section_id"])
        course = db.courses.get(sec["course_id"]) if sec else None
        if course and course["singleton"]:
            n += 1
    return n


def trailing_no_shows(student_id):
    """NO_SHOW appointments with start_at >= logical_now - 90d (closed bound)."""
    cutoff = db.clock.now() - timedelta(days=LOOKBACK_DAYS)
    n = 0
    for a in db.appointments.values():
        if a["student_id"] == student_id and a["state"] == "NO_SHOW":
            try:
                if parse_iso(a["start_at"]) >= cutoff:
                    n += 1
            except ValueError:
                continue
    return n


# ---------------------------------------------------------------------------
# placement_selector (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------

def placement_candidates(student, course, term_id):
    """Eligible PUBLISHED sections of the course for this student."""
    taken = student_enrolled_periods(student["id"], term_id)
    out = []
    for sec in db.sections.values():
        if sec["term_id"] != term_id or sec["course_id"] != course["id"]:
            continue
        if sec["state"] != "PUBLISHED":
            continue
        if section_enrolled_count(sec["id"]) >= sec["capacity"]:
            continue  # strict: a section at exactly capacity is ineligible
        if sec.get("period") in taken:
            continue
        if (course["special_program_exclusive"] != "NONE"
                and student["special_program"] != course["special_program_exclusive"]):
            continue
        out.append(sec)
    return out


def rank_sections(student, candidates):
    """Lexicographic: enrolled_count ASC, cohort_penalty ASC, created_at ASC."""
    prog = student["special_program"]

    def key(sec):
        enrolled = section_enrolled_count(sec["id"])
        penalty = 0
        if prog != "NONE":
            if section_cohort_counts(sec["id"]).get(prog, 0) >= cohort_half_cap(sec["capacity"]):
                penalty = 1
        return (enrolled, penalty, sec["created_at"], sec["_seq"])

    return sorted(candidates, key=key)


def placement_select(student, course, term_id):
    """Return the best eligible section or None."""
    ranked = rank_sections(student, placement_candidates(student, course, term_id))
    return ranked[0] if ranked else None


# ---------------------------------------------------------------------------
# section_count_tally (final + optimistic variants)
# ---------------------------------------------------------------------------

def tally_rows(term, optimistic):
    """Per-course demand rows. Final: SUBMITTED/LOCKED at full weight.
    Optimistic preview: adds DRAFT rows at halved weight (0.5/0.25)."""
    target = to_d(term["class_size_target"])
    rows = []
    courses = sorted(db.courses.values(), key=lambda c: (c["created_at"], c["_seq"]))
    for course in courses:
        demand = Decimal("0")
        for r in db.course_requests.values():
            if r["term_id"] != term["id"] or r["course_id"] != course["id"]:
                continue
            if r["state"] in ("SUBMITTED", "LOCKED"):
                demand += Decimal("0.5") if r["is_alternate"] else Decimal("1.0")
            elif optimistic and r["state"] == "DRAFT":
                demand += Decimal("0.25") if r["is_alternate"] else Decimal("0.5")
        if demand <= 0:
            continue
        if course["singleton"]:
            sections = 1
        else:
            sections = math.ceil(demand / target)
        sections = min(sections, term["periods_per_day"])
        rows.append({"course_id": course["id"], "course_code": course["course_code"],
                     "demand": float(demand), "projected_sections": sections,
                     "_course": course})
    return rows


# ---------------------------------------------------------------------------
# credit_pace_requirement (final_audit + provisional_projection variants)
# ---------------------------------------------------------------------------

def credit_audit_values(student, term_id, provisional=False):
    """Returns dict of required/projected/deficiency/deficient_subjects.

    Pinned order: planned_credit_load first, then projected, then deficiency,
    then the subject sweep consuming planned as an input.
    """
    grade = student["grade_level"]
    required = GRADE_PACE[grade]
    years = grade - 8
    earned = to_d(student["earned_credits"])

    if provisional:
        # Requested credits over SUBMITTED primaries (alternates excluded).
        planned = Decimal("0")
        per_subject = {}
        for r in db.course_requests.values():
            if (r["student_id"] == student["id"] and r["term_id"] == term_id
                    and r["state"] == "SUBMITTED" and not r["is_alternate"]):
                course = db.courses.get(r["course_id"])
                if not course:
                    continue
                c = to_d(course["credits"])
                planned += c
                per_subject[course["subject_area"]] = (
                    per_subject.get(course["subject_area"], Decimal("0")) + c)
    else:
        planned = student_planned_credit_load(student["id"], term_id)
        per_subject = {}
        for e in student_enrolled_entries(student["id"], term_id):
            sec = db.sections.get(e["section_id"])
            course = db.courses.get(sec["course_id"]) if sec else None
            if not course:
                continue
            per_subject[course["subject_area"]] = (
                per_subject.get(course["subject_area"], Decimal("0"))
                + to_d(course["credits"]))

    projected = q2(earned + planned)
    deficiency = q2(max(Decimal("0"), required - projected))
    deficient = [name for name, per_year in SUBJECT_MINIMUMS
                 if per_subject.get(name, Decimal("0")) < per_year * years]
    return {"required_credits": required, "projected_credits": projected,
            "deficiency_credits": deficiency, "deficient_subjects": deficient}


# ---------------------------------------------------------------------------
# recovery_priority
# ---------------------------------------------------------------------------

def recovery_priority_score(student, term_id):
    a = latest_audit(student["id"], term_id)
    deficiency = to_d(a["deficiency_credits"]) if a else Decimal("0")
    subjects = a["deficient_subjects"] if a else []
    score = (Decimal(10) * deficiency
             + Decimal(2) * (student["grade_level"] - 8)
             + (Decimal(3) if "ENGLISH" in subjects else Decimal(0))
             + (Decimal(3) if "MATH" in subjects else Decimal(0)))
    return q2(score)


# ---------------------------------------------------------------------------
# rebalance_imbalance
# ---------------------------------------------------------------------------

def term_imbalance(term):
    secs = [s for s in db.sections.values()
            if s["term_id"] == term["id"] and s["state"] == "PUBLISHED"]
    total = sum(section_enrolled_count(s["id"]) for s in secs)
    p = term["periods_per_day"]
    target = Decimal(total) / Decimal(p)
    loads = {i: 0 for i in range(1, p + 1)}
    for s in secs:
        if s.get("period") in loads:
            loads[s["period"]] += section_enrolled_count(s["id"])
    imbalance = sum(abs(Decimal(loads[i]) - target) for i in loads)
    return q2(imbalance)


# ---------------------------------------------------------------------------
# counselor_utilization
# ---------------------------------------------------------------------------

def counselor_utilization(counselor_id, window_start, window_end):
    booked = 0
    for a in db.appointments.values():
        if a["counselor_id"] != counselor_id or a["state"] != "BOOKED":
            continue
        try:
            s = parse_iso(a["start_at"])
            e = parse_iso(a["end_at"])
        except ValueError:
            continue
        # Half-open window [window_start, window_end): fully-inside appointments.
        if s >= window_start and e <= window_end:
            booked += int((e - s).total_seconds() // 60)  # truncate seconds
    available = 0
    day = window_start.date()
    last = window_end.date()
    from datetime import date as date_cls
    while day <= last:
        day_start = datetime_at(day)
        day_end = datetime_at(day + timedelta(days=1))
        if day_start < window_end and day_end > window_start:
            if day.weekday() < 5:  # Mon-Fri
                available += WEEKDAY_MINUTES
        day += timedelta(days=1)
    if available <= 0:
        util = Decimal("0")
    else:
        util = q4(Decimal(booked) / Decimal(available))
        if util > Decimal("1.0000"):
            util = Decimal("1.0000")
    return {"counselor_id": counselor_id, "booked_minutes": booked,
            "available_minutes": available, "utilization": float(util)}


def datetime_at(d):
    from datetime import datetime, timezone
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
