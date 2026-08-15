"""TaxReturnFiling (Form 1041) workflow with amendment cycle."""

from datetime import date

from flask import Blueprint, request

import db
from errors import (ApiError, ERR_INVALID_STATE, ERR_TRUST_NOT_ACTIVE,
                    ERR_RESOURCE_NOT_FOUND, ERR_SEGREGATION_OF_DUTIES,
                    ERR_DUPLICATE_TAX_YEAR, ERR_INVALID_ELECTION_AMOUNT,
                    ERR_UNPOSTED_FEE_ASSESSMENTS)
from middleware import authenticate, require_role
from response import ok, ok_list
from serialize import filing_json
from services import workflow, calc
from services.workflow import find_or_404
from validation import get_body, validate, parse_pagination

bp = Blueprint("filings", __name__)

READ_ROLES = {"TrustOfficer", "TrustExecutive", "TaxSpecialist"}


@bp.route("/trusts/tax-return-filings", methods=["POST"])
def create_filing():
    _, role = authenticate()
    data = get_body()
    v = validate(data, [
        ("trust_id", "str", True),
        ("tax_year", "int", True),
    ])
    require_role(role, {"TaxSpecialist"})
    trust = db.trusts.get(v["trust_id"])
    if trust is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404,
                       "Trust not found: %s" % v["trust_id"])
    if trust["status"] not in ("ACTIVE", "SUSPENDED", "TERMINATING", "TERMINATED"):
        raise ApiError(ERR_TRUST_NOT_ACTIVE, 409,
                       "Trust status does not permit opening a tax filing")
    # [8] one filing per (trust, tax_year) ever
    for f in db.filings.values():
        if f["trust_id"] == trust["id"] and f["tax_year"] == v["tax_year"]:
            raise ApiError(ERR_DUPLICATE_TAX_YEAR, 409,
                           "A filing already exists for this tax year")
    f = workflow.new_entity()
    f.update({
        "trust_id": trust["id"],
        "tax_year": v["tax_year"],
        "tentative_dni_cents": 0,
        "dni_cents": 0,
        "elected_65day_amount_cents": 0,
        "distribution_deduction_cents": 0,
        "exemption_cents": calc.EXEMPTION_CENTS,
        "trust_taxable_income_cents": 0,
        "status": "DATA_COLLECTION",
        "prepared_by_user_id": None,
        "reviewed_by_user_id": None,
        "amendment_number": 0,
        "filed_at": None,
        "accepted_at": None,
    })
    db.filings[f["id"]] = f
    return ok(filing_json(f), status=201)


