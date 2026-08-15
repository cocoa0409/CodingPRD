"""YearEndPackage endpoints (PRD 3.12)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_FILINGS_INCOMPLETE,
    ERR_MISSING_SSN,
    ERR_DUPLICATE_YEAR_END_PACKAGE,
)
from middleware import require_roles, check_employer_ownership
from response import success_object, success_list
from routes.employers import get_employer_or_404
from services import tax as tax_svc
from services.posture import issued_paychecks
from services.serializers import serialize_year_end_package
from util import (
    get_json_body,
    paginate,
    parse_pagination,
    require_int,
    sort_by_created_at,
)

bp = Blueprint("year_end", __name__)


def get_package_or_404(package_id: str) -> dict:
    pkg = db.year_end_packages.get(package_id)
    if pkg is None:
        raise_err(ERR_NOT_FOUND, "YearEndPackage id does not exist")
    return pkg


@bp.route("/household-payroll/employers/<employer_id>/year-end-packages", methods=["POST"])
@require_roles("PayrollAdmin")
def create_year_end_package(employer_id: str, _user_id: str, _role: str):
    get_employer_or_404(employer_id)
    body = get_json_body()
    tax_year = require_int(body, "tax_year")

    for pkg in db.year_end_packages.values():
        if pkg["employer_id"] == employer_id and pkg["tax_year"] == tax_year:
            raise_err(
                ERR_DUPLICATE_YEAR_END_PACKAGE,
                "Year-end package for (employer, tax_year) already exists",
            )

    pkg = {
        "employer_id": employer_id,
        "tax_year": tax_year,
        "status": "DRAFT",
        "schedule_h_total_cents": None,
        "w2_lines": [],
        "underpayment_penalty_applies": False,
    }
    db.stamp_new(pkg)
    db.year_end_packages[pkg["id"]] = pkg
    return success_object(serialize_year_end_package(pkg), 201)


@bp.route("/household-payroll/year-end-packages/<package_id>/finalize", methods=["POST"])
@require_roles("ComplianceOfficer")
def finalize_year_end_package(package_id: str, _user_id: str, _role: str):
    pkg = get_package_or_404(package_id)
    if pkg["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT package can be finalized")

    for quarter in (1, 2, 3, 4):
        ok = any(
            f["employer_id"] == pkg["employer_id"]
            and f["tax_year"] == pkg["tax_year"]
            and f["quarter"] == quarter
            and f["status"] == "ACCEPTED"
            for f in db.filings.values()
        )
        if not ok:
            raise_err(ERR_FILINGS_INCOMPLETE, "All four quarterly filings must be ACCEPTED")

    checks = [
        pc for pc in issued_paychecks(pkg["employer_id"])
        if int(db.pay_runs[pc["pay_run_id"]]["pay_date"][:4]) == pkg["tax_year"]
    ]
    for pc in checks:
        worker = db.workers.get(pc["worker_id"])
        if worker is None or not worker.get("ssn"):
            raise_err(ERR_MISSING_SSN, "A worker with ISSUED paychecks in the year has no ssn")

    employer = db.employers.get(pkg["employer_id"])
    figures = tax_svc.year_end_figures(employer, pkg["tax_year"])
    pkg["schedule_h_total_cents"] = figures["schedule_h_total_cents"]
    pkg["w2_lines"] = figures["w2_lines"]
    pkg["underpayment_penalty_applies"] = figures["underpayment_penalty_applies"]
    pkg["status"] = "FINALIZED"
    db.touch(pkg)
    return success_object(serialize_year_end_package(pkg))


@bp.route("/household-payroll/employers/<employer_id>/year-end-packages", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient")
def list_year_end_packages(employer_id: str, _user_id: str, _role: str):
    get_employer_or_404(employer_id)
    check_employer_ownership(_user_id, _role, employer_id)
    limit, offset = parse_pagination()
    items = [p for p in db.year_end_packages.values() if p["employer_id"] == employer_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_year_end_package(p) for p in page], limit, offset, total)
