"""Regulatory sweep: advances the regulatory epoch in pinned order."""

from datetime import timedelta, datetime, timezone
import db
from services.calculations import compute_pass_rate, _extract_date


def run_sweep():
    """Execute the 5-phase regulatory sweep. Returns summary counts."""
    today = db.today()
    now = db.get_clock()

    counts = {
        "approvals_expired": 0,
        "instructor_approvals_expired": 0,
        "grants_suspended": 0,
        "offerings_advanced": 0,
        "enrollments_expired": 0,
        "attempts_no_show": 0,
        "schools_evaluated": 0,
    }

    # Phase 1: Approval aging
    counts["approvals_expired"], counts["grants_suspended"] = _sweep_course_approvals(today)
    counts["instructor_approvals_expired"] = _sweep_instructor_approvals(today)

    # Phase 2: Offering advancement
    counts["offerings_advanced"] = _sweep_offerings(today)

    # Phase 3: Enrollment expiry
    counts["enrollments_expired"] = _sweep_enrollments(today)

    # Phase 4: Exam attempt no-show
    counts["attempts_no_show"] = _sweep_exam_attempts(now)

    # Phase 5: School pass-rate evaluation
    counts["schools_evaluated"] = _sweep_schools(today)

    return counts


def _sweep_course_approvals(today):
    """Phase 1a: Course approval aging."""
    expired_count = 0
    grants_suspended = 0

    for approval in list(db.course_approvals.values()):
        if approval["status"] == "APPROVED":
            valid_until = _extract_date(approval.get("valid_until"))
            if valid_until is None:
                continue
            days_until_expiry = (valid_until - today).days
            if 0 <= days_until_expiry <= 30:
                approval["status"] = "EXPIRING"
                db.touch(approval)
                db.audit("CourseApproval", approval["id"], "STATUS_CHANGE",
                         "system", "system",
                         {"from_status": "APPROVED", "to_status": "EXPIRING"})
        elif approval["status"] == "EXPIRING":
            valid_until = _extract_date(approval.get("valid_until"))
            if valid_until is not None and today > valid_until:
                approval["status"] = "EXPIRED"
                db.touch(approval)
                db.audit("CourseApproval", approval["id"], "STATUS_CHANGE",
                         "system", "system",
                         {"from_status": "EXPIRING", "to_status": "EXPIRED"})
                expired_count += 1
                # Cascade: suspend grants
                course_id = approval["course_id"]
                state_code = approval["state_code"]
                for grant in db.equivalency_grants.values():
                    if (grant["course_id"] == course_id
                            and grant["home_state_code"] == state_code
                            and grant["status"] == "ACTIVE"):
                        grant["status"] = "SUSPENDED"
                        db.touch(grant)
                        db.audit("EquivalencyGrant", grant["id"], "STATUS_CHANGE",
                                 "system", "system",
                                 {"from_status": "ACTIVE", "to_status": "SUSPENDED"})
                        grants_suspended += 1

    return expired_count, grants_suspended


def _sweep_instructor_approvals(today):
    """Phase 1b: Instructor approval aging."""
    expired_count = 0

    for approval in list(db.instructor_approvals.values()):
        if approval["status"] == "APPROVED":
            valid_until = _extract_date(approval.get("valid_until"))
            if valid_until is None:
                continue
            days_until_expiry = (valid_until - today).days
            if 0 <= days_until_expiry <= 30:
                approval["status"] = "EXPIRING"
                db.touch(approval)
                db.audit("InstructorApproval", approval["id"], "STATUS_CHANGE",
                         "system", "system",
                         {"from_status": "APPROVED", "to_status": "EXPIRING"})
        elif approval["status"] == "EXPIRING":
            valid_until = _extract_date(approval.get("valid_until"))
            if valid_until is not None and today > valid_until:
                approval["status"] = "EXPIRED"
                db.touch(approval)
                db.audit("InstructorApproval", approval["id"], "STATUS_CHANGE",
                         "system", "system",
                         {"from_status": "EXPIRING", "to_status": "EXPIRED"})
                expired_count += 1

    return expired_count


