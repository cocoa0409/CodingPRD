"""Bronchoprovocation runs, dose stepping and the rescue-dose ledger."""
from flask import Blueprint, request

import calc
import services as svc
from auth import (authenticate, LAB_MANAGER, TECHNOLOGIST,
                  INTERPRETING_PHYSICIAN, COMPLIANCE_AUDITOR)
from calc import D, num, rnd
from errors import ApiError
from responses import object_response, paginate
from store import db, iso, parse_date, stamp_new, touch
import validation as v

bp = Blueprint("challenge", __name__)

RUN_READ_ROLES = [LAB_MANAGER, TECHNOLOGIST, INTERPRETING_PHYSICIAN,
                  COMPLIANCE_AUDITOR]
RUN_LIVE = ("ARMED", "IN_PROGRESS")


@bp.route("/test-sessions/<session_id>/challenge-runs", methods=["POST"])
def arm_run(session_id):
    authenticate([TECHNOLOGIST])
    session = svc.get_session(session_id)
    body = v.get_body()
    lot = None
    if body.get("rescue_lot_id") is not None:
        lot = svc.get_lot(body.get("rescue_lot_id"))
    agent = v.v_enum(body, "agent", calc.CHALLENGE_AGENTS)
    if lot is None:
        v.v_str(body, "rescue_lot_id")
    if session["session_status"] != "IN_PROGRESS":
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "Only an IN_PROGRESS study may arm a challenge.")
    pct_predicted = session.get("fev1_pct_predicted")
    if pct_predicted is None or D(pct_predicted) < calc.CHALLENGE_MIN_FEV1_PCT:
        raise ApiError("ERR_CHALLENGE_CONTRAINDICATED",
                       "Baseline FEV1 percent predicted is below 60.0.")
    order = db.orders.get(session["order_id"])
    challenge_type = (order or {}).get("challenge_type") or "NONE"
    if challenge_type == "NONE" or challenge_type != agent:
        raise ApiError("ERR_CHALLENGE_NOT_REQUESTED",
                       "The order did not request a %s challenge." % agent)
    expires_on = parse_date(lot["expires_on"])
    if lot["status"] != "STOCKED" or expires_on is None or \
            expires_on < db.clock.date():
        raise ApiError("ERR_RESCUE_NOT_READY",
                       "The nominated rescue lot is not usable.")
    free = int(lot["doses_remaining"]) - int(lot["doses_reserved"])
    if free < calc.RESCUE_RESERVE_DOSES:
        raise ApiError("ERR_RESCUE_DOSES_INSUFFICIENT",
                       "The rescue lot has fewer than %d free doses."
                       % calc.RESCUE_RESERVE_DOSES)
    record = {
        "session_id": session["id"],
        "rescue_lot_id": lot["id"],
        "agent": agent,
        "baseline_fev1_l": session.get("best_fev1_l"),
        "status": "ARMED",
        "current_step_index": 0,
        "cumulative_dose_units": 0,
        "last_step_dose_units": 0,
        "last_step_drop_pct": 0,
        "max_fev1_drop_pct": num(rnd(0, 2)),
        "pc20_dose_units": None,
        "rescue_doses_administered": 0,
        "stop_reason": None,
        "abort_reason": None,
    }
    stamp_new(record)
    db.runs[record["id"]] = record
    lot["doses_reserved"] = int(lot["doses_reserved"]) + \
        calc.RESCUE_RESERVE_DOSES
    touch(lot)
    return object_response(svc.ser_run(record), 201)


@bp.route("/challenge-runs/<run_id>", methods=["GET"])
def read_run(run_id):
    authenticate(RUN_READ_ROLES)
    return object_response(svc.ser_run(svc.get_run(run_id)))


@bp.route("/challenge-runs", methods=["GET"])
def list_runs():
    authenticate(RUN_READ_ROLES)
    session_id = request.args.get("session_id")
    rescue_lot_id = request.args.get("rescue_lot_id")
    status = request.args.get("status")
    records = []
    for run in db.runs.values():
        if session_id is not None and run["session_id"] != session_id:
            continue
        if rescue_lot_id is not None and run["rescue_lot_id"] != rescue_lot_id:
            continue
        if status is not None and run["status"] != status:
            continue
        records.append(run)
    return paginate(records, svc.ser_run)


@bp.route("/challenge-runs/<run_id>/steps", methods=["POST"])
def record_step(run_id):
    authenticate([TECHNOLOGIST])
    run = svc.get_run(run_id)
    body = v.get_body()
    dose_units = v.v_num(body, "dose_units", minimum=0, exclusive_min=True)
    post_fev1 = v.v_num(body, "post_step_fev1_l", minimum=0,
                        exclusive_min=True)
    if run["status"] not in RUN_LIVE:
        raise ApiError("ERR_RUN_STATE_INVALID",
                       "Only an ARMED or IN_PROGRESS run may record a step.")
    prev_cumulative = D(run["cumulative_dose_units"])
    new_cumulative = prev_cumulative + D(dose_units)
    if new_cumulative > calc.MAX_CUMULATIVE_DOSE_UNITS:
        raise ApiError("ERR_MAX_DOSE_EXCEEDED",
                       "The step would exceed the %s unit ceiling."
                       % calc.MAX_CUMULATIVE_DOSE_UNITS)
    prev_drop = D(run["max_fev1_drop_pct"])
    drop_pct = calc.step_drop_pct(run["baseline_fev1_l"], post_fev1)

    run["last_step_dose_units"] = num(prev_cumulative)
    run["last_step_drop_pct"] = num(prev_drop)
    run["current_step_index"] = int(run["current_step_index"]) + 1
    run["cumulative_dose_units"] = num(rnd(new_cumulative, 3))
    run["max_fev1_drop_pct"] = num(max(prev_drop, drop_pct))

    if drop_pct >= calc.PC20_THRESHOLD_PCT:
        run["status"] = "STOPPED_PC20"
        run["stop_reason"] = "PC20_REACHED"
        run["pc20_dose_units"] = num(calc.pc20_interpolate(
            prev_cumulative, new_cumulative, prev_drop, drop_pct))
        svc.settle_run_ledger(run)
    elif rnd(new_cumulative, 3) == rnd(calc.MAX_CUMULATIVE_DOSE_UNITS, 3):
        run["status"] = "COMPLETED_NEGATIVE"
        run["stop_reason"] = "MAX_CUMULATIVE_DOSE_REACHED"
        svc.settle_run_ledger(run)
    else:
        run["status"] = "IN_PROGRESS"
    touch(run)
    return object_response(svc.ser_run(run), 200)


@bp.route("/challenge-runs/<run_id>/abort", methods=["POST"])
def abort_run(run_id):
    authenticate([TECHNOLOGIST])
    run = svc.get_run(run_id)
    body = v.get_body()
    reason = v.v_str(body, "abort_reason")
    if run["status"] not in RUN_LIVE:
        raise ApiError("ERR_RUN_STATE_INVALID",
                       "Only an ARMED or IN_PROGRESS run may be aborted.")
    dosed = int(run["current_step_index"]) >= 1
    run["status"] = "ABORTED_SAFETY"
    run["stop_reason"] = "TECHNOLOGIST_ABORT"
    run["abort_reason"] = reason
    svc.settle_run_ledger(run)
    touch(run)
    if dosed:
        session = db.sessions.get(run["session_id"])
        if session is not None:
            svc.abort_session(session, "CHALLENGE_SAFETY_ABORT")
    return object_response(svc.ser_run(run), 200)
