"""Deduction events and the bounded dispute cycle (PRD 3.5 / 3.6)."""

from flask import Blueprint

import calc
from db import db, insert, public, setf
from errors import fail
from middleware import (ROLE_AUTHORITY_OFFICER, ROLE_CONCESSIONAIRE, actor, body,
                        concession_of_period, event_of_dispute, get_dispute, get_event,
                        get_period, owner_guard, period_of_event, req_enum, req_int,
                        req_str, require_auth, sod_guard)
from response import created, ok

bp = Blueprint("deductions", __name__)

OFFICER_DEDUCTION_TYPES = ("UNAVAILABILITY", "PERFORMANCE_FAILURE")
ALL_DEDUCTION_TYPES = ("UNAVAILABILITY", "PERFORMANCE_FAILURE",
                       "SELF_REPORT_UNDERSTATEMENT", "HANDBACK_SHORTFALL")
OPEN_DISPUTE_STATUSES = ("RAISED", "REFERRED_BACK", "RESUBMITTED")


@bp.post("/ppp/service-periods/<row_id>/deduction-events")
def issue_event(row_id):
    require_auth(ROLE_AUTHORITY_OFFICER)
    period = get_period(row_id)
    concession = concession_of_period(period)
    data = body()

    raw_report_id = data.get("performance_report_id")
    report = None
    if raw_report_id is not None:
        if not isinstance(raw_report_id, str) or raw_report_id == "":
            fail("ERR_INVALID_REQUEST", "Field 'performance_report_id' must be a string.")
        report = db.tables["reports"].get(raw_report_id)
        if report is None:
            fail("ERR_REFERENCED_ENTITY_NOT_FOUND")

    deduction_type = req_enum(data, "deduction_type", ALL_DEDUCTION_TYPES)
    points = req_int(data, "points", minimum=1)
    if deduction_type not in OFFICER_DEDUCTION_TYPES:
        fail("ERR_INVALID_REQUEST",
             "deduction_type '%s' is raised by the system only." % deduction_type)

    if concession["status"] not in ("OPERATIONS", "STEP_IN"):
        fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")

    if report is not None and report["service_period_id"] != period["id"]:
        fail("ERR_CROSS_ENTITY_MISMATCH")

    event = calc.issue_deduction_event(
        period, deduction_type, points, actor(),
        report_id=report["id"] if report is not None else None)

    calc.price_period(period)
    projected = calc.recompute_ytd(concession)
    calc.annual_cap_guard(concession, projected)
    calc.recompute_points_and_breach(concession)
    return created(public(event))


@bp.post("/ppp/deduction-events/<row_id>/withdraw")
def withdraw_event(row_id):
    require_auth(ROLE_AUTHORITY_OFFICER)
    event = get_event(row_id)
    period = period_of_event(event)
    concession = concession_of_period(period)
    data = body()
    reason = req_str(data, "withdrawal_reason", max_len=2000)
    if event["status"] not in ("ISSUED", "DISPUTED"):
        fail("ERR_INVALID_STATE_TRANSITION")

    setf(event, "withdrawal_reason", reason)
    setf(event, "status", "WITHDRAWN")
    setf(event, "allowed_amount_cents", 0)
    setf(event, "pro_rata_amount_cents", 0)

    for dispute in calc.open_disputes_for_event(event["id"]):
        setf(dispute, "status", "UPHELD")
        setf(dispute, "outcome_note", "WITHDRAWN_BY_AUTHORITY")
        setf(dispute, "adjudicated_by_user_id", "SYSTEM")
        setf(dispute, "adjudicated_at", db.now_str())

    calc.price_period(period)
    calc.mark_adjusted_if_repriced(period)
    calc.recompute_ytd(concession)
    calc.recompute_points_and_breach(concession)
    return ok(public(event))


