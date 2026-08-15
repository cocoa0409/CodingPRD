"""TaxYear endpoints (SCAFFOLD §1.5): create, get, lock-provision,
mark-returns-filed, close. Year lifecycle: OPEN -> PROVISION_LOCKED ->
RETURNS_FILED -> CLOSED (terminal)."""
from flask import Blueprint

from db import db, new_record, bump_year
from errors import (
    raise_error,
    ERR_DATE_RANGE_INVALID,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_STATE_TRANSITION,
    ERR_UNRESOLVED_PROVISION_ITEMS,
    ERR_UNFILED_RETURNS,
    ERR_UNRESOLVED_NOTICES,
)
from middleware import authorized, READER_ROLES
from response import success_object
from routes.common import get_or_404
from serializers import serialize
from services.calc import (
    compute_current_tax_stack,
    filings_of_year,
    differences_of_year,
    vas_of_year,
    utps_of_year,
    recompute_etrs,
)
from util import is_date_str, parse_date
from validate import body_json, present_int, req_str, req_int, opt_int, req_date
from db import touch

bp = Blueprint("tax_years", __name__)


@bp.route("/tax/tax-years", methods=["POST"])
def create_tax_year():
    authorized(("TaxManager", "TaxDirector"))
    data = body_json()

    # Priority 8 (temporal sanity) — evaluated when both dates are parseable.
    ps_raw, pe_raw = data.get("period_start_date"), data.get("period_end_date")
    if is_date_str(ps_raw) and is_date_str(pe_raw):
        if parse_date(pe_raw) <= parse_date(ps_raw):
            raise_error(ERR_DATE_RANGE_INVALID,
                        "period_end_date must be after period_start_date")
    # Priority 10 (amount sanity) — pretax book income must be > 0 so later
    # ETR divisions are always safe.
    pretax_probe = present_int(data, "pretax_book_income_cents")
    if pretax_probe is not None and pretax_probe <= 0:
        raise_error(ERR_INVALID_AMOUNT, "pretax_book_income_cents must be > 0")

    # Priority 11 (structural well-formedness) — deliberately last.
    label = req_str(data, "fiscal_year_label")
    period_start = req_date(data, "period_start_date")
    period_end = req_date(data, "period_end_date")
    rate_bp = req_int(data, "enacted_federal_rate_bp")
    pretax = req_int(data, "pretax_book_income_cents")
    prior = opt_int(data, "prior_year_total_tax_cents", 0)

    year = new_record({
        "fiscal_year_label": label,
        "period_start_date": period_start,
        "period_end_date": period_end,
        "enacted_federal_rate_bp": rate_bp,
        "pretax_book_income_cents": pretax,
        "prior_year_total_tax_cents": prior,
        "status": "OPEN",
        "current_provision_cents": 0,
        "deferred_expense_cents": 0,
        "net_deferred_asset_cents": 0,
        "valuation_allowance_cents": 0,
        "utp_liability_cents": 0,
        "return_to_provision_adjustment_cents": 0,
        "forecast_etr_bp": 0,
        "actual_etr_bp": 0,
    })
    db.tax_years[year["id"]] = year
    return success_object(serialize(year), status=201)


@bp.route("/tax/tax-years/<taxYearId>", methods=["GET"])
def get_tax_year(taxYearId):
    authorized(READER_ROLES)
    return success_object(serialize(get_or_404(db.tax_years, taxYearId, "TaxYear")))


@bp.route("/tax/tax-years/<taxYearId>/lock-provision", methods=["POST"])
def lock_provision(taxYearId):
    authorized(("TaxDirector",))
    year = get_or_404(db.tax_years, taxYearId, "TaxYear")
    if year["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"lock-provision is not defined from status {year['status']}")

    # Priority 9 (cross-entity readiness): differences terminal, an APPROVED
    # valuation allowance present, no IDENTIFIED uncertain tax positions.
    if any(d["status"] not in ("LOCKED", "REJECTED") for d in differences_of_year(year["id"])):
        raise_error(ERR_UNRESOLVED_PROVISION_ITEMS,
                    "every BookTaxDifference of the year must be LOCKED or REJECTED")
    if not any(v["status"] == "APPROVED" for v in vas_of_year(year["id"])):
        raise_error(ERR_UNRESOLVED_PROVISION_ITEMS,
                    "an APPROVED ValuationAllowance is required to lock the provision")
    if any(p["status"] == "IDENTIFIED" for p in utps_of_year(year["id"])):
        raise_error(ERR_UNRESOLVED_PROVISION_ITEMS,
                    "an UncertainTaxPosition of the year is still IDENTIFIED")

    # Side effects: stamp per-jurisdiction estimates onto filings, snapshot the
    # current provision (frozen thereafter), recompute forecast ETR, bump version.
    total, components = compute_current_tax_stack(year)
    year["current_provision_cents"] = total
    for f in filings_of_year(year["id"]):
        f["estimated_liability_cents"] = components.get(f["jurisdiction_id"], 0)
        touch(f)
    year["status"] = "PROVISION_LOCKED"
    recompute_etrs(year)
    bump_year(year)
    return success_object(serialize(year))


@bp.route("/tax/tax-years/<taxYearId>/mark-returns-filed", methods=["POST"])
def mark_returns_filed(taxYearId):
    authorized(("TaxDirector",))
    year = get_or_404(db.tax_years, taxYearId, "TaxYear")
    if year["status"] != "PROVISION_LOCKED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"mark-returns-filed is not defined from status {year['status']}")
    if any(f["status"] not in ("FILED", "ACCEPTED") for f in filings_of_year(year["id"])):
        raise_error(ERR_UNFILED_RETURNS,
                    "every Filing of the year must be FILED or ACCEPTED")
    year["status"] = "RETURNS_FILED"
    bump_year(year)
    return success_object(serialize(year))


@bp.route("/tax/tax-years/<taxYearId>/close", methods=["POST"])
def close_tax_year(taxYearId):
    authorized(("TaxDirector",))
    year = get_or_404(db.tax_years, taxYearId, "TaxYear")
    if year["status"] != "RETURNS_FILED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"close is not defined from status {year['status']}")

    # Cross-entity readiness: every audit of the year closed, and every notice
    # tied to the year (via a linked audit, or standalone in a jurisdiction with
    # a filing in this year) RESOLVED.
    if any(a["status"] not in ("CLOSED_AGREED", "CLOSED_NO_CHANGE")
           for a in db.audits.values() if a["tax_year_id"] == year["id"]):
        raise_error(ERR_UNRESOLVED_NOTICES,
                    "every AuditCase of the year must be CLOSED_AGREED or CLOSED_NO_CHANGE")
    year_audit_ids = {a["id"] for a in db.audits.values() if a["tax_year_id"] == year["id"]}
    jurisdictions_with_filings = {f["jurisdiction_id"] for f in filings_of_year(year["id"])}
    for n in db.notices.values():
        if n["status"] == "RESOLVED":
            continue
        tied = (n.get("audit_case_id") in year_audit_ids) or (
            n.get("audit_case_id") is None and n["jurisdiction_id"] in jurisdictions_with_filings)
        if tied:
            raise_error(ERR_UNRESOLVED_NOTICES,
                        "every TaxNotice tied to the year must be RESOLVED")

    year["status"] = "CLOSED"
    bump_year(year)
    return success_object(serialize(year))
