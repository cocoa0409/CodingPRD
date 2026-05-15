"""Tax report (1099-Q) endpoints."""

from flask import Blueprint, g, request
from core.auth import require_roles
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, lock
from core.validation import require_body, require_field
from core.models import tax_report_create, tax_report_view, touch
from services.calendar import year_from_iso


bp = Blueprint("tax_reports", __name__)


def _withdrawals_for_report(account_id: str, tax_year: int):
    rows = []
    for w in STORE.withdrawals.values():
        if w["account_id"] != account_id:
            continue
        d = w.get("_disbursed_at")
        if not d:
            continue
        if year_from_iso(d) != tax_year:
            continue
        if w["status"] in {"CLASSIFIED", "REPORTED"}:
            rows.append(w)
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return rows


def _aggregate(report):
    rows = _withdrawals_for_report(report["account_id"], report["tax_year"])
    gross = sum(w["requested_amount_cents"] for w in rows)
    earnings = sum(w["earnings_portion_cents"] or 0 for w in rows)
    basis = gross - earnings
    penalty = sum(w["penalty_cents"] or 0 for w in rows)
    report["gross_distribution_cents"] = gross
    report["earnings_cents"] = earnings
    report["basis_cents"] = basis
    report["total_penalty_cents"] = penalty


@bp.post("/tax-reports")
@require_roles("PlanAdministrator")
def create_tax_report():
    body = require_body(request)
    account_id = require_field(body, "account_id", kind="string")
    tax_year = require_field(body, "tax_year", kind="int")
    if tax_year < 2000:
        raise_error("ERR_VALIDATION_FAILED", "tax_year must be >= 2000")
    with lock():
        a = STORE.accounts.get(account_id)
        if not a:
            raise_error("ERR_NOT_FOUND", f"Account {account_id} not found")
        # If a locked report for (account_id, tax_year) exists, creating a new
        # report for the same year would be a regulatory error.
        for tr in STORE.tax_reports.values():
            if tr["account_id"] == account_id and tr["tax_year"] == tax_year and tr["locked"]:
                raise_error("ERR_TAX_REPORT_LOCKED",
                            f"A locked TaxReport already exists for ({account_id}, {tax_year})")
        report = tax_report_create(account_id, tax_year)
        _aggregate(report)  # live_recompute on creation
    return success_object(tax_report_view(report), 201)


@bp.get("/tax-reports/<tid>")
@require_roles("PlanAdministrator", "Donor", "Beneficiary")
def get_tax_report(tid):
    report = STORE.tax_reports.get(tid)
    if not report:
        raise_error("ERR_NOT_FOUND", f"TaxReport {tid} not found")
    if g.user_role == "Donor":
        a = STORE.accounts.get(report["account_id"])
        if not a or a["primary_donor_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN", "Donor may only read tax reports for their accounts")
    elif g.user_role == "Beneficiary":
        a = STORE.accounts.get(report["account_id"])
        if not a or a["beneficiary_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN",
                        "Beneficiary may only read tax reports for accounts they benefit from")
    if not report["locked"]:
        with lock():
            _aggregate(report)
    return success_object(tax_report_view(report))


@bp.post("/tax-reports/<tid>/finalize")
@require_roles("PlanAdministrator")
def finalize_tax_report(tid):
    with lock():
        report = STORE.tax_reports.get(tid)
        if not report:
            raise_error("ERR_NOT_FOUND", f"TaxReport {tid} not found")
        if report["locked"]:
            raise_error("ERR_INVALID_STATE", "TaxReport is already locked")
        _aggregate(report)
        # Cascade: every CLASSIFIED withdrawal in this year on this account -> REPORTED.
        rows = _withdrawals_for_report(report["account_id"], report["tax_year"])
        for w in rows:
            if w["status"] == "CLASSIFIED":
                w["status"] = "REPORTED"
                touch(w)
        report["locked"] = True
    return success_object(tax_report_view(report))
