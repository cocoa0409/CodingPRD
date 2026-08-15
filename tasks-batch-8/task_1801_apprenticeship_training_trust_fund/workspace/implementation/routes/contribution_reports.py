"""ContributionReport endpoints: create, get, list, submit, flag, resubmit, remit."""

from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success_object, success_list
from services import ledger

bp = Blueprint("contribution_reports", __name__)

ALL_ROLES = ("TrustAdmin", "EmployerRep", "CommitteeMember", "Instructor")


def report_view(r):
    return {
        "id": r["id"],
        "employer_id": r["employer_id"],
        "period_year": r["period_year"],
        "period_month": r["period_month"],
        "lines": r["lines"],
        "due_date": r["due_date"],
        "provisional_due_cents": r["provisional_due_cents"],
        "contribution_due_cents": r["contribution_due_cents"],
        "flag_reason": r["flag_reason"],
        "status": r["status"],
        "remitted_at": r["remitted_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def get_report_or_404(rid):
    r = db.contribution_reports.get(rid)
    if r is None:
        raise errors.err_report_not_found()
    return r


def _check_ownership(user_id, report):
    if user_id != report["employer_id"]:
        raise errors.err_not_owner()


def _validate_lines_shape(lines):
    if not isinstance(lines, list) or len(lines) == 0:
        raise errors.err_invalid_request("lines must be a non-empty array")


@bp.route("/contribution-reports", methods=["POST"])
def create_report():
    user_id, _ = mw.require_roles("EmployerRep")
    body = mw.get_body()
    mw.require_fields(body, ["employer_id", "period_year", "period_month", "lines"])
    if not mw.is_str(body["employer_id"]):
        raise errors.err_invalid_request("employer_id must be a string")
    employer = db.employers.get(body["employer_id"])
    if employer is None:
        raise errors.err_employer_not_found()
    # Ownership: EmployerRep may only act for their own employer
    if user_id != employer["id"]:
        raise errors.err_not_owner()

    py = body["period_year"]
    pm = body["period_month"]
    if not mw.is_int(py):
        raise errors.err_invalid_request("period_year must be an integer")
    if not mw.is_int(pm) or pm < 1 or pm > 12:
        raise errors.err_invalid_period()
    # Period must already have begun: first day of period must not be after now
    now = db.get_clock()
    from datetime import datetime, timezone
    period_start = datetime(py, pm, 1, 0, 0, 0, tzinfo=timezone.utc)
    if period_start > now:
        raise errors.err_invalid_period()

    lines = body["lines"]
    _validate_lines_shape(lines)

    # Uniqueness: one report per employer per period in ANY status
    for r in db.contribution_reports.values():
        if (r["employer_id"] == employer["id"]
                and r["period_year"] == py and r["period_month"] == pm):
            raise errors.err_duplicate_report_period()

    due_date = ledger.compute_due_date(py, pm)
    provisional = ledger.compute_due_cents(lines, employer["agreement_rate_cents_per_hour"])

    rid = db.new_id()
    now_iso = db.now_iso()
    report = {
        "id": rid,
        "employer_id": employer["id"],
        "period_year": py,
        "period_month": pm,
        "lines": lines,
        "due_date": due_date,
        "provisional_due_cents": provisional,
        "contribution_due_cents": None,
        "flag_reason": None,
        "status": "DRAFT",
        "remitted_at": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.contribution_reports[rid] = report
    return success_object(report_view(report), 201)


@bp.route("/contribution-reports/<rid>", methods=["GET"])
def get_report(rid):
    mw.require_roles(*ALL_ROLES)
    return success_object(report_view(get_report_or_404(rid)), 200)


@bp.route("/contribution-reports", methods=["GET"])
def list_reports():
    mw.require_roles(*ALL_ROLES)
    limit, offset = mw.parse_pagination(request.args)
    emp = request.args.get("employer_id")
    status = request.args.get("status")
    py = request.args.get("period_year")
    pm = request.args.get("period_month")
    items = list(db.contribution_reports.values())
    if emp is not None:
        items = [r for r in items if r["employer_id"] == emp]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if py is not None:
        try:
            pyv = int(py)
        except ValueError:
            raise errors.err_invalid_request("period_year must be an integer")
        items = [r for r in items if r["period_year"] == pyv]
    if pm is not None:
        try:
            pmv = int(pm)
        except ValueError:
            raise errors.err_invalid_request("period_month must be an integer")
        items = [r for r in items if r["period_month"] == pmv]
    items.sort(key=lambda r: (db._parse_iso(r["created_at"]), r["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([report_view(r) for r in page], limit, offset, total)


@bp.route("/contribution-reports/<rid>/submit", methods=["POST"])
def submit_report(rid):
    user_id, _ = mw.require_roles("EmployerRep")
    report = get_report_or_404(rid)
    _check_ownership(user_id, report)
    if report["status"] != "DRAFT":
        raise errors.err_invalid_state("submit requires the report to be DRAFT")
    employer = db.employers[report["employer_id"]]
    ledger.validate_report_lines(employer, report["lines"])

    employer = db.employers[report["employer_id"]]
    report["contribution_due_cents"] = ledger.compute_due_cents(
        report["lines"], employer["agreement_rate_cents_per_hour"])
    report["status"] = "SUBMITTED"
    ledger.touch(report)
    # Credit OJT hours + wage recompute
    ledger.apply_hours_delta([], report["lines"])
    ledger.recompute_employer_outstanding(employer)
    return success_object(report_view(report), 200)


@bp.route("/contribution-reports/<rid>/flag", methods=["POST"])
def flag_report(rid):
    mw.require_roles("TrustAdmin")
    report = get_report_or_404(rid)
    body = mw.get_body()
    if report["status"] != "SUBMITTED":
        raise errors.err_report_not_flaggable()
    report["status"] = "FLAGGED"
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise errors.err_invalid_request("reason must be a string")
    report["flag_reason"] = reason
    ledger.touch(report)
    ledger.recompute_employer_outstanding(db.employers[report["employer_id"]])
    return success_object(report_view(report), 200)


@bp.route("/contribution-reports/<rid>/resubmit", methods=["POST"])
def resubmit_report(rid):
    user_id, _ = mw.require_roles("EmployerRep")
    report = get_report_or_404(rid)
    _check_ownership(user_id, report)
    if report["status"] != "FLAGGED":
        raise errors.err_report_not_resubmittable()
    body = mw.get_body()
    mw.require_fields(body, ["lines"])
    new_lines = body["lines"]
    employer = db.employers[report["employer_id"]]
    ledger.validate_report_lines(employer, new_lines)

    old_lines = report["lines"]
    ledger.apply_hours_delta(old_lines, new_lines)
    report["lines"] = new_lines
    report["contribution_due_cents"] = ledger.compute_due_cents(
        new_lines, employer["agreement_rate_cents_per_hour"])
    report["status"] = "SUBMITTED"
    report["flag_reason"] = None
    ledger.touch(report)
    ledger.recompute_employer_outstanding(employer)
    return success_object(report_view(report), 200)


@bp.route("/contribution-reports/<rid>/remit", methods=["POST"])
def remit_report(rid):
    user_id, _ = mw.require_roles("EmployerRep")
    report = get_report_or_404(rid)
    _check_ownership(user_id, report)
    if report["status"] not in ("SUBMITTED", "DELINQUENT"):
        raise errors.err_report_not_payable()
    body = mw.get_body()
    mw.require_fields(body, ["amount_tendered_cents"])
    tendered = body["amount_tendered_cents"]
    if not mw.is_int(tendered):
        raise errors.err_invalid_request("amount_tendered_cents must be an integer")
    if tendered != report["contribution_due_cents"]:
        raise errors.err_remittance_mismatch()

    employer = db.employers[report["employer_id"]]
    fund = db.trust_funds[employer["trust_fund_id"]]

    report["status"] = "PAID"
    report["remitted_at"] = db.now_iso()
    ledger.touch(report)

    ledger.recompute_employer_outstanding(employer)
    # Cure cascade: employer DELINQUENT -> ACTIVE when no remaining DELINQUENT reports
    ledger.recompute_employer_status(employer)
    # Fund ledger: contributions_received += due; version advances by exactly one
    ledger.recompute_fund(fund, bump_version=True)
    return success_object(report_view(report), 200)
