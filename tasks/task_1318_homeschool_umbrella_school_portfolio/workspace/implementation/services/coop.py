"""Co-op domain services: overlap checks, waitlist promotion, drop cascades."""
from datetime import date as _date

import clock
import db
from services import core
from services import fees


def _parse_date(d):
    y, m, dd = (int(x) for x in d.split("-"))
    return _date(y, m, dd)


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start,end) intersection; adjacency (touching) is allowed."""
    return a_start < b_end and b_start < a_end


def student_confirmed_coop_classes(enrollment):
    """CoopClasses in which the student of this enrollment holds CONFIRMED membership."""
    student = core.student_of_enrollment(enrollment)
    if not student:
        return []
    classes = []
    for en in db.enrollments.values():
        if en["student_id"] != student["id"]:
            continue
        for ce in db.coop_enrollments.values():
            if ce["enrollment_id"] != en["id"] or ce["status"] != "CONFIRMED":
                continue
            cls = db.coop_classes.get(ce["coop_class_id"])
            if cls:
                classes.append(cls)
    return classes


def has_schedule_overlap(enrollment, target_class, exclude_coop_enrollment_id=None):
    student = core.student_of_enrollment(enrollment)
    if not student:
        return False
    for en in db.enrollments.values():
        if en["student_id"] != student["id"]:
            continue
        for ce in db.coop_enrollments.values():
            if ce["enrollment_id"] != en["id"] or ce["status"] != "CONFIRMED":
                continue
            if exclude_coop_enrollment_id and ce["id"] == exclude_coop_enrollment_id:
                continue
            cls = db.coop_classes.get(ce["coop_class_id"])
            if not cls or cls["id"] == target_class["id"]:
                continue
            if cls["meeting_day"] != target_class["meeting_day"]:
                continue
            if windows_overlap(
                cls["meeting_start_minutes"], cls["meeting_end_minutes"],
                target_class["meeting_start_minutes"], target_class["meeting_end_minutes"],
            ):
                return True
    return False


def waitlist_promotion(coop_class):
    """Promote waitlisted coop enrollments into freed seats, one at a time."""
    while coop_class["seats_taken"] < coop_class["capacity"]:
        candidates = []
        for ce in db.coop_enrollments.values():
            if ce["coop_class_id"] != coop_class["id"] or ce["status"] != "WAITLISTED":
                continue
            en = db.enrollments.get(ce["enrollment_id"])
            if not en:
                continue
            if en["enrollment_status"] != "ACTIVE":
                continue
            if en["compliance_standing"] == "NONCOMPLIANT":
                continue
            if not (coop_class["grade_min"] <= en["grade_level"] <= coop_class["grade_max"]):
                continue
            if has_schedule_overlap(en, coop_class, exclude_coop_enrollment_id=ce["id"]):
                continue
            candidates.append((ce, en))
        if not candidates:
            break
        candidates.sort(key=lambda pair: (pair[0]["created_at"], pair[1]["created_at"]))
        ce, en = candidates[0]
        promote(ce, en, coop_class)


def promote(coop_enrollment, enrollment, coop_class):
    student = core.student_of_enrollment(enrollment)
    family = core.family_of_student(student)
    discount = fees.compute_discount_pct(
        coop_class, student["family_id"], enrollment["academic_year_id"],
        coop_enrollment["created_at"],
    )
    fee_cents = fees.compute_fee_cents(coop_class, discount)
    coop_enrollment["discount_pct_applied"] = discount
    coop_enrollment["fee_cents"] = fee_cents
    coop_enrollment["status"] = "CONFIRMED"
    coop_enrollment["promoted_at"] = clock.now_iso()
    core.touch(coop_enrollment)
    fees.charge_family(family, fee_cents)
    coop_class["seats_taken"] += 1
    core.touch(coop_class)


def drop_coop_enrollment(coop_enrollment, drop_reason, run_promotion=True):
    """CONFIRMED -> DROPPED with refund waterfall, family credit, seat release."""
    coop_class = db.coop_classes.get(coop_enrollment["coop_class_id"])
    enrollment = db.enrollments.get(coop_enrollment["enrollment_id"])
    family = core.family_of_enrollment(enrollment)
    refund = fees.compute_refund(coop_enrollment, coop_class, drop_reason)
    coop_enrollment["refund_cents"] = refund
    coop_enrollment["drop_reason"] = drop_reason
    coop_enrollment["status"] = "DROPPED"
    core.touch(coop_enrollment)
    if refund:
        fees.credit_family(family, refund)
    coop_class["seats_taken"] -= 1
    core.touch(coop_class)
    if run_promotion:
        waitlist_promotion(coop_class)


def cancel_waitlisted(coop_enrollment):
    coop_enrollment["status"] = "CANCELLED"
    core.touch(coop_enrollment)


def noncompliant_cascade(enrollment):
    """Fire on entry into NONCOMPLIANT: drop CONFIRMED co-ops (SCHOOL_STANDING,
    full refund), cancel WAITLISTED ones; each freed seat runs promotion."""
    classes_to_promote = []
    for ce in list(db.coop_enrollments.values()):
        if ce["enrollment_id"] != enrollment["id"]:
            continue
        if ce["status"] == "CONFIRMED":
            coop_class = db.coop_classes.get(ce["coop_class_id"])
            drop_coop_enrollment(ce, "SCHOOL_STANDING", run_promotion=False)
            if coop_class is not None:
                classes_to_promote.append(coop_class)
        elif ce["status"] == "WAITLISTED":
            cancel_waitlisted(ce)
    seen = set()
    for cls in classes_to_promote:
        if cls["id"] in seen:
            continue
        seen.add(cls["id"])
        waitlist_promotion(cls)
