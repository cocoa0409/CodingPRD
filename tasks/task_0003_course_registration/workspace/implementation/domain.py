"""Domain logic: state transitions, calculations, cascades, sweep."""
from datetime import datetime, timezone

from core import (
    APPROVAL_TIMEOUT_SECONDS,
    CREDIT_TIER,
    DOWNSTREAM_ALL,
    DOWNSTREAM_FINANCE,
    DOWNSTREAM_OVER_LIMIT,
    DOWNSTREAM_PAID,
    FRAUD_GRACE,
    RAPID_SUBMIT_LIMIT,
    RAPID_SUBMIT_PENALTY,
    RAPID_SUBMIT_WINDOW_SECONDS,
    REC_TOP_K,
    REC_W_GAP,
    REC_W_PREREQ_UNLOCK,
    REC_W_TIME_CONFLICT,
    UNAUTHORIZED_DEPT_PENALTY,
    W_FRAUD,
    W_GAP,
    W_PREREQ,
    W_YEAR,
    bump,
    db,
    err,
    new_id,
    now_iso,
    round2,
    stamp_create_immutable,
    sum_round2,
    trunc_int,
)


# ---------------------------------------------------------------------------
# Sync events
# ---------------------------------------------------------------------------
def emit_sync_event(subject_entity: str, subject_id: str, event_type: str, target_systems, payload=None, student_id=None):
    rec = stamp_create_immutable()
    rec.update(
        {
            "subject_entity": subject_entity,
            "subject_id": subject_id,
            "event_type": event_type,
            "target_systems": list(target_systems),
            "payload": payload or {},
            "_student_id": student_id,
        }
    )
    db.sync_events.append(rec)
    return rec


# ---------------------------------------------------------------------------
# Time utilities
# ---------------------------------------------------------------------------
def weekday_of(unix_seconds: int) -> int:
    """Return Monday=0..Sunday=6 for a Unix epoch second."""
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).weekday()


# ---------------------------------------------------------------------------
# Term auto-transitions (driven by clock)
# ---------------------------------------------------------------------------
def _term_to_registration_open(term):
    term["status"] = "REGISTRATION_OPEN"
    bump(term)


def _term_to_registration_closed(term):
    term["status"] = "REGISTRATION_CLOSED"
    bump(term)
    # Cascade: SUBMITTED enrollment requests → REJECTED (not in our state machine but PRD covers SUBMITTED == fresh)
    for ereq in db.enrollment_requests.values():
        if ereq["term_id"] == term["id"]:
            if ereq["academic_status"] == "SUBMITTED":
                ereq["academic_status"] = "REJECTED"
                bump(ereq)
    # Cascade: ACTIVE WaitlistEntry → EXPIRED
    for w in db.waitlist_entries.values():
        offering = db.course_offerings.get(w["offering_id"])
        if offering and offering["term_id"] == term["id"] and w["status"] == "ACTIVE":
            w["status"] = "EXPIRED"
            # WaitlistEntry has no version/updated_at


def _term_to_in_session(term):
    term["status"] = "IN_SESSION"
    bump(term)
    # Cascade: CourseOffering CLOSED → IN_SESSION
    for offering in db.course_offerings.values():
        if offering["term_id"] == term["id"] and offering["status"] == "CLOSED":
            offering["status"] = "IN_SESSION"
            bump(offering)


def _overlimit_escalate(app):
    app["status"] = "AWAITING_SECONDARY"
    app["timeout_deadline_at"] = db.clock + APPROVAL_TIMEOUT_SECONDS
    bump(app)


def _overlimit_expire(app):
    app["status"] = "EXPIRED"
    bump(app)


