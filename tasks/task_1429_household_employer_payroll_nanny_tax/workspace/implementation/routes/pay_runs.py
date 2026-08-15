"""PayRun endpoints: create, calculate, finalize (PRD 3.6)."""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PAYRUN_OVERLAP,
    ERR_PERIOD_LENGTH_MISMATCH,
    ERR_PAYRUN_STALE,
    ERR_EMPLOYER_RESTRICTED,
    ERR_WORKERS_COMP_REQUIRED,
    ERR_REGISTRATION_INACTIVE,
)
from middleware import require_roles, check_employer_ownership
from response import success_object, success_list
from routes.employers import get_employer_or_404
from services.payroll import (
    agreement_covers_period,
    compute_gross_fields,
    compute_lines_fields,
    employer_quarter_applies_futa,
    recompute_payrun_totals,
)
from services.posture import compute_posture, pack_for_state, policy_covers
from services import tax as tax_svc
from services.serializers import serialize_pay_run, serialize_paycheck, serialize_timesheet
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_date,
    sort_by_created_at,
)

bp = Blueprint("pay_runs", __name__)


def get_pay_run_or_404(run_id: str) -> dict:
    run = db.pay_runs.get(run_id)
    if run is None:
        raise_err(ERR_NOT_FOUND, "PayRun id does not exist")
    return run


def _span_matches_frequency(period_start: str, period_end: str, frequency: str) -> bool:
    start = datetime.strptime(period_start, "%Y-%m-%d").date()
    end = datetime.strptime(period_end, "%Y-%m-%d").date()
    if frequency == "WEEKLY":
        return (end - start).days == 7
    if frequency == "BIWEEKLY":
        return (end - start).days == 14
    if frequency == "SEMIMONTHLY":
        if start.day == 1 and end.day == 16 and start.year == end.year and start.month == end.month:
            return True
        if start.day == 16:
            first_next = (start.replace(day=1) + timedelta(days=32)).replace(day=1)
            return end == first_next
        return False
    if frequency == "MONTHLY":
        if start.day != 1:
            return False
        first_next = (start + timedelta(days=32)).replace(day=1)
        return end == first_next
    return False


def _member_workers(pay_run: dict) -> list[tuple[dict, dict]]:
    """(worker, agreement) pairs eligible for this run: worker ACTIVE on
    period_start with an ACTIVE agreement covering the period; worker
    created_at ASC order (never by id)."""
    members = []
    workers = [w for w in db.workers.values() if w["employer_id"] == pay_run["employer_id"]]
    # Worker created_at ASC; the logical clock makes ties common, so the
    # insertion sequence breaks them deterministically (never the random id).
    workers.sort(key=lambda w: (w["created_at"], w["_seq"]))
    for worker in workers:
        if worker["status"] != "ACTIVE":
            continue
        if worker["hire_date"] > pay_run["period_start"]:
            continue
        agreement = agreement_covers_period(worker["id"], pay_run["period_start"], pay_run["period_end"])
        if agreement is None:
            continue
        members.append((worker, agreement))
    return members


def _lock_covering_timesheets(pay_run: dict, worker_id: str) -> None:
    for ts in db.timesheets.values():
        if ts["worker_id"] != worker_id or ts["status"] != "APPROVED":
            continue
        if ts["period_start"] == pay_run["period_start"] and ts["period_end"] == pay_run["period_end"]:
            ts["status"] = "LOCKED"
            ts["pay_run_id"] = pay_run["id"]
            db.touch(ts)


@bp.route("/household-payroll/employers/<employer_id>/pay-runs", methods=["POST"])
@require_roles("PayrollAdmin")
def create_pay_run(employer_id: str, _user_id: str, _role: str):
    employer = get_employer_or_404(employer_id)
    body = get_json_body()
    period_start = require_date(body, "period_start")
    period_end = require_date(body, "period_end")
    pay_date = require_date(body, "pay_date")
    if period_end <= period_start:
        raise_err(ERR_INVALID_REQUEST, "period_end must be after period_start (half-open interval)")

    if employer["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Pay run creation requires an ACTIVE employer")

    for other in db.pay_runs.values():
        if other["employer_id"] != employer_id or other["status"] == "FINALIZED":
            continue
        if period_start < other["period_end"] and other["period_start"] < period_end:
            raise_err(ERR_PAYRUN_OVERLAP, "Pay-run period overlaps an existing non-terminal pay run")

    if not _span_matches_frequency(period_start, period_end, employer["pay_frequency"]):
        raise_err(ERR_PERIOD_LENGTH_MISMATCH, "Period span does not match the employer's pay_frequency")

    run = {
        "employer_id": employer_id,
        "period_start": period_start,
        "period_end": period_end,
        "pay_date": pay_date,
        "status": "OPEN",
        "recalc_status": "CURRENT",
        "total_gross_cents": 0,
        "total_net_cents": 0,
        "total_employer_tax_cents": 0,
    }
    db.stamp_new(run)
    db.pay_runs[run["id"]] = run
    return success_object(serialize_pay_run(run), 201)


