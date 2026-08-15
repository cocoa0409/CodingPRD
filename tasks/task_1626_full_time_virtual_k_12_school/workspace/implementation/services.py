"""Business logic: calculations (PRD section 3 / scaffold Table 3), the
withdrawal cascade, derived-field reconciliation, and the clock sweep."""

from datetime import timedelta

import db
from util import parse_dt, midnight_utc

# --- Calculation constants (scaffold Table 3) ---
FULL_DAY_MINUTES = 240
HALF_DAY_MINUTES = 120
MIN_CHECKINS = 2
TRUANCY_WINDOW_SCHOOL_DAYS = 10
TRUANCY_THRESHOLD = 3
DEVICE_RETURN_WINDOW_DAYS = 30

DAILY_ATTENDANCE_REASONS = {"DROPOUT", "ADMINISTRATIVE"}
CALENDAR_ELAPSED_REASONS = {"MOVED_DISTRICT", "RETURN_TO_BRICK_AND_MORTAR", "HOMESCHOOL"}


# ---------------------------------------------------------------------------
# attendance_determination (thresholds are inclusive)
# ---------------------------------------------------------------------------

def attendance_determination(synchronous_minutes, engagement_check_ins):
    if synchronous_minutes >= FULL_DAY_MINUTES and engagement_check_ins >= MIN_CHECKINS:
        return "PRESENT"
    if synchronous_minutes >= HALF_DAY_MINUTES or engagement_check_ins >= MIN_CHECKINS:
        return "PARTIAL"
    return "ABSENT_UNEXCUSED"


# ---------------------------------------------------------------------------
# truancy_window_count + truancy_determination
# Window = the 10 most recent records (by count of records, not calendar
# span); cutoff = date of the 10th most recent record, inclusive. Threshold
# is inclusive: count >= 3 sets the flag.
# ---------------------------------------------------------------------------

def recompute_truancy(student):
    records = [r for r in db.all_of("attendance_records")
               if r["student_id"] == student["id"]]
    records.sort(key=lambda r: (parse_dt(r["attendance_date"]), r["_seq"]), reverse=True)
    if len(records) >= TRUANCY_WINDOW_SCHOOL_DAYS:
        cutoff = parse_dt(records[TRUANCY_WINDOW_SCHOOL_DAYS - 1]["attendance_date"])
    elif records:
        cutoff = min(parse_dt(r["attendance_date"]) for r in records)
    else:
        cutoff = None
    count = 0
    for r in records:
        if r["attendance_status"] == "ABSENT_UNEXCUSED":
            if cutoff is None or parse_dt(r["attendance_date"]) >= cutoff:
                count += 1
    student["truancy_unexcused_count"] = count
    student["truancy_flag"] = count >= TRUANCY_THRESHOLD
    # A derived-field recomputation is a mutation of the student record.
    db.touch(student)


# ---------------------------------------------------------------------------
# District enrollment cap. A district has an open slot while the number of
# its students in ELIGIBLE or ENROLLED status is strictly less than its
# enrollment_cap. A student who already occupies a slot (ELIGIBLE) fits.
# ---------------------------------------------------------------------------

def district_open_slot(district, student):
    if district is None:
        return False
    count = sum(
        1 for s in db.all_of("students")
        if s["district_of_residence_id"] == district["id"]
        and s["enrollment_status"] in ("ELIGIBLE", "ENROLLED")
    )
    if student["enrollment_status"] in ("ELIGIBLE", "ENROLLED"):
        # The student already holds one of the counted slots.
        return count <= district["enrollment_cap"]
    return count < district["enrollment_cap"]


# ---------------------------------------------------------------------------
# proration_mode_selector + funding_proration
# ---------------------------------------------------------------------------

def proration_mode_for(withdrawal_reason):
    if withdrawal_reason in DAILY_ATTENDANCE_REASONS:
        return "DAILY_ATTENDANCE"
    return "CALENDAR_ELAPSED"


def compute_claimable_days(student, term):
    """Both term endpoints are inclusive calendar days; integer arithmetic."""
    start = parse_dt(term["term_start_date"])
    end = parse_dt(term["term_end_date"])
    if term["proration_mode"] == "CALENDAR_ELAPSED":
        return max(0, (end - start).days + 1)
    # DAILY_ATTENDANCE: only days with a PRESENT or PARTIAL record count.
    count = 0
    for r in db.all_of("attendance_records"):
        if r["student_id"] != student["id"]:
            continue
        d = parse_dt(r["attendance_date"])
        if start <= d <= end and r["attendance_status"] in ("PRESENT", "PARTIAL"):
            count += 1
    return count


# ---------------------------------------------------------------------------
# funding_claim_amount: per-term claim (days * district rate at computation
# time), then summed. Sum-then-multiply is expressly forbidden. All integer
# cents; no rounding anywhere in the funding pipeline.
# ---------------------------------------------------------------------------

def recompute_funding(student):
    district = db.get("districts", student["district_of_residence_id"])
    rate = district["funding_rate_cents"] if district else 0
    total_days = 0
    total_cents = 0
    for t in db.all_of("enrollment_terms"):
        if t["student_id"] == student["id"]:
            total_days += t["claimable_days"]
            total_cents += t["claimable_days"] * rate
    student["funding_days_claimed"] = total_days
    student["funding_claim_cents"] = total_cents