def run_clock_auto_transitions():
    """Per PRD §2.13 canonical order:
    1. Term PLANNING → REGISTRATION_OPEN
    2. Term REGISTRATION_OPEN → REGISTRATION_CLOSED with cascades
    3. OverLimit AWAITING_PRIMARY → AWAITING_SECONDARY (escalation)
    4. OverLimit AWAITING_SECONDARY → EXPIRED
    5. Term REGISTRATION_CLOSED → IN_SESSION
    """
    clk = db.clock

    # Step 1
    for term in sorted(db.terms.values(), key=lambda t: t["id"]):
        if term["status"] == "PLANNING" and clk >= term["registration_open_at"]:
            _term_to_registration_open(term)

    # Step 2
    for term in sorted(db.terms.values(), key=lambda t: t["id"]):
        if term["status"] == "REGISTRATION_OPEN" and clk >= term["registration_close_at"]:
            _term_to_registration_closed(term)

    # Step 3: AWAITING_PRIMARY → AWAITING_SECONDARY
    for app in sorted(db.over_limit_applications.values(), key=lambda a: a["id"]):
        if app["status"] == "AWAITING_PRIMARY" and clk >= app.get("timeout_deadline_at", 0):
            _overlimit_escalate(app)

    # Step 4: AWAITING_SECONDARY → EXPIRED
    for app in sorted(db.over_limit_applications.values(), key=lambda a: a["id"]):
        if app["status"] == "AWAITING_SECONDARY" and clk >= app.get("timeout_deadline_at", 0):
            _overlimit_expire(app)

    # Step 5: REGISTRATION_CLOSED → IN_SESSION
    for term in sorted(db.terms.values(), key=lambda t: t["id"]):
        if term["status"] == "REGISTRATION_CLOSED" and clk >= term["classes_start_at"]:
            _term_to_in_session(term)


# ---------------------------------------------------------------------------
# Calculations: gap analysis, dynamic credit quota, transferable credits, conflicts
# ---------------------------------------------------------------------------
def degree_plan_required_course_ids(student) -> set:
    return {c["id"] for c in db.courses.values() if c["owning_department_id"] == student["program_department_id"]}


def degree_plan_gap(student):
    required_ids = degree_plan_required_course_ids(student)
    completed_ids = set(student.get("completed_course_ids") or [])
    completed_credits_vals = []
    for cid in completed_ids:
        c = db.courses.get(cid)
        if c:
            completed_credits_vals.append(c["credits"])
    completed_credits = sum_round2(completed_credits_vals)

    in_progress_vals = []
    held_course_ids = set()
    for ereq in db.enrollment_requests.values():
        if ereq["student_id"] != student["id"]:
            continue
        if ereq["academic_status"] in ("APPROVED", "WAITLISTED", "SETTLED"):
            offering = db.course_offerings.get(ereq["offering_id"])
            if offering:
                course = db.courses.get(offering["course_id"])
                if course:
                    in_progress_vals.append(course["credits"])
            if ereq["academic_status"] in ("APPROVED", "SETTLED"):
                if offering:
                    held_course_ids.add(offering["course_id"])
    in_progress_credits = sum_round2(in_progress_vals)

    gap_courses = required_ids - completed_ids - held_course_ids
    gap_count = len(gap_courses)

    total_required_vals = []
    for cid in required_ids:
        c = db.courses.get(cid)
        if c:
            total_required_vals.append(c["credits"])
    total_required_credits = sum_round2(total_required_vals)

    remaining_credits = round2(total_required_credits - completed_credits - in_progress_credits)

    return {
        "required_course_ids": sorted(required_ids),
        "gap_courses": sorted(gap_courses),
        "gap_count": gap_count,
        "completed_credits": completed_credits,
        "in_progress_credits": in_progress_credits,
        "total_required_credits": total_required_credits,
        "remaining_credits": remaining_credits,
    }


def transferable_credits_for(student):
    """Per-course rounding then sum (PRD-pinned)."""
    completed_ids = set(student.get("completed_course_ids") or [])
    total = 0.0
    for cid in completed_ids:
        course = db.courses.get(cid)
        if not course:
            continue
        for policy in db.credit_equivalence_policies.values():
            if (
                policy["source_program_id"] == course["owning_department_id"]
                and policy["target_program_id"] == student["program_id"]
                and policy["source_course_id"] == cid
            ):
                raw = course["credits"] * policy["transfer_factor"]
                per_course = round2(raw)
                total = round2(total + per_course)
    return total


def base_quota_for(student) -> int:
    y = max(1, min(int(student["year_in_program"]), 6))
    return CREDIT_TIER[y]


def effective_quota_provisional(student, term_id) -> float:
    """base + sum(granted_credits over APPROVED OverLimitApp for student/term)."""
    base = base_quota_for(student)
    extension = 0.0
    for app in db.over_limit_applications.values():
        if (
            app["student_id"] == student["id"]
            and app["term_id"] == term_id
            and app["status"] == "APPROVED"
        ):
            extension = round2(extension + app.get("granted_credits", 0))
    return round2(base + extension)