@bp.route("/household-payroll/pay-runs/<run_id>", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient")
def get_pay_run(run_id: str, _user_id: str, _role: str):
    run = get_pay_run_or_404(run_id)
    check_employer_ownership(_user_id, _role, run["employer_id"])
    return success_object(serialize_pay_run(run))


@bp.route("/household-payroll/employers/<employer_id>/pay-runs", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient")
def list_pay_runs(employer_id: str, _user_id: str, _role: str):
    get_employer_or_404(employer_id)
    check_employer_ownership(_user_id, _role, employer_id)
    limit, offset = parse_pagination()
    items = [r for r in db.pay_runs.values() if r["employer_id"] == employer_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["status"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_pay_run(r) for r in page], limit, offset, total)


@bp.route("/household-payroll/pay-runs/<run_id>/calculate", methods=["POST"])
@require_roles("PayrollAdmin")
def calculate_pay_run(run_id: str, _user_id: str, _role: str):
    run = get_pay_run_or_404(run_id)
    if not (run["status"] == "OPEN" or (run["status"] == "CALCULATED" and run["recalc_status"] == "STALE")):
        raise_err(
            ERR_INVALID_STATE,
            "Calculate requires OPEN, or CALCULATED with recalc_status STALE",
        )

    if run["status"] == "OPEN":
        members = _member_workers(run)
        # Phase 1: gross for every member, so the FUTA quarterly trigger sees
        # the whole run's wages projected into pay_date's quarter.
        gross_by_worker = {}
        for worker, agreement in members:
            _lock_covering_timesheets(run, worker["id"])
            gross_by_worker[worker["id"]] = compute_gross_fields(run, worker, agreement)
        run_total_gross = sum(g["gross_cents"] for g in gross_by_worker.values())
        year = int(run["pay_date"][:4])
        futa_applies = employer_quarter_applies_futa(run["employer_id"], year, run_total_gross, run["pay_date"])
        # Phase 2: tax lines in worker created_at ASC order.
        per_worker_earlier: dict[str, list[dict]] = {}
        for worker, agreement in members:
            gross_fields = gross_by_worker[worker["id"]]
            earlier = per_worker_earlier.setdefault(worker["id"], [])
            lines = compute_lines_fields(run, worker, agreement, gross_fields["gross_cents"], earlier, futa_applies)
            pc = {
                "pay_run_id": run["id"],
                "worker_id": worker["id"],
                "basis_stale": False,
                "status": "CALCULATED",
                "deposit_status": "PENDING",
                "stub_status": "PENDING",
                **gross_fields,
                **lines,
            }
            db.stamp_new(pc)
            db.paychecks[pc["id"]] = pc
            earlier.append(pc)
        run["status"] = "CALCULATED"
    else:
        # Re-calculation after STALE: recompute member paychecks from the
        # currently approved timesheets; clear basis_stale.
        members = [pc for pc in db.paychecks.values() if pc["pay_run_id"] == run["id"]]
        members.sort(key=lambda pc: (db.workers[pc["worker_id"]]["created_at"], db.workers[pc["worker_id"]]["_seq"], pc["_seq"]))
        resolved = []
        for pc in members:
            worker = db.workers[pc["worker_id"]]
            agreement = agreement_covers_period(worker["id"], run["period_start"], run["period_end"])
            if agreement is None:
                continue
            _lock_covering_timesheets(run, worker["id"])
            resolved.append((pc, worker, agreement, compute_gross_fields(run, worker, agreement)))
        run_total_gross = sum(g["gross_cents"] for _, _, _, g in resolved)
        year = int(run["pay_date"][:4])
        futa_applies = employer_quarter_applies_futa(run["employer_id"], year, run_total_gross, run["pay_date"])
        per_worker_earlier = {}
        for pc, worker, agreement, gross_fields in resolved:
            earlier = per_worker_earlier.setdefault(worker["id"], [])
            lines = compute_lines_fields(run, worker, agreement, gross_fields["gross_cents"], earlier, futa_applies)
            pc.update(gross_fields)
            pc.update(lines)
            pc["basis_stale"] = False
            db.touch(pc)
            earlier.append(pc)

    run["recalc_status"] = "CURRENT"
    recompute_payrun_totals(run)
    db.touch(run)
    return success_object(serialize_pay_run(run))


@bp.route("/household-payroll/pay-runs/<run_id>/finalize", methods=["POST"])
@require_roles("PayrollAdmin")
def finalize_pay_run(run_id: str, _user_id: str, _role: str):
    run = get_pay_run_or_404(run_id)
    if run["status"] != "CALCULATED":
        raise_err(ERR_INVALID_STATE, "Only a CALCULATED pay run can be finalized")
    if run["recalc_status"] != "CURRENT":
        raise_err(ERR_PAYRUN_STALE, "Pay run is STALE; re-run calculate before finalize")

    employer = db.employers.get(run["employer_id"])
    if employer is None or employer["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Pay run finalize requires an ACTIVE employer")
    if compute_posture(employer) == "RESTRICTED":
        raise_err(ERR_EMPLOYER_RESTRICTED, "Employer compliance posture is RESTRICTED")

    members = [pc for pc in db.paychecks.values() if pc["pay_run_id"] == run["id"]]

    for pc in members:
        worker = db.workers.get(pc["worker_id"])
        if worker is None:
            continue
        pack = pack_for_state(worker["work_state_code"])
        if pack is not None and pack["workers_comp_required"]:
            if not policy_covers(employer["id"], worker["work_state_code"], run["pay_date"]):
                raise_err(
                    ERR_WORKERS_COMP_REQUIRED,
                    "A member worker's state mandates workers' comp coverage for pay_date",
                )

    for pc in members:
        worker = db.workers.get(pc["worker_id"])
        if worker is None:
            continue
        for agency in ("SIT_WITHHOLDING", "SUTA"):
            active = any(
                reg["employer_id"] == employer["id"]
                and reg["state_code"] == worker["work_state_code"]
                and reg["agency"] == agency
                and reg["status"] == "ACTIVE"
                for reg in db.registrations.values()
            )
            if not active:
                raise_err(ERR_REGISTRATION_INACTIVE, f"{agency} registration is not ACTIVE")

    # Side effects: issue paychecks, move the parallel deposit/stub
    # dimensions, and accrue the year's tax liability accounts in fixed order.
    year = int(run["pay_date"][:4])
    tax_svc.ensure_year_accounts(employer["id"], year)
    for pc in members:
        worker = db.workers.get(pc["worker_id"])
        pack = pack_for_state(worker["work_state_code"]) if worker else None
        pc["status"] = "ISSUED"
        pc["deposit_status"] = "SENT"
        if pack is not None and not pack["pay_stub_required"]:
            pc["stub_status"] = "NOT_REQUIRED"
        else:
            pc["stub_status"] = "DELIVERED"
        db.touch(pc)
        tax_svc.accrue_paycheck(run, pc, sign=+1)

    run["status"] = "FINALIZED"
    recompute_payrun_totals(run)
    db.touch(run)
    return success_object(serialize_pay_run(run))


@bp.route("/household-payroll/pay-runs/<run_id>/paychecks", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient")
def list_pay_run_paychecks(run_id: str, _user_id: str, _role: str):
    run = get_pay_run_or_404(run_id)
    check_employer_ownership(_user_id, _role, run["employer_id"])
    limit, offset = parse_pagination()
    items = [p for p in db.paychecks.values() if p["pay_run_id"] == run_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_paycheck(p) for p in page], limit, offset, total)


@bp.route("/household-payroll/pay-runs/<run_id>/timesheets", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient")
def list_pay_run_timesheets(run_id: str, _user_id: str, _role: str):
    run = get_pay_run_or_404(run_id)
    check_employer_ownership(_user_id, _role, run["employer_id"])
    limit, offset = parse_pagination()
    items = [t for t in db.timesheets.values() if t.get("pay_run_id") == run_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_timesheet(t) for t in page], limit, offset, total)
