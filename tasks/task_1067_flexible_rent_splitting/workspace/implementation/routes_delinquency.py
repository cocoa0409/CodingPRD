from datetime import timedelta
from flask import Blueprint, request
from core import (db, ApiError, auth, caller, body, ok, ok_list, base_full, base_append,
                  touch, as_enum, as_str, parse_dt, iso_ms, clock_iso, get_clock,
                  paginate, sort_seq)
from domain import append_ledger, emit_reminder, recompute_repaid
import serial
import calc

bp = Blueprint("delinquency", __name__)

ACTION_TYPES = {"OUTREACH", "PROMISE_SET", "RETRY_CHARGE", "NOTE"}


def get_case_or_404(cid):
    c = db.delinquency_cases.get(cid)
    if c is None:
        raise ApiError("ERR_DELINQUENCY_CASE_NOT_FOUND", 404, "Delinquency case not found.")
    return c


def _cycle(case):
    return db.billing_cycles.get(case["cycle_id"])


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/api/delinquency-cases/<cid>")
@auth("PlatformAdmin", "CollectionsAgent", "CollectionsManager")
def get_case(cid):
    c = get_case_or_404(cid)
    return ok(serial.case_out(c))


@bp.get("/api/delinquency-cases")
@auth("PlatformAdmin", "CollectionsAgent", "CollectionsManager")
def list_cases():
    cycle_id = request.args.get("cycle_id")
    renter_id = request.args.get("renter_id")
    status = request.args.get("status")
    items = [c for c in db.delinquency_cases.values()
             if (cycle_id is None or c["cycle_id"] == cycle_id)
             and (renter_id is None or c["renter_id"] == renter_id)
             and (status is None or c["status"] == status)]
    items = sort_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serial.case_out(c) for c in page], limit, offset, total)


