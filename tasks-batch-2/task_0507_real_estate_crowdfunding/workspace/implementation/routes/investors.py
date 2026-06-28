"""Investor onboarding, suitability review, and tax documents (PRD §3.3, §3.8)."""
from flask import Blueprint

import db
from errors import err
from middleware import require_role, get_identity
from response import success, list_success
from services import domain, serialize
from services.paginate import get_pagination, order_and_page
from services import validate as V

bp = Blueprint("investors", __name__)

READ_ROLES = {"FundManager", "ComplianceOfficer", "Operator", "Investor"}


# ============================ REGISTRATION ============================
@bp.post("/investors")
def register_investor():
    # Anonymous endpoint — no auth required (PRD §2.1, §3.3)
    body = V.get_body()
    email = V.req_str(body, "email")
    full_name = V.req_str(body, "full_name")
    accredited_status = V.opt_enum(body, "accredited_status",
                                   {"NON_ACCREDITED", "ACCREDITED"}, "NON_ACCREDITED")
    annual_income = V.req_int(body, "annual_income_cents", minimum=0)
    net_worth = V.req_int(body, "net_worth_cents", minimum=0)

    for inv in db.investors.values():
        if inv["email"] == email:
            raise err("ERR_DUPLICATE", "email already registered")

    e = db.base_fields()
    e.update({
        "email": email,
        "full_name": full_name,
        "accredited_status": accredited_status,
        "annual_income_cents": annual_income,
        "net_worth_cents": net_worth,
        "suitability_status": "PENDING",
        "reviewed_by_user_id": None,
        "ytd_invested_cents": 0,
    })
    db.investors[e["id"]] = e
    return success(serialize.investor(e), status=201)


@bp.get("/investors/<iid>")
def get_investor(iid):
    require_role(READ_ROLES)
    e = domain.get_investor(iid)
    return success(serialize.investor(e))


@bp.get("/investors")
def list_investors():
    require_role({"FundManager", "ComplianceOfficer", "Operator"})
    limit, offset = get_pagination()
    page, total = order_and_page(list(db.investors.values()), limit, offset)
    return list_success([serialize.investor(e) for e in page], limit, offset, total)


# ============================ SUITABILITY ============================
@bp.post("/investors/<iid>/approve-suitability")
def approve_suitability(iid):
    user_id, _ = require_role({"ComplianceOfficer"})
    inv = domain.get_investor(iid)
    if inv["suitability_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Investor not PENDING")
    inv["suitability_status"] = "APPROVED"
    inv["reviewed_by_user_id"] = user_id
    db.touch(inv)
    return success(serialize.investor(inv))


@bp.post("/investors/<iid>/reject-suitability")
def reject_suitability(iid):
    user_id, _ = require_role({"ComplianceOfficer"})
    inv = domain.get_investor(iid)
    if inv["suitability_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Investor not PENDING")
    inv["suitability_status"] = "REJECTED"
    inv["reviewed_by_user_id"] = user_id
    db.touch(inv)
    return success(serialize.investor(inv))


@bp.post("/investors/<iid>/revoke-suitability")
def revoke_suitability(iid):
    require_role({"ComplianceOfficer"})
    inv = domain.get_investor(iid)
    if inv["suitability_status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Investor not APPROVED")
    inv["suitability_status"] = "PENDING"
    db.touch(inv)
    return success(serialize.investor(inv))


# ============================ TAX DOCUMENTS ============================
@bp.post("/investors/<iid>/tax-documents")
def create_tax_document(iid):
    require_role({"ComplianceOfficer", "Operator"})
    inv = domain.get_investor(iid)
    body = V.get_body()
    fund_id = V.req_str(body, "fund_id")
    tax_year = V.req_int(body, "tax_year")
    if tax_year < 2000:
        raise err("ERR_INVALID_REQUEST", "tax_year must be >= 2000")
    fund = domain.get_fund(fund_id)

    # uniqueness per (investor, fund, year)
    for td in db.tax_documents.values():
        if (td["investor_id"] == iid and td["fund_id"] == fund_id
                and td["tax_year"] == tax_year):
            raise err("ERR_DUPLICATE", "TaxDocument already exists for investor+fund+year")

    doc_type = "FORM_1099_DIV" if fund["vehicle_type"] == "REIT" else "FORM_K1"

    sc_ids = domain.share_class_ids_of_fund(fund_id)
    # holdings belonging to this investor in this fund
    inv_holding_ids = {
        h["id"] for h in db.holdings.values()
        if h["investor_id"] == iid and h["share_class_id"] in sc_ids
    }

    ordinary = 0
    reinvested = 0
    for alloc in db.allocations.values():
        if alloc["holding_id"] not in inv_holding_ids:
            continue
        dist = db.distributions.get(alloc["distribution_id"])
        if dist is None or dist["status"] != "PAID":
            continue
        if _period_year(dist["period_label"]) != tax_year:
            continue
        if alloc["mode"] == "CASH":
            ordinary += alloc["gross_dividend_cents"]
        elif alloc["mode"] == "DRIP":
            reinvested += alloc["gross_dividend_cents"]

    e = db.base_fields(full=False)
    e.update({
        "investor_id": iid,
        "fund_id": fund_id,
        "tax_year": tax_year,
        "doc_type": doc_type,
        "ordinary_dividends_cents": ordinary,
        "reinvested_dividends_cents": reinvested,
    })
    db.tax_documents[e["id"]] = e
    return success(serialize.tax_document(e), status=201)


def _period_year(period_label):
    """Extract the year from a period_label like '2026-Q1'."""
    try:
        return int(str(period_label).split("-")[0])
    except (ValueError, IndexError):
        return None


@bp.get("/investors/<iid>/tax-documents")
def list_investor_tax_documents(iid):
    require_role({"ComplianceOfficer", "Operator", "Investor"})
    domain.get_investor(iid)
    from flask import request
    fund_filter = request.args.get("fund_id")
    limit, offset = get_pagination()
    items = [td for td in db.tax_documents.values() if td["investor_id"] == iid]
    if fund_filter is not None:
        items = [td for td in items if td["fund_id"] == fund_filter]
    page, total = order_and_page(items, limit, offset)
    return list_success([serialize.tax_document(td) for td in page], limit, offset, total)


@bp.get("/funds/<fund_id>/tax-documents")
def list_fund_tax_documents(fund_id):
    require_role({"ComplianceOfficer", "Operator", "FundManager"})
    domain.get_fund(fund_id)
    limit, offset = get_pagination()
    items = [td for td in db.tax_documents.values() if td["fund_id"] == fund_id]
    page, total = order_and_page(items, limit, offset)
    return list_success([serialize.tax_document(td) for td in page], limit, offset, total)