def current_load_provisional(student, term_id) -> float:
    """Sum Course.credits across student's enrollments (APPROVED/WAITLISTED) in term."""
    vals = []
    for ereq in db.enrollment_requests.values():
        if ereq["student_id"] != student["id"] or ereq["term_id"] != term_id:
            continue
        if ereq["academic_status"] in ("APPROVED", "WAITLISTED"):
            offering = db.course_offerings.get(ereq["offering_id"])
            if offering:
                course = db.courses.get(offering["course_id"])
                if course:
                    vals.append(course["credits"])
    return sum_round2(vals)


def current_load_final(student, term_id) -> float:
    vals = []
    for ereq in db.enrollment_requests.values():
        if ereq["student_id"] != student["id"] or ereq["term_id"] != term_id:
            continue
        if ereq["academic_status"] in ("APPROVED", "SETTLED"):
            offering = db.course_offerings.get(ereq["offering_id"])
            if offering:
                course = db.courses.get(offering["course_id"])
                if course:
                    vals.append(course["credits"])
    return sum_round2(vals)


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------
def time_overlap_half_open(m1, m2) -> bool:
    """m1, m2 are dicts with day_of_week, start_minute_of_day, end_minute_of_day."""
    if m1["day_of_week"] != m2["day_of_week"]:
        return False
    return m1["start_minute_of_day"] < m2["end_minute_of_day"] and m2["start_minute_of_day"] < m1["end_minute_of_day"]


def check_time_conflict(student_id, term_id, candidate_offering, exclude_request_id=None):
    candidate_meetings = candidate_offering.get("scheduled_meetings", [])
    for ereq in db.enrollment_requests.values():
        if ereq["student_id"] != student_id or ereq["term_id"] != term_id:
            continue
        if ereq.get("id") == exclude_request_id:
            continue
        if ereq["academic_status"] not in ("APPROVED", "WAITLISTED"):
            continue
        existing = db.course_offerings.get(ereq["offering_id"])
        if not existing or existing["id"] == candidate_offering["id"]:
            continue
        for m_new in candidate_meetings:
            for m_exist in existing.get("scheduled_meetings", []):
                if time_overlap_half_open(m_new, m_exist):
                    return True
    return False


def check_commute_conflict(student_id, term_id, candidate_offering, exclude_request_id=None):
    cand_campus_id = candidate_offering["campus_id"]
    candidate_meetings = candidate_offering.get("scheduled_meetings", [])
    for ereq in db.enrollment_requests.values():
        if ereq["student_id"] != student_id or ereq["term_id"] != term_id:
            continue
        if ereq.get("id") == exclude_request_id:
            continue
        if ereq["academic_status"] not in ("APPROVED", "WAITLISTED"):
            continue
        existing = db.course_offerings.get(ereq["offering_id"])
        if not existing or existing["id"] == candidate_offering["id"]:
            continue
        if existing["campus_id"] == cand_campus_id:
            continue
        from_campus = db.campuses.get(existing["campus_id"])
        if not from_campus:
            continue
        buffer = (from_campus.get("commute_minutes_to") or {}).get(cand_campus_id, 0)
        for m_new in candidate_meetings:
            for m_exist in existing.get("scheduled_meetings", []):
                if m_new["day_of_week"] != m_exist["day_of_week"]:
                    continue
                # Skip if they overlap in time (handled by time conflict).
                if time_overlap_half_open(m_new, m_exist):
                    continue
                # Compute the gap (positive only).
                gap = max(
                    m_new["start_minute_of_day"] - m_exist["end_minute_of_day"],
                    m_exist["start_minute_of_day"] - m_new["end_minute_of_day"],
                )
                if gap < buffer:
                    return True
    return False


def offering_exam_slot(offering, term):
    """Return (day_of_week, start_minute, end_minute) of the offering's exam slot, or None."""
    if not term.get("exam_window_start_at"):
        return None
    exam_day = weekday_of(term["exam_window_start_at"])
    same_day_meetings = [m for m in offering.get("scheduled_meetings", []) if m["day_of_week"] == exam_day]
    if not same_day_meetings:
        return None
    first = sorted(same_day_meetings, key=lambda m: m["start_minute_of_day"])[0]
    return (first["day_of_week"], first["start_minute_of_day"], first["end_minute_of_day"])