@bp.get("/api/delinquency-cases/<cid>/recovery-actions")
@auth("CollectionsAgent", "CollectionsManager", "PlatformAdmin")
def list_recovery_actions(cid):
    get_case_or_404(cid)
    items = sort_seq([a for a in db.recovery_actions.values() if a["case_id"] == cid])
    page, limit, offset, total = paginate(items)
    return ok_list([serial.recovery_action_out(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Record a recovery action
# ---------------------------------------------------------------------------
@bp.post("/api/delinquency-cases/<cid>/recovery-actions")
@auth("CollectionsAgent")
def record_action(cid):
    b = body()
    action_type = as_enum(b, "action_type", ACTION_TYPES)
    note = as_str(b, "note", required=False)
    case = get_case_or_404(cid)
    uid, role = caller()

    promise_norm = None

    if action_type == "OUTREACH":
        if case["status"] == "OPEN":
            case["status"] = "IN_OUTREACH"
        elif case["status"] == "BROKEN_PROMISE":
            case["status"] = "IN_OUTREACH"
            case["recovery_round"] += 1
        else:
            raise ApiError("ERR_INVALID_STATE", 409, "OUTREACH not permitted from state.")
    elif action_type == "PROMISE_SET":
        if case["status"] != "IN_OUTREACH":
            raise ApiError("ERR_INVALID_STATE", 409, "PROMISE_SET requires IN_OUTREACH.")
        if "promise_date" not in b or b["promise_date"] is None:
            raise ApiError("ERR_VALIDATION", 400, "promise_date is required.")
        try:
            pd = parse_dt(b["promise_date"])
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "promise_date is not a valid datetime.")
        if pd > get_clock() + timedelta(days=calc.PROMISE_MAX_DAYS):
            raise ApiError("ERR_PROMISE_WINDOW_EXCEEDED", 422, "promise_date beyond window.")
        promise_norm = iso_ms(pd)
        case["promise_date"] = promise_norm
        case["status"] = "PROMISE_TO_PAY"

    # every action stamps the acting agent and creates a record
    case["last_recovery_agent_id"] = uid
    touch(case)

    action = base_append()
    action.update({
        "case_id": cid,
        "action_type": action_type,
        "agent_id": uid,
        "promise_date": promise_norm,
        "note": note,
    })
    db.recovery_actions[action["id"]] = action

    if action_type == "PROMISE_SET":
        emit_reminder(case["renter_id"], case["cycle_id"], "PROMISE_CONFIRMATION")

    return ok(serial.recovery_action_out(action), 201)


# ---------------------------------------------------------------------------
# Assess (promise check)
# ---------------------------------------------------------------------------
@bp.post("/api/delinquency-cases/<cid>/assess")
@auth("CollectionsAgent", "PlatformAdmin")
def assess_case(cid):
    case = get_case_or_404(cid)
    if case["status"] != "PROMISE_TO_PAY":
        raise ApiError("ERR_INVALID_STATE", 409, "Case is not PROMISE_TO_PAY.")
    cyc = _cycle(case)
    recompute_repaid(cyc)
    if not (get_clock() > parse_dt(case["promise_date"]) and cyc["outstanding_cents"] > 0):
        raise ApiError("ERR_INVALID_STATE", 409, "Promise has not been broken.")

    case["status"] = "BROKEN_PROMISE"
    case["accrued_late_fee_cents"] += calc.LATE_FEE_ROUND_CENTS
    append_ledger(cyc["id"], "LATE_FEE", calc.LATE_FEE_ROUND_CENTS, "Broken-promise late fee")
    touch(case)
    return ok(serial.case_out(case))


# ---------------------------------------------------------------------------
# Charge-off
# ---------------------------------------------------------------------------
@bp.post("/api/delinquency-cases/<cid>/charge-off")
@auth("CollectionsManager")
def charge_off(cid):
    case = get_case_or_404(cid)
    uid, role = caller()
    if case["status"] not in ("BROKEN_PROMISE", "IN_OUTREACH"):
        raise ApiError("ERR_INVALID_STATE", 409, "Case cannot be charged off.")
    # SoD (priority 8)
    if uid == case["last_recovery_agent_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 403, "Approver must differ from last agent.")
    # recovery period (priority 14)
    if get_clock() < parse_dt(case["opened_at"]) + timedelta(days=calc.RECOVERY_MIN_DAYS):
        raise ApiError("ERR_RECOVERY_PERIOD_NOT_ELAPSED", 422, "Recovery period not elapsed.")
    # outstanding (priority 20)
    cyc = _cycle(case)
    recompute_repaid(cyc)
    if cyc["outstanding_cents"] <= 0:
        raise ApiError("ERR_NO_OUTSTANDING_BALANCE", 422, "No outstanding balance.")

    case["status"] = "CHARGED_OFF"
    touch(case)
    append_ledger(cyc["id"], "WRITE_OFF", -cyc["outstanding_cents"], "Charge-off write-down")
    cyc["status"] = "WRITTEN_OFF"
    touch(cyc)
    emit_reminder(case["renter_id"], cyc["id"], "CHARGE_OFF_NOTICE")
    return ok(serial.case_out(case))


# ---------------------------------------------------------------------------
# Resolve
# ---------------------------------------------------------------------------
@bp.post("/api/delinquency-cases/<cid>/resolve")
@auth("CollectionsAgent")
def resolve_case(cid):
    case = get_case_or_404(cid)
    if case["status"] not in ("OPEN", "IN_OUTREACH", "PROMISE_TO_PAY", "BROKEN_PROMISE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Case cannot be resolved.")
    cyc = _cycle(case)
    recompute_repaid(cyc)
    if cyc["outstanding_cents"] > 0:
        raise ApiError("ERR_NO_OUTSTANDING_BALANCE", 422, "Outstanding balance remains.")

    case["status"] = "RESOLVED"
    touch(case)
    cyc["status"] = "SETTLED"
    touch(cyc)
    return ok(serial.case_out(case))
