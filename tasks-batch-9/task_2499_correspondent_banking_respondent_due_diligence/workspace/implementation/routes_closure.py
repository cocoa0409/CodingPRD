"""Orderly closure: drafting, approval, progression and settlement (PRD 3.9)."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import clock
import store
from common import (OPS, arg, eq, need, need_respondent, paged, start, PREFIX)
from errors import fail
from response import ok, ok_list
from validate import body, dec, fenum, fint, q2, validate

bp = Blueprint("closure", __name__)

TERMINATION_REASONS = ("UNRESPONSIVE", "SANCTIONS_EXPOSURE", "PROHIBITED_NESTING",
                       "RISK_APPETITE", "COMMERCIAL", "REGULATORY_ACTION")
CAP_BASES = ("NONE", "FORWARD_PROJECTED", "CHRONOLOGICAL_ACTUAL")
REAL_BASES = ("FORWARD_PROJECTED", "CHRONOLOGICAL_ACTUAL")
ABORT_REASONS = ("RISK_RESOLVED", "COMMERCIAL_DECISION", "SUPERSEDED_PLAN")
OPEN_STATES = ("DRAFT", "PENDING_APPROVAL", "APPROVED", "NOTICE_SERVED", "WIND_DOWN")
LIVE_PAYMENTS = ("RECEIVED", "SCREENED_CLEAR", "HELD_FOR_REVIEW")


def _enter_exiting(resp, plan):
    """dd_state -> EXITING with payment_posture WIND_DOWN_ONLY and its cascades."""
    if resp["dd_state"] != "EXITING":
        plan["_pre_exit_dd_state"] = resp["dd_state"]
        plan["_pre_exit_restriction"] = resp["restriction_reason"]
    was_open = resp["payment_posture"] == "OPEN"
    resp["dd_state"] = "EXITING"
    resp["payment_posture"] = "WIND_DOWN_ONLY"
    store.touch(resp)
    if was_open:
        cascade.hold_cleared_payments(resp)
    cascade.cancel_cycles(resp, ("SCHEDULED", "IN_PROGRESS"), "RELATIONSHIP_EXITING")


def _restore(resp, plan):
    """Return the respondent to its pre-exit standing with posture SCREEN_ONLY."""
    pre = plan.get("_pre_exit_dd_state") or "APPROVED"
    if pre in ("EXITING", "TERMINATED", "PROSPECT", "DECLINED"):
        pre = "APPROVED"
    resp["dd_state"] = pre
    if pre == "RESTRICTED":
        resp["restriction_reason"] = plan.get("_pre_exit_restriction") \
            or resp["restriction_reason"] or "OFFICER_ACTION"
    else:
        resp["restriction_reason"] = None
    resp["payment_posture"] = "SCREEN_ONLY"
    store.touch(resp)


@bp.post(PREFIX + "/respondents/<respondent_id>/closure-plans")
def draft(respondent_id):
    ctx = start(("FIGRelationshipManager", "ComplianceAnalyst"))
    resp = need_respondent(respondent_id)
    data = body()
    validate(data, [
        fenum("termination_reason", TERMINATION_REASONS, True),
        fenum("cap_basis", CAP_BASES, True),
        fint("original_obligation_cents", True, 0),
    ])
    cascade.guard_not_closed(resp, allow_exiting=True)
    if cascade.open_plan(resp) is not None:
        fail("ERR_CLOSURE_PLAN_ALREADY_OPEN",
             "This respondent already holds an open closure plan.")
    obligation = int(data["original_obligation_cents"])
    row = store.insert("plans", {
        "respondent_bank_id": resp["id"],
        "termination_reason": data["termination_reason"],
        "state": "DRAFT",
        "cap_basis": data["cap_basis"],
        "notice_period_days": 0,
        "notice_served_at": None,
        "wind_down_end_at": None,
        "wind_down_cap_usd": q2("0.00"),
        "wind_down_released_usd": q2("0.00"),
        "original_obligation_cents": obligation,
        "outstanding_obligation_cents": obligation,
        "settled_cents": 0,
        "last_allocated_cents": 0,
        "allocation_round": 0,
        "allocation_lines": [],
        "return_rounds": 0,
        "drafted_by_user_id": ctx.user_id,
        "approved_by_user_id": None,
        "closed_at": None,
        "abort_reason": None,
    })
    row["notice_period_days"] = calc.notice_period_days(row, resp)
    _enter_exiting(resp, row)
    return ok(row, 201)


@bp.get(PREFIX + "/closure-plans")
def list_plans():
    start(OPS)
    rows = store.by_seq_desc(store.all_rows("plans"))
    rows = eq(rows, "respondent_bank_id", arg("respondent_bank_id"))
    rows = eq(rows, "state", arg("state"))
    rows = eq(rows, "termination_reason", arg("termination_reason"))
    page, limit, offset, total = paged(rows)
    return ok_list(page, limit, offset, total)


@bp.get(PREFIX + "/closure-plans/<plan_id>")
def read_plan(plan_id):
    start(OPS)
    return ok(need("plans", plan_id))


@bp.post(PREFIX + "/closure-plans/<plan_id>/submission")
def submission(plan_id):
    ctx = start(("FIGRelationshipManager", "ComplianceAnalyst"))
    row = need("plans", plan_id)
    resp = store.get("respondents", row["respondent_bank_id"])
    if resp["dd_state"] in ("PROSPECT", "DECLINED", "TERMINATED"):
        fail("ERR_INVALID_RESPONDENT_STATE",
             "This respondent state permits no closure submission.")
    cascade.guard_not_closed(resp, allow_exiting=True)
    if row["state"] != "DRAFT":
        fail("ERR_INVALID_CLOSURE_STATE", "Only a drafted plan may be submitted.")
    if ctx.user_id != row["drafted_by_user_id"]:
        fail("ERR_FORBIDDEN_ROLE",
             "Only the identity that drafted the plan may submit it.")
    if int(row["original_obligation_cents"]) != (
            int(row["outstanding_obligation_cents"]) + int(row["settled_cents"])):
        fail("ERR_INVALID_CLOSURE_STATE", "The obligation invariant does not hold.")
    row["state"] = "PENDING_APPROVAL"
    store.touch(row)
    return ok(row)


@bp.post(PREFIX + "/closure-plans/<plan_id>/approval")
def approval(plan_id):
    ctx = start(("CommitteeApprover",))
    row = need("plans", plan_id)
    data = body()
    validate(data, [
        fenum("action", ("APPROVE", "REJECT", "RETURN"), True),
        fenum("cap_basis", CAP_BASES, False),
    ])
    resp = store.get("respondents", row["respondent_bank_id"])
    cascade.guard_not_closed(resp, allow_exiting=True)
    action = data["action"]
    if row["state"] != "PENDING_APPROVAL":
        fail("ERR_INVALID_CLOSURE_STATE",
             "Only a plan pending approval may be decided.")
    if action == "RETURN" and int(row["return_rounds"]) > 1:
        fail("ERR_ROUNDS_EXHAUSTED", "The return budget of this plan is exhausted.")
    if ctx.user_id == row["drafted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The identity that drafted the plan may not approve it.")
    if resp["assessed_by_user_id"] and ctx.user_id == resp["assessed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The identity that assessed the respondent may not approve its exit.")
    if action == "APPROVE":
        if data.get("cap_basis") is not None:
            row["cap_basis"] = data["cap_basis"]
        if row["cap_basis"] not in REAL_BASES:
            fail("ERR_INVALID_REQUEST_BODY",
                 "cap_basis must be FORWARD_PROJECTED or CHRONOLOGICAL_ACTUAL.")
        row["notice_period_days"] = calc.notice_period_days(row, resp)
        row["wind_down_cap_usd"] = calc.wind_down_cap(row, resp)
        row["approved_by_user_id"] = ctx.user_id
        row["state"] = "APPROVED"
        store.touch(row)
        _enter_exiting(resp, row)
    elif action == "REJECT":
        row["state"] = "ABORTED"
        row["abort_reason"] = "COMMERCIAL_DECISION"
        store.touch(row)
        _restore(resp, row)
    else:
        row["return_rounds"] = int(row["return_rounds"]) + 1
        row["state"] = "DRAFT"
        store.touch(row)
    return ok(row)


ACTIONS = ("SERVE_NOTICE", "BEGIN_WIND_DOWN", "START_WIND_DOWN", "CLOSE", "ABORT")
FROM_STATES = {
    "SERVE_NOTICE": ("APPROVED",),
    "BEGIN_WIND_DOWN": ("NOTICE_SERVED",),
    "CLOSE": ("WIND_DOWN",),
    "ABORT": ("DRAFT", "PENDING_APPROVAL", "APPROVED"),
}


@bp.post(PREFIX + "/closure-plans/<plan_id>/progression")
def progression(plan_id):
    start(("FIGRelationshipManager", "ComplianceAnalyst"))
    row = need("plans", plan_id)
    data = body()
    validate(data, [
        fenum("action", ACTIONS, True),
        fenum("abort_reason", ABORT_REASONS, False),
    ])
    resp = store.get("respondents", row["respondent_bank_id"])
    cascade.guard_not_closed(resp, allow_exiting=True)
    action = data["action"]
    if action == "START_WIND_DOWN":
        action = "BEGIN_WIND_DOWN"
    if row["state"] not in FROM_STATES[action]:
        fail("ERR_INVALID_CLOSURE_STATE",
             "Action %s is not declared from state %s." % (action, row["state"]))
    if action == "SERVE_NOTICE":
        _serve_notice(row, resp)
    elif action == "BEGIN_WIND_DOWN":
        _begin_wind_down(row, resp)
    elif action == "CLOSE":
        _close(row, resp)
    else:
        _abort(row, resp, data.get("abort_reason"))
    return ok(row)


def _serve_notice(row, resp):
    if row["notice_period_days"] is None:
        fail("ERR_INVALID_CLOSURE_STATE", "The notice period has not been computed.")
    for rfi in store.rfis_of(resp["id"]):
        if rfi["state"] == "RESPONDED":
            fail("ERR_INVALID_RFI_STATE",
                 "An information request still awaits adjudication.")
    now = clock.now()
    store.set_dt(row, "notice_served_at", now)
    store.set_dt(row, "wind_down_end_at",
                 clock.add_days(now, int(row["notice_period_days"])))
    row["state"] = "NOTICE_SERVED"
    store.touch(row)
    cascade.terminate_all_nested(resp)


def _begin_wind_down(row, resp):
    served = store.dt(row, "notice_served_at")
    if served is not None and clock.now() < served:
        fail("ERR_INVALID_CLOSURE_STATE",
             "The logical clock has not reached notice_served_at.")
    for nested in store.nested_of(resp["id"]):
        if nested["state"] not in ("TERMINATED", "PROHIBITED"):
            fail("ERR_INVALID_CLOSURE_STATE",
                 "Every nested relationship must be terminated or prohibited first.")
    row["state"] = "WIND_DOWN"
    store.touch(row)
    resp["payment_posture"] = "WIND_DOWN_ONLY"
    store.touch(resp)


def _close(row, resp):
    end_at = store.dt(row, "wind_down_end_at")
    if end_at is None or clock.now() < end_at:
        fail("ERR_NOTICE_PERIOD_NOT_ELAPSED",
             "The notice period has not elapsed.")
    if int(row["outstanding_obligation_cents"]) != 0:
        fail("ERR_OBLIGATION_OUTSTANDING",
             "The settlement obligation is not fully allocated.")
    for pay in store.payments_of(resp["id"]):
        if pay["screening_state"] in LIVE_PAYMENTS:
            fail("ERR_INVALID_PAYMENT_STATE",
                 "A payment instruction of this respondent is still live.")
    store.set_dt(row, "closed_at", clock.now())
    row["state"] = "CLOSED"
    store.touch(row)
    resp["dd_state"] = "TERMINATED"
    resp["payment_posture"] = "BLOCKED"
    store.touch(resp)
    cascade.abandon_open_rfis(resp)


def _abort(row, resp, reason):
    if reason is None:
        fail("ERR_INVALID_REQUEST_BODY", "abort_reason is required to abort a plan.")
    if row["state"] == "APPROVED":
        for pay in store.payments_of(resp["id"]):
            if pay["screening_state"] == "HELD_FOR_REVIEW":
                fail("ERR_INVALID_PAYMENT_STATE",
                     "A held payment instruction must be disposed of first.")
    from_state = row["state"]
    row["state"] = "ABORTED"
    row["abort_reason"] = reason
    store.touch(row)
    if from_state != "DRAFT":
        _restore(resp, row)


@bp.post(PREFIX + "/closure-plans/<plan_id>/settlement-allocation")
def settlement_allocation(plan_id):
    start(("FIGRelationshipManager",))
    row = need("plans", plan_id)
    data = body()
    validate(data, [
        fenum("action", ("ALLOCATE", "REVERSE"), True),
        fint("amount_cents", True, None, None, 0),
    ])
    resp = store.get("respondents", row["respondent_bank_id"])
    cascade.guard_not_closed(resp, allow_exiting=True)
    if row["state"] not in ("APPROVED", "NOTICE_SERVED", "WIND_DOWN"):
        fail("ERR_INVALID_CLOSURE_STATE",
             "Only an approved, notice-served or winding-down plan may allocate.")
    amount = int(data["amount_cents"])
    if data["action"] == "ALLOCATE":
        if amount > int(row["outstanding_obligation_cents"]):
            fail("ERR_SETTLEMENT_EXCEEDS_OUTSTANDING",
                 "The allocation exceeds the outstanding obligation.")
        row["allocation_lines"] = calc.settlement_lines(resp, amount)
        row["settled_cents"] = int(row["settled_cents"]) + amount
        row["outstanding_obligation_cents"] = \
            int(row["outstanding_obligation_cents"]) - amount
        row["last_allocated_cents"] = amount
        row["allocation_round"] = int(row["allocation_round"]) + 1
    else:
        if int(row["allocation_round"]) < 1:
            fail("ERR_NO_ALLOCATION_TO_REVERSE",
                 "There is no allocation round to reverse.")
        if amount != int(row["last_allocated_cents"]):
            fail("ERR_REVERSAL_AMOUNT_MISMATCH",
                 "A reversal must carry exactly the last allocated amount.")
        row["settled_cents"] = int(row["settled_cents"]) - amount
        row["outstanding_obligation_cents"] = \
            int(row["outstanding_obligation_cents"]) + amount
        row["allocation_round"] = int(row["allocation_round"]) - 1
        row["last_allocated_cents"] = 0
        if int(row["allocation_round"]) == 0:
            row["allocation_lines"] = []
    store.touch(row)
    return ok(row)