def _sweep_offerings(today):
    """Phase 2: Offering advancement."""
    advanced = 0

    for offering in list(db.offerings.values()):
        if offering["status"] == "PUBLISHED":
            start_d = _extract_date(offering["start_date"])
            if start_d is not None and today >= start_d:
                offering["status"] = "IN_SESSION"
                db.touch(offering)
                db.audit("CourseOffering", offering["id"], "STATUS_CHANGE",
                         "system", "system",
                         {"from_status": "PUBLISHED", "to_status": "IN_SESSION"})
                advanced += 1
        elif offering["status"] == "IN_SESSION":
            end_d = _extract_date(offering["end_date"])
            if end_d is not None and today > end_d:
                offering["status"] = "COMPLETED"
                db.touch(offering)
                db.audit("CourseOffering", offering["id"], "STATUS_CHANGE",
                         "system", "system",
                         {"from_status": "IN_SESSION", "to_status": "COMPLETED"})
                advanced += 1

    return advanced


def _sweep_enrollments(today):
    """Phase 3: Enrollment expiry."""
    expired = 0

    for enrollment in list(db.enrollments.values()):
        if enrollment["academic_status"] in ("ENROLLED", "IN_PROGRESS", "SEAT_TIME_MET", "EXAM_PASSED"):
            deadline = _extract_date(enrollment.get("deadline_date"))
            if deadline is not None and today > deadline:
                old_status = enrollment["academic_status"]
                enrollment["academic_status"] = "EXPIRED"
                db.touch(enrollment)
                db.audit("Enrollment", enrollment["id"], "STATUS_CHANGE",
                         "system", "system",
                         {"from_status": old_status, "to_status": "EXPIRED"})
                expired += 1
                # Recompute offering counts
                offering = db.offerings.get(enrollment["offering_id"])
                if offering:
                    from services.calculations import update_offering_counts
                    update_offering_counts(offering)
                    db.touch(offering)

    return expired


def _sweep_exam_attempts(now):
    """Phase 4: SCHEDULED attempts more than 24h past scheduled_at -> NO_SHOW."""
    no_show = 0
    cutoff = now - timedelta(hours=24)

    for attempt in list(db.exam_attempts.values()):
        if attempt["status"] == "SCHEDULED":
            scheduled_at_str = attempt.get("scheduled_at")
            if scheduled_at_str:
                try:
                    s_clean = scheduled_at_str.replace("Z", "+00:00")
                    sched_dt = datetime.fromisoformat(s_clean)
                    if sched_dt.tzinfo is None:
                        sched_dt = sched_dt.replace(tzinfo=timezone.utc)
                    if now > sched_dt + timedelta(hours=24):
                        attempt["status"] = "NO_SHOW"
                        db.touch(attempt)
                        db.audit("ExamAttempt", attempt["id"], "STATUS_CHANGE",
                                 "system", "system",
                                 {"from_status": "SCHEDULED", "to_status": "NO_SHOW"})
                        no_show += 1
                except (ValueError, TypeError):
                    pass

    return no_show


def _sweep_schools(today):
    """Phase 5: School pass-rate evaluation and posture update."""
    evaluated = 0

    for school in list(db.schools.values()):
        result = compute_pass_rate(school["id"], today)
        evaluated += 1

        school["last_evaluation_attempt_count"] = result["first_attempt_count"]
        school["last_evaluation_first_attempt_pass_rate_bps"] = result["first_attempt_pass_rate_bps"]

        first_count = result["first_attempt_count"]
        first_rate = result["first_attempt_pass_rate_bps"]
        threshold = school.get("pass_rate_threshold_bps", 6000)

        if first_count >= 10 and first_rate is not None:
            old_posture = school["posture"]
            if first_rate < threshold:
                school["posture"] = "PROBATION"
            else:
                school["posture"] = "GOOD_STANDING"

            if school["posture"] != old_posture:
                db.audit("School", school["id"], "STATUS_CHANGE",
                         "system", "system",
                         {"from_status": old_posture, "to_status": school["posture"]})

        db.touch(school)

    return evaluated
