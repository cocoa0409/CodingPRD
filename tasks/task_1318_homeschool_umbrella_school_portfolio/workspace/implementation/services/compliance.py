"""compliance_standing_derivation + the compliance sweep."""
from datetime import date as _date
from datetime import datetime, time, timezone

import clock
import db
from services import core
from services import coop as coop_svc


def _parse_date(d):
    y, m, dd = (int(x) for x in d.split("-"))
    return _date(y, m, dd)


def _start_of_day(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _end_of_day(d):
    return datetime.combine(d, time(23, 59, 59, 999999), tzinfo=timezone.utc)


def hard_violation(enrollment, year):
    now = clock.now()
    # Notice of intent not acknowledged past the filing deadline
    has_ack = any(
        n["enrollment_id"] == enrollment["id"] and n["status"] == "ACKNOWLEDGED"
        for n in db.notices.values()
    )
    if not has_ack and now > clock.parse(year["notice_filing_deadline"]):
        return True
    end_of_year = _end_of_day(_parse_date(year["end_date"]))
    if now > end_of_year:
        # Testing required but unsatisfied
        if enrollment["testing_required"] and not enrollment["testing_satisfied"]:
            return True
        # Certified progress shortfall
        if enrollment["certified_days_counted"] < year["required_instructional_days"]:
            return True
        minutes_required = (
            year["required_minutes_elementary"]
            if enrollment["grade_level"] <= 5
            else year["required_minutes_secondary"]
        )
        if enrollment["certified_minutes_credited"] < minutes_required:
            return True
    # Rejected portfolio
    for pf in db.portfolios.values():
        if pf["enrollment_id"] == enrollment["id"] and pf["status"] == "REJECTED":
            return True
    return False


def soft_violation(enrollment, year):
    now = clock.now()
    end_of_year = _end_of_day(_parse_date(year["end_date"]))
    # Portfolio not accepted past its soft deadline (before year end)
    has_accepted = any(
        pf["enrollment_id"] == enrollment["id"] and pf["status"] == "ACCEPTED"
        for pf in db.portfolios.values()
    )
    if not has_accepted and now > clock.parse(year["portfolio_due_date"]) and now <= end_of_year:
        return True
    # Mid-year pace check
    mid = _start_of_day(_parse_date(year["mid_year_date"]))
    if now > mid and now <= end_of_year:
        if enrollment["provisional_days_counted"] * 2 < year["required_instructional_days"]:
            return True
    return False


def derive_standing(enrollment, year):
    if hard_violation(enrollment, year):
        return "NONCOMPLIANT"
    if soft_violation(enrollment, year):
        return "PROBATION"
    return "GOOD_STANDING"


def apply_standing(enrollment, target):
    """Set standing; fire co-op cascade on entry into NONCOMPLIANT."""
    prev = enrollment["compliance_standing"]
    if prev == target:
        return
    enrollment["compliance_standing"] = target
    core.touch(enrollment)
    if target == "NONCOMPLIANT":
        coop_svc.noncompliant_cascade(enrollment)


def run_sweep(year):
    """The compliance sweep: standing recompute, year-end completion, class advancement."""
    now = clock.now()
    end_of_year = _end_of_day(_parse_date(year["end_date"]))

    for en in list(db.enrollments.values()):
        if en["academic_year_id"] != year["id"]:
            continue
        if en["enrollment_status"] not in ("REGISTERED", "ACTIVE", "COMPLETED"):
            continue
        if en["standing_locked"]:
            continue
        target = derive_standing(en, year)
        apply_standing(en, target)
        # Year-end completion
        if (
            en["enrollment_status"] == "ACTIVE"
            and now > end_of_year
            and en["compliance_standing"] != "NONCOMPLIANT"
        ):
            en["enrollment_status"] = "COMPLETED"
            core.touch(en)

    # Co-op class lifecycle advancement
    for cls in list(db.coop_classes.values()):
        if cls["academic_year_id"] != year["id"]:
            continue
        start = _start_of_day(_parse_date(cls["start_date"]))
        end = _end_of_day(_parse_date(cls["end_date"]))
        if cls["status"] == "OPEN" and now >= start:
            cls["status"] = "IN_SESSION"
            core.touch(cls)
        if cls["status"] == "IN_SESSION" and now > end:
            cls["status"] = "COMPLETED"
            core.touch(cls)
            for ce in list(db.coop_enrollments.values()):
                if ce["coop_class_id"] == cls["id"] and ce["status"] == "CONFIRMED":
                    ce["status"] = "COMPLETED"
                    core.touch(ce)

    core.touch(year)