@bp.route("/trusts/tax-return-filings", methods=["GET"])
def list_filings():
    _, role = authenticate()
    limit, offset = parse_pagination()
    require_role(role, READ_ROLES)
    filters = []
    for param in ("trust_id", "status"):
        val = request.args.get(param)
        if val is not None:
            filters.append((param, val))
    ty = request.args.get("tax_year")
    if ty is not None:
        try:
            filters.append(("tax_year", int(ty)))
        except ValueError:
            filters.append(("tax_year", None))
    items, total = workflow.list_page(db.filings, filters, filing_json,
                                      limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/trusts/tax-return-filings/<fid>", methods=["GET"])
def get_filing(fid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    f = find_or_404(db.filings, fid, "TaxReturnFiling")
    return ok(filing_json(f))


@bp.route("/trusts/tax-return-filings/<fid>/compute-tentative", methods=["POST"])
def compute_tentative(fid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TaxSpecialist"})
    f = find_or_404(db.filings, fid, "TaxReturnFiling")
    if f["status"] != "DATA_COLLECTION":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Filing must be in DATA_COLLECTION to compute tentative DNI")
    f["tentative_dni_cents"] = calc.compute_dni(f["trust_id"], f["tax_year"])
    workflow.touch(f)
    return ok(filing_json(f))


@bp.route("/trusts/tax-return-filings/<fid>/prepare", methods=["POST"])
def prepare_filing(fid):
    user_id, role = authenticate()
    data = get_body()
    v = validate(data, [("elected_65day_amount_cents", "nnint", False)])
    require_role(role, {"TaxSpecialist"})
    f = find_or_404(db.filings, fid, "TaxReturnFiling")
    if f["status"] != "DATA_COLLECTION":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Filing must be in DATA_COLLECTION to prepare")
    elected = v.get("elected_65day_amount_cents") or 0
    # [8] 65-day election cap: distributions disbursed in [next-year-01-01, 03-06]
    cap = calc.elected_65day_cap(f["trust_id"], f["tax_year"])
    if elected > cap:
        raise ApiError(ERR_INVALID_ELECTION_AMOUNT, 422,
                       "Elected 65-day amount exceeds eligible distributions")
    # [10] every overlapping FINAL FeeAssessment (not REVERSED) must be POSTED
    year_start, year_end = calc.tax_year_window(f["tax_year"])
    for fa in db.fee_assessments.values():
        if (fa["trust_id"] == f["trust_id"] and fa["variant"] == "FINAL"
                and fa["status"] != "REVERSED"):
            ps = date.fromisoformat(fa["period_start"])
            pe = date.fromisoformat(fa["period_end"])
            if ps <= year_end and year_start <= pe and fa["status"] != "POSTED":
                raise ApiError(ERR_UNPOSTED_FEE_ASSESSMENTS, 409,
                               "FINAL fee assessment overlapping the tax year "
                               "is not POSTED")
    # FINAL variant: pinned sequence at prepare time
    dni = calc.compute_dni(f["trust_id"], f["tax_year"])
    paid = calc.distributions_paid(f["trust_id"], f["tax_year"])
    deduction = min(dni, paid + elected)
    f["elected_65day_amount_cents"] = elected
    f["dni_cents"] = dni
    f["distribution_deduction_cents"] = deduction
    f["trust_taxable_income_cents"] = dni - deduction - calc.EXEMPTION_CENTS
    f["prepared_by_user_id"] = user_id
    f["status"] = "PREPARED"
    workflow.touch(f)
    return ok(filing_json(f))


@bp.route("/trusts/tax-return-filings/<fid>/submit-for-review", methods=["POST"])
def submit_for_review(fid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TaxSpecialist"})
    f = find_or_404(db.filings, fid, "TaxReturnFiling")
    if f["status"] != "PREPARED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Filing must be PREPARED to submit for review")
    f["status"] = "UNDER_REVIEW"
    workflow.touch(f)
    return ok(filing_json(f))


@bp.route("/trusts/tax-return-filings/<fid>/approve-review", methods=["POST"])
def approve_review(fid):
    user_id, role = authenticate()
    get_body()
    require_role(role, {"TaxSpecialist"})
    f = find_or_404(db.filings, fid, "TaxReturnFiling")
    # [4] segregation of duties: reviewer must differ from preparer
    if f["prepared_by_user_id"] is not None and user_id == f["prepared_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "Reviewer must differ from the preparer")
    if f["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Filing must be UNDER_REVIEW to approve")
    f["status"] = "FILED"
    f["reviewed_by_user_id"] = user_id
    f["filed_at"] = workflow.now_stamp()
    workflow.touch(f)
    return ok(filing_json(f))


@bp.route("/trusts/tax-return-filings/<fid>/record-acceptance", methods=["POST"])
def record_acceptance(fid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TaxSpecialist"})
    f = find_or_404(db.filings, fid, "TaxReturnFiling")
    if f["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Filing must be FILED to record acceptance")
    f["status"] = "ACCEPTED"
    f["accepted_at"] = workflow.now_stamp()
    workflow.touch(f)
    return ok(filing_json(f))


@bp.route("/trusts/tax-return-filings/<fid>/require-amendment", methods=["POST"])
def require_amendment(fid):
    _, role = authenticate()
    data = get_body()
    validate(data, [("reason", "str", True)])
    require_role(role, {"TaxSpecialist"})
    f = find_or_404(db.filings, fid, "TaxReturnFiling")
    if f["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Filing must be FILED to require amendment")
    f["status"] = "AMENDMENT_REQUIRED"
    workflow.touch(f)
    return ok(filing_json(f))


@bp.route("/trusts/tax-return-filings/<fid>/begin-amendment", methods=["POST"])
def begin_amendment(fid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TaxSpecialist"})
    f = find_or_404(db.filings, fid, "TaxReturnFiling")
    if f["status"] != "AMENDMENT_REQUIRED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Filing must be AMENDMENT_REQUIRED to begin amendment")
    f["status"] = "DATA_COLLECTION"
    f["amendment_number"] += 1
    f["prepared_by_user_id"] = None
    f["reviewed_by_user_id"] = None
    workflow.touch(f)
    return ok(filing_json(f))
