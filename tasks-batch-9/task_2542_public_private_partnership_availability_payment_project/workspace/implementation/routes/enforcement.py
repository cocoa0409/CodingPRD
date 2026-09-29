"""Refinancing gain sharing, step-in / termination enforcement and the clock."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
from db import (db, format_date, format_instant, insert, is_date_only, public,
                setf, touch)
from errors import fail
from middleware import (ROLE_AUTHORITY_OFFICER, ROLE_CONCESSIONAIRE, ROLE_LENDER_AGENT,
                        actor, as_instant, body, concession_of, get_action,
                        get_concession, get_refi, owner_guard, req_enum, req_instant,
                        req_int, req_str, require_auth, role, sod_guard)
from response import empty, created, ok

bp = Blueprint("enforcement", __name__)

STEP_IN_GROUNDS = ("PERSISTENT_BREACH", "LENDER_DEFAULT_CURE")
TERMINATION_GROUNDS = ("AUTHORITY_VOLUNTARY", "CONCESSIONAIRE_DEFAULT",
                       "AUTHORITY_DEFAULT", "FORCE_MAJEURE")
ALL_GROUNDS = STEP_IN_GROUNDS + TERMINATION_GROUNDS


def sponsor_of(concession):
    return db.tables["concessionaires"].get(concession["concessionaire_id"])


# ------------------------------------------------------------------ refinancing
@bp.post("/ppp/concessions/<row_id>/refinancing-events")
def propose_refinancing(row_id):
    require_auth(ROLE_CONCESSIONAIRE, ROLE_AUTHORITY_OFFICER)
    concession = get_concession(row_id)
    owner_guard(concession)
    data = body()
    raw_date, _ = req_instant(data, "refinancing_date")
    new_debt = req_int(data, "new_senior_debt_cents", minimum=0)
    outstanding = req_int(data, "outstanding_senior_debt_cents", minimum=0)
    cost = req_int(data, "refinancing_cost_cents", minimum=0)
    if concession["status"] != "OPERATIONS":
        fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")
    calc.enforcement_freeze_guard(concession)

    gross_gain = calc.refinancing_gain(new_debt, outstanding, cost)
    if new_debt <= outstanding or gross_gain <= 0:
        fail("ERR_NO_REFINANCING_GAIN")
    rate = calc.refinancing_tier(concession, gross_gain)
    authority_share = calc.rhu(Decimal(gross_gain) * rate)
    row = insert("refis", {
        "concession_id": concession["id"],
        "refinancing_date": raw_date,
        "new_senior_debt_cents": new_debt,
        "outstanding_senior_debt_cents": outstanding,
        "refinancing_cost_cents": cost,
        "gross_gain_cents": gross_gain,
        "tier_pct_applied": float(rate),
        "authority_share_cents": authority_share,
        "concessionaire_share_cents": gross_gain - authority_share,
        "reserve_sweep_cents": 0,
        "proposed_by_user_id": actor(),
        "status": "PROPOSED",
        "consented_by_user_id": None,
        "consented_at": None,
    })
    return created(public(row))


@bp.post("/ppp/refinancing-events/<row_id>/consent")
def consent_refinancing(row_id):
    require_auth(ROLE_AUTHORITY_OFFICER)
    refi = get_refi(row_id)
    concession = concession_of(refi)
    data = body()
    decision = req_enum(data, "decision", ("CONSENT", "REJECT"))
    expected = req_int(data, "expected_concession_version", minimum=0)
    if expected != concession["version"]:
        fail("ERR_STALE_CONCESSION_VERSION")
    if refi["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if concession["status"] != "OPERATIONS":
        fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")
    sod_guard(refi["proposed_by_user_id"])
    calc.enforcement_freeze_guard(concession)

    setf(refi, "consented_by_user_id", actor())
    setf(refi, "consented_at", db.now_str())
    if decision == "CONSENT":
        setf(refi, "status", "CONSENTED")
        sweep = calc.rhu(Decimal(refi["concessionaire_share_cents"]) * calc.RESERVE_SWEEP_PCT)
        setf(refi, "reserve_sweep_cents", sweep)
        calc.append_ledger(concession, "CONTRIBUTION", sweep,
                           "REFINANCING_GAIN_SWEEP", "SYSTEM")
    else:
        setf(refi, "status", "REJECTED")
    touch(concession)
    return ok(public(refi))


# ------------------------------------------------------------------ enforcement
@bp.post("/ppp/concessions/<row_id>/enforcement-actions")
def notify_action(row_id):
    require_auth(ROLE_AUTHORITY_OFFICER, ROLE_LENDER_AGENT)
    concession = get_concession(row_id)
    data = body()
    action_type = req_enum(data, "action_type", ("STEP_IN", "TERMINATION"))
    trigger_reason = req_enum(data, "trigger_reason", ALL_GROUNDS)
    raw_effective, effective_dt = req_instant(data, "effective_date")

    if action_type == "STEP_IN":
        if trigger_reason not in STEP_IN_GROUNDS:
            fail("ERR_ENFORCEMENT_GROUND_NOT_ADMITTED")
        if (trigger_reason == "PERSISTENT_BREACH"
                and not concession["persistent_breach_flag"]):
            fail("ERR_ENFORCEMENT_GROUND_NOT_ADMITTED")
        if concession["status"] != "OPERATIONS":
            fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")
    else:
        if trigger_reason not in TERMINATION_GROUNDS:
            fail("ERR_ENFORCEMENT_GROUND_NOT_ADMITTED")
        if concession["status"] == "TERMINATED":
            fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")

    row = insert("enforcements", {
        "concession_id": concession["id"],
        "action_type": action_type,
        "trigger_reason": trigger_reason,
        "initiated_by_role": role(),
        "effective_date": raw_effective,
        "cure_deadline": None,
        "status": "NOTIFIED",
        "outstanding_senior_debt_cents": None,
        "market_value_estimate_cents": None,
        "rectification_cost_cents": None,
        "authority_reprocurement_cost_cents": None,
        "termination_date": None,
        "elapsed_operational_months": None,
        "accrued_equity_return_cents": None,
        "unpaid_invoiced_cents": None,
        "deduction_offset_cents": None,
        "compensation_cents": None,
        "calculated_by_user_id": None,
        "cure_note": None,
        "cured_at": None,
        "settled_at": None,
        "settlement_reference": None,
        "escalated_to_action_id": None,
    })

    if action_type == "STEP_IN":
        # PRD 3.11: the cure deadline is the effective_date plus 90 calendar days,
        # so it carries the same calendar-date shape the effective_date was given in.
        deadline = effective_dt + timedelta(days=calc.CURE_PERIOD_DAYS)
        row["cure_deadline"] = (format_date(deadline) if is_date_only(raw_effective)
                                else format_instant(deadline))
        row["status"] = "STEP_IN_ACTIVE"
        setf(concession, "status", "STEP_IN")
        sponsor = sponsor_of(concession)
        if sponsor is not None and sponsor["status"] == "ACTIVE":
            setf(sponsor, "status", "STEPPED_IN")
    return created(public(row))


@bp.post("/ppp/enforcement-actions/<row_id>/cure")
def cure_action(row_id):
    require_auth(ROLE_LENDER_AGENT)
    action = get_action(row_id)
    concession = concession_of(action)
    data = body()
    note = req_str(data, "cure_note", max_len=2000)
    if action["status"] != "STEP_IN_ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION")
    deadline = as_instant(action["cure_deadline"])
    if deadline is not None and db.now() > deadline:
        fail("ERR_CURE_WINDOW_VIOLATION")

    setf(action, "cure_note", note)
    setf(action, "cured_at", db.now_str())
    setf(action, "status", "CURED")
    if concession["status"] == "STEP_IN":
        setf(concession, "status", "OPERATIONS")
    sponsor = sponsor_of(concession)
    if sponsor is not None and sponsor["status"] == "STEPPED_IN":
        setf(sponsor, "status", "ACTIVE")
    return ok(public(action))


@bp.post("/ppp/enforcement-actions/<row_id>/escalate")
def escalate_action(row_id):
    require_auth(ROLE_LENDER_AGENT)
    action = get_action(row_id)
    concession = concession_of(action)
    if action["status"] != "STEP_IN_ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION")
    deadline = as_instant(action["cure_deadline"])
    if deadline is not None and db.now() <= deadline:
        fail("ERR_CURE_WINDOW_VIOLATION")

    setf(action, "status", "LAPSED")
    appended = insert("enforcements", {
        "concession_id": concession["id"],
        "action_type": "TERMINATION",
        "trigger_reason": "CONCESSIONAIRE_DEFAULT",
        "initiated_by_role": "SYSTEM",
        # PRD 3.11: effective_date equal to the current logical clock; the field is
        # a calendar date, so the clock's calendar day is what it carries.
        "effective_date": format_date(db.now()),
        "cure_deadline": None,
        "status": "NOTIFIED",
        "outstanding_senior_debt_cents": None,
        "market_value_estimate_cents": None,
        "rectification_cost_cents": None,
        "authority_reprocurement_cost_cents": None,
        "termination_date": None,
        "elapsed_operational_months": None,
        "accrued_equity_return_cents": None,
        "unpaid_invoiced_cents": None,
        "deduction_offset_cents": None,
        "compensation_cents": None,
        "calculated_by_user_id": None,
        "cure_note": None,
        "cured_at": None,
        "settled_at": None,
        "settlement_reference": None,
        "escalated_to_action_id": None,
    })
    setf(action, "escalated_to_action_id", appended["id"])
    return ok(public(action))


@bp.post("/ppp/enforcement-actions/<row_id>/calculate-compensation")
def calculate_compensation(row_id):
    require_auth(ROLE_AUTHORITY_OFFICER)
    action = get_action(row_id)
    concession = concession_of(action)
    data = body()
    raw_termination, termination_dt = req_instant(data, "termination_date")
    outstanding = req_int(data, "outstanding_senior_debt_cents", minimum=0)
    market_value = req_int(data, "market_value_estimate_cents", minimum=0, required=False)
    rectification = req_int(data, "rectification_cost_cents", minimum=0, required=False)
    reprocurement = req_int(data, "authority_reprocurement_cost_cents", minimum=0,
                            required=False)
    if action["trigger_reason"] == "CONCESSIONAIRE_DEFAULT":
        if market_value is None or rectification is None or reprocurement is None:
            fail("ERR_INVALID_REQUEST",
                 "CONCESSIONAIRE_DEFAULT requires all three market-value inputs.")

    if action["status"] != "NOTIFIED" or action["action_type"] != "TERMINATION":
        fail("ERR_INVALID_STATE_TRANSITION")
    if concession["status"] not in ("OPERATIONS", "STEP_IN"):
        fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")
    commencement = as_instant(concession["actual_service_commencement"])
    if commencement is not None and termination_dt.date() < commencement.date():
        fail("ERR_INVALID_INTERVAL")

    setf(action, "termination_date", raw_termination)
    setf(action, "outstanding_senior_debt_cents", outstanding)
    if market_value is not None:
        setf(action, "market_value_estimate_cents", market_value)
    if rectification is not None:
        setf(action, "rectification_cost_cents", rectification)
    if reprocurement is not None:
        setf(action, "authority_reprocurement_cost_cents", reprocurement)

    figures = calc.termination_compensation(concession, action, termination_dt)
    for field, value in figures.items():
        setf(action, field, value)
    setf(action, "calculated_by_user_id", actor())
    setf(action, "status", "COMPENSATION_CALCULATED")
    return ok(public(action))


@bp.post("/ppp/enforcement-actions/<row_id>/settle")
def settle_action(row_id):
    require_auth(ROLE_AUTHORITY_OFFICER)
    action = get_action(row_id)
    concession = concession_of(action)
    data = body()
    reference = req_str(data, "settlement_reference", max_len=200)
    if action["status"] != "COMPENSATION_CALCULATED" or action["compensation_cents"] is None:
        fail("ERR_INVALID_STATE_TRANSITION")
    sod_guard(action["calculated_by_user_id"])

    setf(action, "settled_at", db.now_str())
    setf(action, "settlement_reference", reference)
    setf(action, "status", "SETTLED")

    if concession["status"] in ("OPERATIONS", "STEP_IN"):
        setf(concession, "status", "TERMINATED")
    for period in calc.concession_periods(concession["id"]):
        if period["payment_status"] == "INVOICED":
            setf(period, "payment_status", "ADJUSTED")
    sponsor = sponsor_of(concession)
    if sponsor is not None:
        setf(sponsor, "status", "WOUND_UP")
    return ok(public(action))


# ------------------------------------------------------------------ logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    data = body()
    raw, parsed = req_instant(data, "current_utc")
    db.set_clock(parsed)
    return empty()