# ---------------------------------------------------------------------------
# Derived-field reconciliation on read (silent: no version bump). Derived
# values are pure functions of other state; recomputation on read keeps them
# valued at the rate/state in effect at computation time (PRD section 2.10).
# ---------------------------------------------------------------------------

def reconcile_student(student):
    recompute_funding(student)


def reconcile_teacher(teacher):
    teacher["current_caseload"] = sum(
        1 for ta in db.all_of("teacher_assignments")
        if ta["teacher_id"] == teacher["id"] and ta["assignment_status"] == "ASSIGNED"
    )


def reconcile_site(site):
    site["seats_booked"] = sum(
        1 for pa in db.all_of("proctor_assignments")
        if pa["test_site_id"] == site["id"] and pa["assignment_status"] == "BOOKED"
    )


# ---------------------------------------------------------------------------
# Student ENROLLED -> WITHDRAWN cascade (PRD section 3.3): single atomic
# operation; every cascaded record is itself mutated (version + updated_at).
# ---------------------------------------------------------------------------

def withdraw_cascade(student, term, withdrawal_reason):
    now = db.now()
    today = midnight_utc(now)

    # 1. Close the books on the open term.
    term["term_status"] = "WITHDRAWN"
    term["term_end_date"] = db.fmt_date(today - timedelta(days=1))
    term["withdrawal_reason"] = withdrawal_reason
    term["proration_mode"] = proration_mode_for(withdrawal_reason)
    term["claimable_days"] = compute_claimable_days(student, term)
    db.touch(term)

    # 2. Stipends: DEVICE -> RETURN_REQUESTED (30-day deadline);
    #    INTERNET -> FORFEITED with zero clawback.
    for s in db.all_of("stipends"):
        if s["student_id"] != student["id"] or s["issue_status"] != "ISSUED":
            continue
        if s["stipend_type"] == "DEVICE":
            s["issue_status"] = "RETURN_REQUESTED"
            s["return_due_date"] = db.fmt_date(today + timedelta(days=DEVICE_RETURN_WINDOW_DAYS))
        else:
            s["issue_status"] = "FORFEITED"
            s["clawback_cents"] = 0
        db.touch(s)

    # 3. Teacher assignments: end every live assignment; caseload drops.
    for ta in db.all_of("teacher_assignments"):
        if ta["student_id"] == student["id"] and ta["assignment_status"] == "ASSIGNED":
            ta["assignment_status"] = "ENDED"
            ta["ended_at"] = db.fmt_ts(now)
            db.touch(ta)
            teacher = db.get("teachers", ta["teacher_id"])
            if teacher is not None:
                teacher["current_caseload"] = max(0, teacher["current_caseload"] - 1)
                db.touch(teacher)

    # 4. Proctor bookings: cancel every BOOKED seat; release the seat.
    for pa in db.all_of("proctor_assignments"):
        if pa["student_id"] == student["id"] and pa["assignment_status"] == "BOOKED":
            pa["assignment_status"] = "CANCELLED"
            db.touch(pa)
            site = db.get("test_sites", pa["test_site_id"])
            if site is not None:
                site["seats_booked"] = max(0, site["seats_booked"] - 1)
                db.touch(site)

    # 5. Service deliveries: cancel every SCHEDULED session.
    for sd in db.all_of("service_deliveries"):
        if sd["student_id"] == student["id"] and sd["delivery_status"] == "SCHEDULED":
            sd["delivery_status"] = "CANCELLED"
            db.touch(sd)

    # 6. Student status + funding totals; one version bump for the operation.
    student["enrollment_status"] = "WITHDRAWN"
    recompute_funding(student)
    db.touch(student)


# ---------------------------------------------------------------------------
# Logical-clock sweep (PRD section 2.5): fires on every clock set.
# ---------------------------------------------------------------------------

def clock_sweep():
    now = db.now()
    # Assessment windows: SCHEDULED -> OPEN once window_start is reached.
    for w in db.all_of("assessment_windows"):
        if w["window_status"] == "SCHEDULED" and parse_dt(w["window_start"]) <= now:
            w["window_status"] = "OPEN"
            db.touch(w)
    # Assessment windows: OPEN -> CLOSED once window_end is strictly past;
    # still-BOOKED seats are stranded as NO_SHOW and released.
    for w in db.all_of("assessment_windows"):
        if w["window_status"] == "OPEN" and parse_dt(w["window_end"]) < now:
            w["window_status"] = "CLOSED"
            db.touch(w)
            for pa in db.all_of("proctor_assignments"):
                if (pa["assessment_window_id"] == w["id"]
                        and pa["assignment_status"] == "BOOKED"):
                    pa["assignment_status"] = "NO_SHOW"
                    db.touch(pa)
                    site = db.get("test_sites", pa["test_site_id"])
                    if site is not None:
                        site["seats_booked"] = max(0, site["seats_booked"] - 1)
                        db.touch(site)
    # Device stipends: RETURN_REQUESTED past its due date -> FORFEITED with
    # full clawback. Comparison is by calendar date.
    clock_date = midnight_utc(now)
    for s in db.all_of("stipends"):
        if s["issue_status"] == "RETURN_REQUESTED" and s["return_due_date"] is not None:
            if parse_dt(s["return_due_date"]) < clock_date:
                s["issue_status"] = "FORFEITED"
                s["clawback_cents"] = s["amount_cents"]
                db.touch(s)
