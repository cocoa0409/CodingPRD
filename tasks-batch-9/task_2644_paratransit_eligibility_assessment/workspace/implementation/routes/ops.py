"""PRD 2.9 / 2.11 — the logical clock and the day-close sweep."""

from flask import Blueprint

import lookups
import mirrors
import shapes
from auth import require
from envelope import ok
from store import date_of, db, iso, now, ordered, plus_days, today, touch

bp = Blueprint("ops", __name__)

APPEAL_DECISION_WINDOW_DAYS = 30
PRESUMPTIVE_PENDING_DAYS = 21
PRESUMPTIVE_EXCLUDED_STATUSES = ("DRAFT", "RETURNED_INCOMPLETE", "DETERMINED")


@bp.post("/_clock/set_current_utc")
@require(("AccessibilityOfficeAdmin",))
def set_clock():
    payload = shapes.body()
    current_utc = shapes.req_instant(payload, "current_utc")
    # PRD 2.9: the response echoes the accepted instant and mutates no record.
    db.clock = current_utc
    return ok({"current_utc": iso(current_utc)})


def _step1_hearings_held():
    """Every appeal in HEARING_SCHEDULED whose hearing_at is at or before the
    current instant advances to HEARD."""
    instant = now()
    advanced = 0
    for appeal in ordered(db.appeals.values()):
        if appeal["status"] != "HEARING_SCHEDULED":
            continue
        if appeal["hearing_at"] is None or appeal["hearing_at"] > instant:
            continue
        appeal["status"] = "HEARD"
        appeal["heard_at"] = instant
        appeal["decision_due_date"] = plus_days(
            date_of(instant), APPEAL_DECISION_WINDOW_DAYS
        )
        touch(appeal)
        advanced += 1
    return advanced


def _step2_suspensions():
    """Response lapses, then service starts, then service completions — three
    sequential passes, so one proceeding may advance twice in one sweep."""
    day = today()
    advanced = 0

    for proceeding in ordered(db.proceedings.values()):
        if proceeding["status"] != "NOTICE_SENT":
            continue
        deadline = proceeding["response_deadline_date"]
        if deadline is None or not deadline < day:
            continue
        # Nothing but the status and updated_at changes: the lapse is the
        # due-process evidence.
        proceeding["status"] = "RESPONSE_LAPSED"
        touch(proceeding)
        advanced += 1

    for proceeding in ordered(db.proceedings.values()):
        if proceeding["status"] != "UPHELD_PENDING":
            continue
        start = proceeding["suspension_start_date"]
        if start is None or start > day:
            continue
        proceeding["status"] = "ACTIVE"
        touch(proceeding)
        applicant = db.applicants.get(proceeding["applicant_id"])
        if applicant is not None:
            # service_status is a derived mirror; the rider row is still
            # touched because the sweep changed what it reads.
            touch(applicant)
        advanced += 1

    for proceeding in ordered(db.proceedings.values()):
        if proceeding["status"] != "ACTIVE":
            continue
        end = proceeding["suspension_end_date"]
        if end is None or not end < day:
            continue
        proceeding["status"] = "SERVED"
        proceeding["days_served"] = proceeding["duration_days"]
        proceeding["days_forgiven"] = 0
        touch(proceeding)
        applicant = db.applicants.get(proceeding["applicant_id"])
        if applicant is not None:
            touch(applicant)
        advanced += 1

    return advanced


def _step3_determination_expiry():
    """The three-hop cascade of PRD 3.5."""
    day = today()
    expired = 0
    withdrawn = 0
    for det in ordered(db.determinations.values()):
        if det["status"] != "ISSUED":
            continue
        if det["expires_at"] is None or det["expires_at"] > day:
            continue
        # Hop 1
        det["status"] = "EXPIRED"
        touch(det)
        expired += 1
        # Hop 2
        applicant = db.applicants.get(det["applicant_id"])
        if applicant is not None:
            mirrors.set_eligibility(applicant, "EXPIRED", None, None)
        # Hop 3
        withdrawn += mirrors.withdraw_referrals_for_lapse(det["applicant_id"])
    return expired, withdrawn


def _step4_presumptive():
    """PRD 3.2: all four conditions must hold at the moment the sweep looks."""
    instant = now()
    granted = 0
    for app_rec in ordered(db.applications.values()):
        statutory = _statutory_days(app_rec)
        if statutory < PRESUMPTIVE_PENDING_DAYS:
            continue
        if app_rec["status"] in PRESUMPTIVE_EXCLUDED_STATUSES:
            continue
        if app_rec["presumptive_granted_at"] is not None:
            continue
        if lookups.issued_determination_of(app_rec["applicant_id"]) is not None:
            continue
        app_rec["presumptive_granted_at"] = instant
        touch(app_rec)
        applicant = db.applicants.get(app_rec["applicant_id"])
        if applicant is not None:
            mirrors.set_eligibility_status(applicant, "PRESUMPTIVE")
        granted += 1
    return granted


def _statutory_days(app_rec):
    import serializers

    statutory, _net = serializers.pending_days(app_rec)
    return statutory


def _step5_overdue_appeals():
    """A reviewer who lets the clock run out does not cost the rider service."""
    day = today()
    extended = 0
    for appeal in ordered(db.appeals.values()):
        if appeal["status"] != "HEARD" or appeal["outcome"] is not None:
            continue
        due = appeal["decision_due_date"]
        if due is None or not due < day:
            continue
        # Guarded so a second sweep at a fixed clock changes nothing.
        if appeal["continued_service_extended"]:
            continue
        appeal["continued_service_extended"] = True
        touch(appeal)
        applicant_id = lookups.appeal_owner_applicant_id(appeal)
        applicant = db.applicants.get(applicant_id)
        if applicant is not None:
            mirrors.set_eligibility_status(applicant, "PRESUMPTIVE")
        extended += 1
    return extended


@bp.post("/_ops/day-close")
@require(("AccessibilityOfficeAdmin",))
def day_close():
    appeals_heard_count = _step1_hearings_held()
    proceedings_advanced_count = _step2_suspensions()
    determinations_expired_count, referrals_withdrawn_count = _step3_determination_expiry()
    presumptive_granted_count = _step4_presumptive()
    appeals_overdue_count = _step5_overdue_appeals()
    return ok(
        {
            "appeals_heard_count": appeals_heard_count,
            "proceedings_advanced_count": proceedings_advanced_count,
            "determinations_expired_count": determinations_expired_count,
            "referrals_withdrawn_count": referrals_withdrawn_count,
            "presumptive_granted_count": presumptive_granted_count,
            "appeals_overdue_count": appeals_overdue_count,
        }
    )