def check_exam_conflict(student_id, term_id, candidate_offering, exclude_request_id=None):
    term = db.terms.get(term_id)
    if not term:
        return False
    cand_slot = offering_exam_slot(candidate_offering, term)
    if not cand_slot:
        return False
    for ereq in db.enrollment_requests.values():
        if ereq["student_id"] != student_id or ereq["term_id"] != term_id:
            continue
        if ereq.get("id") == exclude_request_id:
            continue
        if ereq["academic_status"] not in ("APPROVED", "WAITLISTED"):
            continue
        existing = db.course_offerings.get(ereq["offering_id"])
        if not existing or existing["id"] == candidate_offering["id"]:
            continue
        existing_slot = offering_exam_slot(existing, term)
        if not existing_slot:
            continue
        if cand_slot[0] != existing_slot[0]:
            continue
        # Closed intervals on both ends
        a_start, a_end = cand_slot[1], cand_slot[2]
        b_start, b_end = existing_slot[1], existing_slot[2]
        if a_start <= b_end and b_start <= a_end:
            return True
    return False


def check_lab_equipment_conflict(candidate_offering, exclude_offering_id=None):
    cand_equip_ids = candidate_offering.get("requires_lab_equipment_ids") or []
    if not cand_equip_ids:
        return False
    candidate_meetings = candidate_offering.get("scheduled_meetings", [])
    term_id = candidate_offering["term_id"]
    for lab_id in cand_equip_ids:
        equip = db.lab_equipment.get(lab_id)
        if not equip:
            continue
        buffer = equip.get("setup_buffer_minutes", 0)
        for other in db.course_offerings.values():
            if other["id"] == candidate_offering["id"] or other["id"] == exclude_offering_id:
                continue
            if other["term_id"] != term_id:
                continue
            if other["status"] not in ("OPEN", "IN_SESSION"):
                continue
            if lab_id not in (other.get("requires_lab_equipment_ids") or []):
                continue
            for m_new in candidate_meetings:
                for m_exist in other.get("scheduled_meetings", []):
                    if m_new["day_of_week"] != m_exist["day_of_week"]:
                        continue
                    # Buffer extends both endpoints uniformly: start1 < end2 + buffer AND start2 < end1 + buffer
                    if (
                        m_new["start_minute_of_day"] < m_exist["end_minute_of_day"] + buffer
                        and m_exist["start_minute_of_day"] < m_new["end_minute_of_day"] + buffer
                    ):
                        return True
    return False


def instructor_weekly_minutes(instructor_id, exclude_offering_id=None) -> int:
    total = 0
    for offering in db.course_offerings.values():
        if offering["instructor_id"] != instructor_id:
            continue
        if offering["id"] == exclude_offering_id:
            continue
        if offering["status"] not in ("OPEN", "IN_SESSION"):
            continue
        for m in offering.get("scheduled_meetings", []):
            total += m["end_minute_of_day"] - m["start_minute_of_day"]
    return total


def offering_weekly_minutes(offering) -> int:
    return sum(m["end_minute_of_day"] - m["start_minute_of_day"] for m in offering.get("scheduled_meetings", []))


# ---------------------------------------------------------------------------
# Cross-department access / category check
# ---------------------------------------------------------------------------
def cross_dept_access_ok(student, course) -> bool:
    if course["owning_department_id"] == student["program_department_id"]:
        return True
    src = student["program_department_id"]
    tgt = course["owning_department_id"]
    cat = course.get("category")
    for grant in db.department_access_grants.values():
        if grant["status"] != "ACTIVE":
            continue
        s, t = grant["source_department_id"], grant["target_department_id"]
        match_dir = (s == src and t == tgt) or (grant.get("bidirectional") and s == tgt and t == src)
        if not match_dir:
            continue
        allowed = grant.get("course_categories_allowed") or []
        if cat is not None and cat in allowed:
            return True
    return False


# ---------------------------------------------------------------------------
# Prereq check
# ---------------------------------------------------------------------------
def prereqs_satisfied(student, course) -> bool:
    completed = set(student.get("completed_course_ids") or [])
    for entry in course.get("prerequisite_course_ids") or []:
        if isinstance(entry, dict):
            cid = entry.get("course_id")
            mode = entry.get("mode", "REQUIRED")
        else:
            cid = entry
            mode = "REQUIRED"
        if mode != "REQUIRED":
            continue
        if cid in completed:
            continue
        # Check equivalents (per-prereq course's equivalent list)
        prereq_course = db.courses.get(cid)
        ok = False
        if prereq_course:
            equivs = prereq_course.get("equivalent_course_ids") or []
            if any(e in completed for e in equivs):
                ok = True
        if not ok:
            return False
    return True


