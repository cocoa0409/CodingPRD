"""QuarterlyFiling endpoints with segregation of duties (PRD 3.10)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_QUARTER_NOT_CLOSED,
    ERR_DUPLICATE_FILING,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_roles, check_employer_ownership
from response import success_object, success_list
from routes.employers import get_employer_or_404
from services import tax as tax_svc
from services.serializers import serialize_filing
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_int,
    sort_by_created_at,
)

bp = Blueprint("filings", __name__)


def get_filing_or_404(filing_id: str) -> dict:
    filing = db.filings.get(filing_id)
    if filing is None:
        raise_err(ERR_NOT_FOUND, "QuarterlyFiling id does not exist")
    return filing


@bp.route("/household-payroll/employers/<employer_id>/quarterly-filings", methods=["POST"])
@require_roles("PayrollAdmin")
def create_filing(employer_id: str, _user_id: str, _role: str):
    get_employer_or_404(employer_id)
    body = get_json_body()
    tax_year = require_int(body, "tax_year")
    quarter = require_int(body, "quarter")
    from errors import ERR_INVALID_REQUEST

    if quarter not in (1, 2, 3, 4):
        raise_err(ERR_INVALID_REQUEST, "quarter must be 1, 2, 3, or 4")

    for filing in db.filings.values():
        if (filing["employer_id"] == employer_id
                and filing["tax_year"] == tax_year
                and filing["quarter"] == quarter):
            raise_err(ERR_DUPLICATE_FILING, "Filing for (employer, tax_year, quarter) already exists")

    filing = {
        "employer_id": employer_id,
        "tax_year": tax_year,
        "quarter": quarter,
        "status": "OPEN",
        "total_cash_wages_cents": 0,
        "futa_applies": False,
        "futa_due_cents": 0,
        "suta_due_cents": 0,
        "estimated_federal_payment_cents": 0,
        "prepared_by_user_id": None,
        "prepared_at": None,
    }
    db.stamp_new(filing)
    db.filings[filing["id"]] = filing
    return success_object(serialize_filing(filing), 201)


@bp.route("/household-payroll/quarterly-filings/<filing_id>/prepare", methods=["POST"])
@require_roles("PayrollAdmin")
def prepare_filing(filing_id: str, _user_id: str, _role: str):
    filing = get_filing_or_404(filing_id)
    if filing["status"] not in ("OPEN", "REJECTED"):
        raise_err(ERR_INVALID_STATE, "Prepare requires an OPEN or REJECTED filing")
    _, q_end = tax_svc._quarter_bounds(filing["tax_year"], filing["quarter"])
    if db.clock_today() <= q_end:
        raise_err(ERR_QUARTER_NOT_CLOSED, "The filing quarter has not closed on the logical clock")

    employer = db.employers.get(filing["employer_id"])
    figures = tax_svc.prepare_figures(employer, filing["tax_year"], filing["quarter"])
    filing.update(figures)
    filing["prepared_by_user_id"] = _user_id
    filing["prepared_at"] = db.now_iso()
    filing["status"] = "PREPARED"
    db.touch(filing)
    return success_object(serialize_filing(filing))


@bp.route("/household-payroll/quarterly-filings/<filing_id>/submit", methods=["POST"])
@require_roles("ComplianceOfficer")
def submit_filing(filing_id: str, _user_id: str, _role: str):
    filing = get_filing_or_404(filing_id)
    if filing["status"] != "PREPARED":
        raise_err(ERR_INVALID_STATE, "Only a PREPARED filing can be submitted")
    if _user_id == filing["prepared_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "The preparer may not submit the filing")
    filing["status"] = "SUBMITTED"
    db.touch(filing)
    return success_object(serialize_filing(filing))


@bp.route("/household-payroll/quarterly-filings/<filing_id>/accept", methods=["POST"])
@require_roles("ComplianceOfficer")
def accept_filing(filing_id: str, _user_id: str, _role: str):
    filing = get_filing_or_404(filing_id)
    if filing["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED filing can be accepted")
    filing["status"] = "ACCEPTED"
    db.touch(filing)
    return success_object(serialize_filing(filing))


@bp.route("/household-payroll/quarterly-filings/<filing_id>/reject", methods=["POST"])
@require_roles("ComplianceOfficer")
def reject_filing(filing_id: str, _user_id: str, _role: str):
    filing = get_filing_or_404(filing_id)
    if filing["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED filing can be rejected")
    filing["status"] = "REJECTED"
    db.touch(filing)
    return success_object(serialize_filing(filing))


@bp.route("/household-payroll/employers/<employer_id>/quarterly-filings", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient")
def list_filings(employer_id: str, _user_id: str, _role: str):
    get_employer_or_404(employer_id)
    check_employer_ownership(_user_id, _role, employer_id)
    limit, offset = parse_pagination()
    items = [f for f in db.filings.values() if f["employer_id"] == employer_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["tax_year", "status"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_filing(f) for f in page], limit, offset, total)
