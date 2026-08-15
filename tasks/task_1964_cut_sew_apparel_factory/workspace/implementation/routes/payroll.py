"""PayrollRun endpoints (PRD §3.7)."""

from flask import Blueprint

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_PAYROLL_CLERK, ROLE_PLANT_MANAGER
from response import success_object
from util import get_body, req_int, req_enum, req_date
from errors import (
    invalid_request, stale_version, payroll_not_open, payroll_not_calculated,
    payroll_not_approved, sod_payroll_self_approve,
)
from services.calc import payroll_calculate, operator_efficiency
from services.core import base_record, touch, public, get_payroll_run

bp = Blueprint("payroll", __name__)

DECISIONS = {"APPROVE", "REJECT"}


@bp.route("/payroll-runs", methods=["POST"])
def create_payroll_run():
    require_roles([ROLE_PAYROLL_CLERK])
    body = get_body()
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    if period_end < period_start:
        raise invalid_request("period_end must not be before period_start")

    rec = base_record()
    rec.update({
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "calculated_by_user_id": None,
        "approved_by_user_id": None,
        "entry_count": 0,
        "total_piece_cents": 0,
        "total_topup_cents": 0,
        "total_bonus_cents": 0,
        "total_payable_cents": 0,
    })
    store.payroll_runs[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/payroll-runs/<run_id>", methods=["GET"])
def get_payroll_run_endpoint(run_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_payroll_run(run_id)))


@bp.route("/payroll-runs/<run_id>/calculate", methods=["POST"])
def calculate_payroll_run(run_id):
    _, user_id = require_roles([ROLE_PAYROLL_CLERK])
    run = get_payroll_run(run_id)
    body = get_body()
    expected = req_int(body, "expected_payroll_run_version")
    # OCC on PayrollRun.version — checked before state (PRD §2.7).
    if expected != run["version"]:
        raise stale_version(
            f"expected_payroll_run_version {expected} does not match current "
            f"run version {run['version']}")
    if run["status"] != "OPEN":
        raise payroll_not_open("payroll run must be OPEN to calculate")
    run["calculated_by_user_id"] = user_id
    payroll_calculate(run)
    return success_object(public(run))


@bp.route("/payroll-runs/<run_id>/decide", methods=["POST"])
def decide_payroll_run(run_id):
    _, user_id = require_roles([ROLE_PLANT_MANAGER])
    run = get_payroll_run(run_id)
    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    # From-state rule first, then segregation of duties (PRD §3.7).
    if run["status"] != "CALCULATED":
        raise payroll_not_calculated("payroll run must be CALCULATED to decide")
    if user_id == run["calculated_by_user_id"]:
        raise sod_payroll_self_approve(
            "payroll decider must differ from the clerk who calculated it")
    if decision == "APPROVE":
        run["approved_by_user_id"] = user_id
        run["status"] = "APPROVED"
    else:
        # Rejection unwinds the calculation: swept entries are unstamped and
        # the run returns to OPEN with zeroed totals (cyclic loop).
        for e in store.piece_work_entries.values():
            if e["payroll_run_id"] == run["id"]:
                e["payroll_run_id"] = None
                e["payable_cents"] = None
                touch(e)
        run["calculated_by_user_id"] = None
        run["entry_count"] = 0
        run["total_piece_cents"] = 0
        run["total_topup_cents"] = 0
        run["total_bonus_cents"] = 0
        run["total_payable_cents"] = 0
        run["status"] = "OPEN"
    touch(run)
    return success_object(public(run))


@bp.route("/payroll-runs/<run_id>/pay", methods=["POST"])
def pay_payroll_run(run_id):
    require_roles([ROLE_PAYROLL_CLERK])
    get_body()
    run = get_payroll_run(run_id)
    if run["status"] != "APPROVED":
        raise payroll_not_approved("payroll run must be APPROVED to pay")
    swept = sorted(
        [e for e in store.piece_work_entries.values()
         if e["payroll_run_id"] == run["id"] and e["status"] == "VERIFIED"],
        key=lambda e: (e["created_at"], e["_seq"]),
    )
    for e in swept:
        e["status"] = "PAID"
        touch(e)
        # Per entry: credit the operator and recompute their metrics; both
        # records' versions increment per entry flipped (PRD §3.7).
        op = store.operators.get(e["operator_id"])
        if op is not None:
            op["ytd_earnings_cents"] += e["payable_cents"]
            eff, _, _ = operator_efficiency(op["id"])
            op["efficiency_pct"] = eff
            touch(op)
    run["status"] = "PAID"
    touch(run)
    return success_object(public(run))