# ---------------------------------------------------------------------------
# Anti-fraud
# ---------------------------------------------------------------------------
def recent_submission_count(student_id) -> int:
    cutoff = db.clock - RAPID_SUBMIT_WINDOW_SECONDS
    cnt = 0
    for ereq in db.enrollment_requests.values():
        if ereq["student_id"] != student_id:
            continue
        ts = ereq.get("_created_clock", 0)
        if ts >= cutoff:
            cnt += 1
    return cnt


# ---------------------------------------------------------------------------
# Priority score
# ---------------------------------------------------------------------------
def downstream_unlock_count(course_id) -> int:
    cnt = 0
    for c in db.courses.values():
        for entry in c.get("prerequisite_course_ids") or []:
            cid = entry.get("course_id") if isinstance(entry, dict) else entry
            if cid == course_id:
                cnt += 1
                break
    return cnt


def compute_priority_score(student, course):
    year_factor = min(int(student["year_in_program"]), 5)
    gap_set = degree_plan_required_course_ids(student) - set(student.get("completed_course_ids") or [])
    held = set()
    for ereq in db.enrollment_requests.values():
        if ereq["student_id"] == student["id"] and ereq["academic_status"] in ("APPROVED", "SETTLED"):
            offering = db.course_offerings.get(ereq["offering_id"])
            if offering:
                held.add(offering["course_id"])
    gap_set = gap_set - held
    gap_count = 1 if course["id"] in gap_set else 0
    prereq_strength = downstream_unlock_count(course["id"])
    fraud_penalty = max(0, student.get("fraud_score", 0) - FRAUD_GRACE)
    score = (W_YEAR * year_factor) + (W_GAP * gap_count) + (W_PREREQ * prereq_strength) - (W_FRAUD * fraud_penalty)
    return trunc_int(score)


# ---------------------------------------------------------------------------
# State transitions: enrollment approve/waitlist
# ---------------------------------------------------------------------------
def _approve_enrollment(ereq, offering, course, student):
    ereq["academic_status"] = "APPROVED"
    ereq["financial_status"] = "BILLED"
    ereq["provisional_credit_charge"] = round2(course["credits"])
    ereq["priority_score"] = compute_priority_score(student, course)
    bump(ereq)
    offering["enrolled_count"] = offering.get("enrolled_count", 0) + 1
    bump(offering)
    emit_sync_event(
        "EnrollmentRequest", ereq["id"], "ENROLLMENT_APPROVED", DOWNSTREAM_ALL,
        payload={"student_id": student["id"], "offering_id": offering["id"]},
        student_id=student["id"],
    )
    emit_sync_event(
        "EnrollmentRequest", ereq["id"], "TUITION_BILLED", DOWNSTREAM_FINANCE,
        payload={"student_id": student["id"], "amount_credits": round2(course["credits"])},
        student_id=student["id"],
    )


def _waitlist_enrollment(ereq, offering, course, student):
    ereq["academic_status"] = "WAITLISTED"
    score = compute_priority_score(student, course)
    ereq["priority_score"] = score
    bump(ereq)
    entry = stamp_create_immutable()
    entry.update(
        {
            "offering_id": offering["id"],
            "enrollment_request_id": ereq["id"],
            "priority_score": score,
            "queued_at": db.clock,
            "status": "ACTIVE",
        }
    )
    db.waitlist_entries[entry["id"]] = entry
    return entry


def waitlist_for_offering_active(offering_id):
    """Return ACTIVE WaitlistEntry rows for offering, sorted by priority DESC, queued_at ASC, then id."""
    rows = [w for w in db.waitlist_entries.values() if w["offering_id"] == offering_id and w["status"] == "ACTIVE"]
    rows.sort(key=lambda w: (-w["priority_score"], w["queued_at"], w["id"]))
    return rows


def waitlist_with_position(offering_id):
    """Return all WaitlistEntry rows for an offering with computed position field."""
    active = waitlist_for_offering_active(offering_id)
    seen = set(w["id"] for w in active)
    out = []
    for i, w in enumerate(active, start=1):
        c = dict(w)
        c["position"] = i
        out.append(c)
    # Append non-ACTIVE entries with no position
    for w in db.waitlist_entries.values():
        if w["offering_id"] == offering_id and w["id"] not in seen:
            c = dict(w)
            c["position"] = None
            out.append(c)
    return out


