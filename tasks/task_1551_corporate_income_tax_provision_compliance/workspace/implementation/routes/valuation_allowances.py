"""ValuationAllowance endpoints: create (OCC on TaxYear.version), list, get,
and the review loop: submit / approve (segregation of duties) / return.

Supersede rules (SCAFFOLD state_machines.ValuationAllowance):
  - a bare create supersedes existing DRAFT/SUBMITTED assessments of the year;
  - an approve supersedes any other APPROVED assessment of the year;
  - APPROVED is never superseded by a bare create.
"""
from flask import Blueprint

from db import db, new_record, touch, bump_year
from errors import (
    raise_error,
    ERR_INVALID_STATE_TRANSITION,
    ERR_TAX_YEAR_NOT_OPEN,
    ERR_STALE_VERSION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_INVALID_AMOUNT,
)
from middleware import authorized, READER_ROLES
from response import success_object, success_list
from routes.common import get_or_404, apply_filters, paginate
from serializers import serialize
from services.calc import (
    compute_allowance_amount,
    recompute_valuation_allowance_ref,
    recompute_etrs,
)
from validate import (
    body_json, present_int, req_str, req_int, req_bool, opt_str,
)

bp = Blueprint("valuation_allowances", __name__)


@bp.route("/tax/valuation-allowances", methods=["POST"])
def create_valuation_allowance():
    caller = authorized(("TaxManager",))
    data = body_json()

    # Priority 3 (existence): body FK resolves.
    tax_year_id = data.get("tax_year_id")
    year = None
    if isinstance(tax_year_id, str):
        year = get_or_404(db.tax_years, tax_year_id, "TaxYear")

    # Priority 5 (tax-year posture): creation requires OPEN.
    if year is not None and year["status"] != "OPEN":
        raise_error(ERR_TAX_YEAR_NOT_OPEN,
                    "valuation allowances may be created only while the year is OPEN")

    # Optimistic concurrency (PRD §2.8): expected_tax_year_version must match.
    expected = present_int(data, "expected_tax_year_version")
    if year is not None and expected is not None and expected != year["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_tax_year_version does not match the TaxYear's current version")

    # Priority 10 (amount sanity): income-support inputs are nonnegative.
    for f in ("projected_taxable_income_cents", "reversing_dtl_cents"):
        v = present_int(data, f)
        if v is not None and v < 0:
            raise_error(ERR_INVALID_AMOUNT, f"{f} must be >= 0")

    # Priority 11 (structural) — deliberately last.
    tax_year_id = req_str(data, "tax_year_id")
    mltn = req_bool(data, "more_likely_than_not")
    projected = req_int(data, "projected_taxable_income_cents")
    reversing = req_int(data, "reversing_dtl_cents")
    note = opt_str(data, "assessment_note")
    req_int(data, "expected_tax_year_version")
    if year is None:
        from errors import ERR_NOT_FOUND
        raise_error(ERR_NOT_FOUND, f"TaxYear '{tax_year_id}' does not exist")

    va = new_record({
        "tax_year_id": tax_year_id,
        "more_likely_than_not": mltn,
        "projected_taxable_income_cents": projected,
        "reversing_dtl_cents": reversing,
        "assessment_note": note,
        "allowance_amount_cents": 0,  # computed below against the live DTA pool
        "prepared_by_user_id": caller.user_id,
        "approved_by_user_id": None,
        "status": "DRAFT",
    })
    db.valuation_allowances[va["id"]] = va
    va["allowance_amount_cents"] = compute_allowance_amount(va, year)

    # A bare create supersedes existing DRAFT/SUBMITTED assessments of the year.
    for other in db.valuation_allowances.values():
        if (other["id"] != va["id"] and other["tax_year_id"] == tax_year_id
                and other["status"] in ("DRAFT", "SUBMITTED")):
            other["status"] = "SUPERSEDED"
            touch(other)

    bump_year(year)
    return success_object(serialize(va), status=201)


@bp.route("/tax/valuation-allowances", methods=["GET"])
def list_valuation_allowances():
    authorized(READER_ROLES)
    recs = apply_filters(db.valuation_allowances.values(), {
        "tax_year_id": "tax_year_id",
        "status": "status",
    })
    page, total, limit, offset = paginate(recs)
    return success_list([serialize(r) for r in page], total, limit, offset)


@bp.route("/tax/valuation-allowances/<allowanceId>", methods=["GET"])
def get_valuation_allowance(allowanceId):
    authorized(READER_ROLES)
    return success_object(serialize(
        get_or_404(db.valuation_allowances, allowanceId, "ValuationAllowance")))


def _va_target(allowance_id, allowed_from, require_open=True):
    va = get_or_404(db.valuation_allowances, allowance_id, "ValuationAllowance")
    if va["status"] not in allowed_from:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"action is not defined from allowance status {va['status']}")
    year = db.tax_years.get(va["tax_year_id"])
    if require_open and year is not None and year["status"] != "OPEN":
        raise_error(ERR_TAX_YEAR_NOT_OPEN,
                    "valuation allowance lifecycle actions require the year to be OPEN")
    return va, year


@bp.route("/tax/valuation-allowances/<allowanceId>/submit", methods=["POST"])
def submit_valuation_allowance(allowanceId):
    authorized(("TaxManager",))
    va, _year = _va_target(allowanceId, ("DRAFT",))
    va["status"] = "SUBMITTED"
    touch(va)
    return success_object(serialize(va))


@bp.route("/tax/valuation-allowances/<allowanceId>/approve", methods=["POST"])
def approve_valuation_allowance(allowanceId):
    caller = authorized(("TaxDirector",))
    va, year = _va_target(allowanceId, ("SUBMITTED",))

    # Priority 6 (segregation of duties): approver != preparer.
    if caller.user_id == va["prepared_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the approving user must differ from the preparer")

    # A subsequent approval displaces any other APPROVED assessment of the year.
    for other in db.valuation_allowances.values():
        if (other["id"] != va["id"] and other["tax_year_id"] == va["tax_year_id"]
                and other["status"] == "APPROVED"):
            other["status"] = "SUPERSEDED"
            touch(other)

    va["status"] = "APPROVED"
    va["approved_by_user_id"] = caller.user_id
    touch(va)

    recompute_valuation_allowance_ref(year)
    recompute_etrs(year)
    bump_year(year)
    return success_object(serialize(va))


@bp.route("/tax/valuation-allowances/<allowanceId>/return", methods=["POST"])
def return_valuation_allowance(allowanceId):
    authorized(("TaxDirector",))
    va, _year = _va_target(allowanceId, ("SUBMITTED",))
    va["status"] = "DRAFT"
    touch(va)
    return success_object(serialize(va))