# ------------------------------------------------------------------ disputes
@bp.post("/ppp/deduction-events/<row_id>/disputes")
def raise_dispute(row_id):
    require_auth(ROLE_CONCESSIONAIRE)
    event = get_event(row_id)
    period = period_of_event(event)
    concession = concession_of_period(period)
    owner_guard(concession)
    data = body()
    grounds = req_str(data, "grounds", max_len=2000)

    if event["status"] != "ISSUED":
        if event["status"] == "DISPUTED" and calc.open_disputes_for_event(event["id"]):
            fail("ERR_DISPUTE_ALREADY_OPEN")
        fail("ERR_INVALID_STATE_TRANSITION")
    if period["reporting_status"] != "VERIFIED":
        fail("ERR_CROSS_ENTITY_MISMATCH")
    if calc.open_disputes_for_event(event["id"]):
        fail("ERR_DISPUTE_ALREADY_OPEN")

    dispute = insert("disputes", {
        "deduction_event_id": event["id"],
        "raised_by_user_id": actor(),
        "grounds": grounds,
        "round_no": 1,
        "status": "RAISED",
        "referred_back_reason": None,
        "adjudicated_by_user_id": None,
        "adjudicated_at": None,
        "outcome_note": None,
    })
    setf(event, "status", "DISPUTED")
    return created(public(dispute))


@bp.post("/ppp/deduction-disputes/<row_id>/refer-back")
def refer_back(row_id):
    require_auth(ROLE_AUTHORITY_OFFICER)
    dispute = get_dispute(row_id)
    data = body()
    reason = req_str(data, "referred_back_reason", max_len=2000)
    if dispute["status"] not in ("RAISED", "RESUBMITTED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    if dispute["round_no"] >= calc.DISPUTE_MAX_ROUNDS:
        fail("ERR_DISPUTE_ROUNDS_EXHAUSTED")
    setf(dispute, "referred_back_reason", reason)
    setf(dispute, "status", "REFERRED_BACK")
    return ok(public(dispute))


@bp.post("/ppp/deduction-disputes/<row_id>/resubmit")
def resubmit_dispute(row_id):
    require_auth(ROLE_CONCESSIONAIRE)
    dispute = get_dispute(row_id)
    event = event_of_dispute(dispute)
    owner_guard(concession_of_period(period_of_event(event)))
    data = body()
    grounds = req_str(data, "grounds", max_len=2000)
    if dispute["status"] != "REFERRED_BACK":
        fail("ERR_INVALID_STATE_TRANSITION")
    if dispute["round_no"] >= calc.DISPUTE_MAX_ROUNDS:
        fail("ERR_DISPUTE_ROUNDS_EXHAUSTED")
    setf(dispute, "grounds", grounds)
    setf(dispute, "round_no", dispute["round_no"] + 1)
    setf(dispute, "status", "RESUBMITTED")
    return ok(public(dispute))


@bp.post("/ppp/deduction-disputes/<row_id>/adjudicate")
def adjudicate_dispute(row_id):
    require_auth(ROLE_AUTHORITY_OFFICER)
    dispute = get_dispute(row_id)
    event = event_of_dispute(dispute)
    period = period_of_event(event)
    concession = concession_of_period(period)
    data = body()
    decision = req_enum(data, "decision", ("UPHOLD", "REJECT"))
    outcome_note = req_str(data, "outcome_note", max_len=2000)
    if dispute["status"] not in OPEN_DISPUTE_STATUSES:
        fail("ERR_INVALID_STATE_TRANSITION")
    sod_guard(event["issued_by_user_id"])

    setf(dispute, "adjudicated_by_user_id", actor())
    setf(dispute, "adjudicated_at", db.now_str())
    setf(dispute, "outcome_note", outcome_note)

    if decision == "UPHOLD":
        setf(dispute, "status", "UPHELD")
        setf(event, "status", "OVERTURNED")
        setf(event, "allowed_amount_cents", 0)
        setf(event, "pro_rata_amount_cents", 0)
        calc.price_period(period)
        calc.mark_adjusted_if_repriced(period)
        calc.recompute_ytd(concession)
        calc.recompute_points_and_breach(concession)
    else:
        setf(dispute, "status", "REJECTED")
        setf(event, "status", "ISSUED")
    return ok(public(dispute))