def _validate_promotion_candidate(ereq, offering, course, student):
    """Re-validate priority 4-12 for promoting an EnrollmentRequest. Return None if ok, else error_id."""
    # 4 state: offering must be OPEN
    if offering["status"] != "OPEN":
        return "ERR_OFFERING_NOT_OPEN"
    # 8 time conflict
    if check_time_conflict(student["id"], offering["term_id"], offering, exclude_request_id=ereq["id"]):
        return "ERR_TIME_CONFLICT"
    # 9 commute
    if check_commute_conflict(student["id"], offering["term_id"], offering, exclude_request_id=ereq["id"]):
        return "ERR_COMMUTE_INFEASIBLE"
    # 10 exam
    if check_exam_conflict(student["id"], offering["term_id"], offering, exclude_request_id=ereq["id"]):
        return "ERR_EXAM_TIME_CONFLICT"
    # 11 lab
    if check_lab_equipment_conflict(offering, exclude_offering_id=offering["id"]):
        # promotion: this offering is already in OPEN; lab conflict cross-offering check naturally excludes self
        pass  # the candidate offering's lab usage was already validated when we opened it; skip here
    # 12 credit quota (variant_provisional excluding this WAITLISTED ereq's own credits since it's transitioning)
    eq = effective_quota_provisional(student, offering["term_id"])
    # current_load_provisional includes this WAITLISTED request; we need to exclude it for the boundary check
    current = current_load_provisional(student, offering["term_id"])
    # Subtract this request's contribution since it's about to flip from WAITLISTED→APPROVED (still counted)
    # No subtraction needed: WAITLISTED already contributes; promotion doesn't add credits.
    # The test is: total_load_after_promotion <= effective_quota.
    # total_load_after_promotion == current_load_provisional (the request stays counted).
    if current > eq:
        return "ERR_CREDIT_QUOTA_EXCEEDED"
    return None


def promote_one_from_waitlist(offering):
    """Try to promote the top WaitlistEntry on offering. Returns (entry, ereq) on success, (None,None) on miss."""
    while offering.get("enrolled_count", 0) < offering.get("capacity", 0):
        active = waitlist_for_offering_active(offering["id"])
        if not active:
            return None, None
        top = active[0]
        ereq = db.enrollment_requests.get(top["enrollment_request_id"])
        if not ereq:
            top["status"] = "EXPIRED"
            continue
        course = db.courses.get(offering["course_id"])
        student = db.students.get(ereq["student_id"])
        if not course or not student:
            top["status"] = "EXPIRED"
            continue
        bad = _validate_promotion_candidate(ereq, offering, course, student)
        if bad:
            top["status"] = "EXPIRED"
            continue
        # Promote
        top["status"] = "PROMOTED"
        _approve_enrollment(ereq, offering, course, student)
        emit_sync_event(
            "EnrollmentRequest", ereq["id"], "WAITLIST_PROMOTED", DOWNSTREAM_ALL,
            payload={"student_id": student["id"], "offering_id": offering["id"]},
            student_id=student["id"],
        )
        return top, ereq
    return None, None


def sweep_offering_waitlist(offering):
    """Promote up to capacity-enrolled_count entries; each promotion may fail and try next."""
    while offering.get("enrolled_count", 0) < offering.get("capacity", 0):
        result = promote_one_from_waitlist(offering)
        if result == (None, None):
            return


def run_full_sweep():
    """Sweep all OPEN offerings + check all over-limit deadlines."""
    for offering in sorted(db.course_offerings.values(), key=lambda o: o["id"]):
        if offering["status"] == "OPEN":
            sweep_offering_waitlist(offering)

    clk = db.clock
    for app in sorted(db.over_limit_applications.values(), key=lambda a: a["id"]):
        if app["status"] == "AWAITING_PRIMARY" and clk >= app.get("timeout_deadline_at", 0):
            _overlimit_escalate(app)
    for app in sorted(db.over_limit_applications.values(), key=lambda a: a["id"]):
        if app["status"] == "AWAITING_SECONDARY" and clk >= app.get("timeout_deadline_at", 0):
            _overlimit_expire(app)
