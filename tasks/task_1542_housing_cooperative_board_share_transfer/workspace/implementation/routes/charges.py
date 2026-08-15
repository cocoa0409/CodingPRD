"""Charge schedules, maintenance charges, payments, arrears actions."""
from flask import request

import domain as D
from db import STORE
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_STALE_COOP_VERSION,
    ERR_TEMPORAL_CONFLICT,
    ERR_CROSS_ENTITY_VIOLATION,
    ERR_PAYMENT_EXCEEDS_OUTSTANDING,
    ERR_FISCAL_THRESHOLD_VIOLATION,
)
from middleware import ctx, require_role, ALL_ROLES
from response import ok
from util import get_body, req_str, req_int, req_enum, req_dt
from routes.core import bp as core_bp, list_response

bp = core_bp  # register on the shared core blueprint

READ_ALL = list(ALL_ROLES)
READ_BOARD = ["PlatformAdmin", "BoardOfficer", "BoardMember", "ManagingAgent"]


# ---------------------------------------------------------------------------
# Charge schedules
# ---------------------------------------------------------------------------

@bp.post("/cooperatives/<cid>/charge-schedules")
def create_schedule(cid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer"])
    coop = D.get_coop(cid)
    body = get_body()
    fiscal_year = req_int(body, "fiscal_year")
    budget = req_int(body, "annual_operating_budget_cents")
    method = req_enum(body, "allocation_method", ["PRO_RATA_SHARES", "EQUAL_SPLIT"])
    effective_from = req_dt(body, "effective_from")
    effective_to = req_dt(body, "effective_to")
    expected = req_int(body, "expected_cooperative_version")
    if effective_from >= effective_to:
        raise ApiError(ERR_TEMPORAL_CONFLICT, "effective_from must be before effective_to", 422)
    # OCC guard (§2.8): evaluated after all other checks.
    if expected != coop["version"]:
        raise ApiError(
            ERR_STALE_COOP_VERSION,
            "expected_cooperative_version %s does not match current version %s"
            % (expected, coop["version"]),
            412,
        )
    sched = D.make(
        "charge_schedules", coop,
        cooperative_id=cid,
        fiscal_year=fiscal_year,
        annual_operating_budget_cents=budget,
        allocation_method=method,
        schedule_status="DRAFT",
        effective_from=effective_from,
        effective_to=effective_to,
        approving_resolution_id=None,
    )
    D.bump_coop(coop)
    return ok(D.ser(sched), 201)


@bp.get("/cooperatives/<cid>/charge-schedules")
def list_schedules(cid):
    uid, role = ctx()
    require_role(role, READ_BOARD)
    D.get_coop(cid)
    return list_response("charge_schedules", cid, [
        ("fiscal_year", request.args.get("fiscal_year"), True),
        ("schedule_status", request.args.get("schedule_status"), False),
    ])


@bp.get("/cooperatives/<cid>/charge-schedules/<csid>")
def get_schedule(cid, csid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    D.get_coop(cid)
    s = D.get_scoped("charge_schedules", csid, cid, "ChargeSchedule")
    return ok(D.ser(s))


# ---------------------------------------------------------------------------
# Maintenance charges & payments
# ---------------------------------------------------------------------------

@bp.get("/cooperatives/<cid>/maintenance-charges")
def list_charges(cid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    D.get_coop(cid)
    return list_response("maintenance_charges", cid, [
        ("unit_id", request.args.get("unit_id"), False),
        ("schedule_id", request.args.get("schedule_id"), False),
        ("charge_status", request.args.get("charge_status"), False),
        ("billing_month", request.args.get("billing_month"), False),
    ])


@bp.get("/cooperatives/<cid>/maintenance-charges/<mcid>")
def get_charge(cid, mcid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    D.get_coop(cid)
    ch = D.get_scoped("maintenance_charges", mcid, cid, "MaintenanceCharge")
    return ok(D.ser(ch))


@bp.post("/cooperatives/<cid>/maintenance-charges/<mcid>/payments")
def post_payment(cid, mcid):
    uid, role = ctx()
    require_role(role, ["ManagingAgent"])
    coop = D.get_coop(cid)
    ch = D.get_scoped("maintenance_charges", mcid, cid, "MaintenanceCharge")
    body = get_body()
    sh_id = req_str(body, "shareholder_id")
    amount = req_int(body, "amount_cents")
    if amount <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "amount_cents must be positive", 400)
    sh = STORE["shareholders"].get(sh_id)
    if sh is None or sh["cooperative_id"] != cid:
        raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "Referenced shareholder does not exist", 422)
    st = ch["charge_status"]
    if st in ("PAID", "WAIVED"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Charge is in terminal state %s" % st, 409)
    if st == "PENDING":
        raise ApiError(ERR_INVALID_STATE, "Charge has not been issued yet", 409)
    now = coop["current_utc"]
    # Catch interest up to the payment instant with the pre-payment principal.
    D.accrue_interest(coop, ch, now)
    if amount > ch["outstanding_cents"]:
        raise ApiError(
            ERR_PAYMENT_EXCEEDS_OUTSTANDING,
            "amount_cents %d exceeds outstanding_cents %d" % (amount, ch["outstanding_cents"]),
            422,
        )
    p = D.make(
        "payments", coop,
        cooperative_id=cid,
        shareholder_id=sh_id,
        charge_id=mcid,
        amount_cents=amount,
        posted_at=now,
        payment_status="POSTED",
    )
    ch["paid_cents"] += amount
    D.recompute_outstanding(ch)
    if ch["outstanding_cents"] == 0:
        ch["charge_status"] = "PAID"
    elif ch["charge_status"] == "ISSUED":
        ch["charge_status"] = "PARTIALLY_PAID"
    D.touch(ch, coop)
    D.recompute_all(coop)
    return ok(D.ser(p), 201)


@bp.post("/cooperatives/<cid>/payments/<pid>/void")
def void_payment(cid, pid):
    uid, role = ctx()
    require_role(role, ["ManagingAgent"])
    coop = D.get_coop(cid)
    p = D.get_scoped("payments", pid, cid, "Payment")
    if p["payment_status"] == "VOIDED":
        raise ApiError(ERR_ALREADY_TERMINAL, "Payment is already VOIDED", 409)
    ch = STORE["maintenance_charges"].get(p["charge_id"])
    now = coop["current_utc"]
    p["payment_status"] = "VOIDED"
    D.touch(p, coop)
    if ch is not None:
        ch["paid_cents"] -= p["amount_cents"]
        D.recompute_outstanding(ch)
        if ch["charge_status"] == "PAID" and ch["outstanding_cents"] > 0:
            if now > D.grace_end(coop, ch):
                D.enter_past_due(coop, ch, now)
            else:
                ch["charge_status"] = "PARTIALLY_PAID"
                D.touch(ch, coop)
        else:
            D.touch(ch, coop)
    D.recompute_all(coop)
    return ok(D.ser(p))


@bp.get("/cooperatives/<cid>/payments/<pid>")
def get_payment(cid, pid):
    uid, role = ctx()
    require_role(role, READ_BOARD)
    D.get_coop(cid)
    p = D.get_scoped("payments", pid, cid, "Payment")
    return ok(D.ser(p))


# ---------------------------------------------------------------------------
# Arrears actions
# ---------------------------------------------------------------------------

@bp.post("/cooperatives/<cid>/arrears-actions")
def create_arrears_action(cid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer", "ManagingAgent"])
    coop = D.get_coop(cid)
    body = get_body()
    sh_id = req_str(body, "shareholder_id")
    action_type = req_enum(body, "action_type", ["LATE_NOTICE", "DEMAND_LETTER", "TERMINATION_NOTICE"])
    sh = STORE["shareholders"].get(sh_id)
    if sh is None or sh["cooperative_id"] != cid:
        raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "Referenced shareholder does not exist", 422)
    if (
        action_type == "TERMINATION_NOTICE"
        and sh["arrears_balance_cents"] < coop["arrears_termination_threshold_cents"]
    ):
        raise ApiError(
            ERR_FISCAL_THRESHOLD_VIOLATION,
            "arrears_balance_cents %d below termination threshold %d"
            % (sh["arrears_balance_cents"], coop["arrears_termination_threshold_cents"]),
            422,
        )
    a = D.spawn_action(coop, sh, action_type, coop["current_utc"])
    return ok(D.ser(a), 201)


@bp.get("/cooperatives/<cid>/arrears-actions")
def list_arrears_actions(cid):
    uid, role = ctx()
    require_role(role, READ_BOARD)
    D.get_coop(cid)
    return list_response("arrears_actions", cid, [
        ("shareholder_id", request.args.get("shareholder_id"), False),
        ("action_type", request.args.get("action_type"), False),
        ("action_status", request.args.get("action_status"), False),
    ])


@bp.get("/cooperatives/<cid>/arrears-actions/<aid>")
def get_arrears_action(cid, aid):
    uid, role = ctx()
    require_role(role, READ_BOARD)
    D.get_coop(cid)
    a = D.get_scoped("arrears_actions", aid, cid, "ArrearsAction")
    return ok(D.ser(a))


@bp.post("/cooperatives/<cid>/arrears-actions/<aid>/escalate")
def escalate_arrears_action(cid, aid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer"])
    coop = D.get_coop(cid)
    a = D.get_scoped("arrears_actions", aid, cid, "ArrearsAction")
    if a["action_status"] in ("CURED", "ESCALATED", "WITHDRAWN"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Arrears action is in terminal state", 409)
    if a["action_status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, "Arrears action is not ISSUED", 409)
    D.escalate_action(coop, a, coop["current_utc"], manual=True)
    return ok(D.ser(a))


@bp.post("/cooperatives/<cid>/arrears-actions/<aid>/withdraw")
def withdraw_arrears_action(cid, aid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer"])
    coop = D.get_coop(cid)
    a = D.get_scoped("arrears_actions", aid, cid, "ArrearsAction")
    if a["action_status"] in ("CURED", "ESCALATED", "WITHDRAWN"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Arrears action is in terminal state", 409)
    if a["action_status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, "Arrears action is not ISSUED", 409)
    a["action_status"] = "WITHDRAWN"
    D.touch(a, coop)
    return ok(D.ser(a))
