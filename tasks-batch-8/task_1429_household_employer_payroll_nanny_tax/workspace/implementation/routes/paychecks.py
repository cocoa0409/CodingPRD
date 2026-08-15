"""Paycheck endpoints: read, void, per-worker list (PRD 3.6)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import require_roles, check_employer_ownership, forbid
from response import success_object, success_list
from routes.workers import get_worker_or_404
from services import tax as tax_svc
from services.payroll import (
    FICA_COVERAGE_THRESHOLD_CENTS,
    recompute_payrun_totals,
    worker_cash_wages_ytd,
)
from services.serializers import serialize_paycheck
from util import paginate, parse_pagination, sort_by_created_at

bp = Blueprint("paychecks", __name__)


def get_paycheck_or_404(paycheck_id: str) -> dict:
    pc = db.paychecks.get(paycheck_id)
    if pc is None:
        raise_err(ERR_NOT_FOUND, "Paycheck id does not exist")
    return pc


def _check_paycheck_access(pc: dict, user_id: str, role: str) -> None:
    if role == "Worker":
        if user_id != pc["worker_id"]:
            forbid("Worker may only read their own paychecks")
    elif role == "HouseholdClient":
        worker = db.workers.get(pc["worker_id"])
        if worker is not None:
            check_employer_ownership(user_id, role, worker["employer_id"])


@bp.route("/household-payroll/paychecks/<paycheck_id>", methods=["GET"])
@require_roles("PayrollAdmin", "HouseholdClient", "Worker")
def get_paycheck(paycheck_id: str, _user_id: str, _role: str):
    pc = get_paycheck_or_404(paycheck_id)
    _check_paycheck_access(pc, _user_id, _role)
    return success_object(serialize_paycheck(pc))


@bp.route("/household-payroll/paychecks/<paycheck_id>/void", methods=["POST"])
@require_roles("PayrollAdmin")
def void_paycheck(paycheck_id: str, _user_id: str, _role: str):
    pc = get_paycheck_or_404(paycheck_id)
    run = db.pay_runs.get(pc["pay_run_id"])
    if pc["status"] != "ISSUED" or run is None or run["status"] != "FINALIZED":
        raise_err(
            ERR_INVALID_STATE,
            "Void requires an ISSUED paycheck whose pay run is FINALIZED",
        )

    pc["status"] = "VOIDED"
    if pc["deposit_status"] == "SENT":
        pc["deposit_status"] = "REVERSAL_PENDING"
    db.touch(pc)

    # Compensating invariant: pay-run totals over non-VOIDED paychecks.
    recompute_payrun_totals(run)
    db.touch(run)

    # Reverse this check's accruals.
    tax_svc.accrue_paycheck(run, pc, sign=-1)

    # FICA coverage is re-evaluated; if coverage is lost, the year's accrued
    # FICA lines for this worker's other issued checks are reversed too.
    year = int(run["pay_date"][:4])
    cash_after = worker_cash_wages_ytd(pc["worker_id"], year)
    if cash_after < FICA_COVERAGE_THRESHOLD_CENTS:
        for other in db.paychecks.values():
            if other["worker_id"] != pc["worker_id"] or other["status"] != "ISSUED":
                continue
            other_run = db.pay_runs.get(other["pay_run_id"])
            if other_run is None or int(other_run["pay_date"][:4]) != year:
                continue
            if other.get("_fica_base_cents", 0) or other.get("_ss_base_cents", 0):
                for line in other["withholding_lines"]:
                    if line["tax_type"] in ("SS_EE", "MEDICARE_EE", "ADDL_MEDICARE_EE"):
                        acct = tax_svc.get_or_create_account(run["employer_id"], year, "FICA_EE")
                        acct["accrued_cents"] -= line["amount_cents"]
                        db.touch(acct)
                for line in other["employer_tax_lines"]:
                    if line["tax_type"] in ("SS_ER", "MEDICARE_ER"):
                        acct = tax_svc.get_or_create_account(run["employer_id"], year, "FICA_ER")
                        acct["accrued_cents"] -= line["amount_cents"]
                        db.touch(acct)
                other["_fica_base_cents"] = 0
                other["_ss_base_cents"] = 0

    return success_object(serialize_paycheck(pc))


@bp.route("/household-payroll/workers/<worker_id>/paychecks", methods=["GET"])
@require_roles("PayrollAdmin", "HouseholdClient", "Worker")
def list_worker_paychecks(worker_id: str, _user_id: str, _role: str):
    worker = get_worker_or_404(worker_id)
    if _role == "Worker":
        if _user_id != worker_id:
            forbid("Worker may only list their own paychecks")
    else:
        check_employer_ownership(_user_id, _role, worker["employer_id"])
    limit, offset = parse_pagination()
    items = [p for p in db.paychecks.values() if p["worker_id"] == worker_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_paycheck(p) for p in page], limit, offset, total)
