"""ProductionCompany, Production, and CreditBuyer endpoints."""
from flask import Blueprint, request

from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_OWNER
from helpers import get_one, list_query, public
from middleware import authorized
from response import success_object
from services.core import new_record
from util import parse_dt
from validate import (
    get_body,
    reject_unknown_fields,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    require_body_ref,
)

bp = Blueprint("parties", __name__)

PRODUCTION_TYPES = {"FEATURE", "SERIES", "DOCUMENTARY", "COMMERCIAL"}


# --- ProductionCompany ------------------------------------------------------

@bp.post("/production-companies")
def create_company():
    authorized(["Producer"])
    body = get_body()
    reject_unknown_fields(body, {"legal_name", "fein", "contact_email"})
    rec = new_record("production_companies", {
        "legal_name": req_str(body, "legal_name"),
        "fein": req_str(body, "fein"),
        "contact_email": req_str(body, "contact_email"),
    })
    return success_object(public(rec), status=201)


@bp.get("/production-companies/<companyId>")
def get_company(companyId):
    return get_one("production_companies", companyId)


# --- Production -------------------------------------------------------------

@bp.post("/productions")
def create_production():
    caller = authorized(["Producer"])
    body = get_body()
    reject_unknown_fields(body, {
        "production_company_id", "title", "production_type",
        "scheduled_start_date", "scheduled_wrap_date", "total_budget_cents",
    })
    production_company_id = req_str(body, "production_company_id")
    title = req_str(body, "title")
    production_type = req_enum(body, "production_type", PRODUCTION_TYPES)
    start = req_datetime(body, "scheduled_start_date")
    wrap = req_datetime(body, "scheduled_wrap_date")
    total_budget_cents = req_int(body, "total_budget_cents", positive=True)
    if not parse_dt(start) < parse_dt(wrap):
        raise_error(ERR_INVALID_REQUEST,
                    "scheduled_start_date must be strictly before scheduled_wrap_date")
    # Existence (3) then ownership (4).
    require_body_ref("production_companies", production_company_id, "production_company_id")
    if caller.user_id != production_company_id:
        raise_error(ERR_NOT_OWNER, "production_company_id does not match the caller's identity")
    rec = new_record("productions", {
        "production_company_id": production_company_id,
        "title": title,
        "production_type": production_type,
        "scheduled_start_date": start,
        "scheduled_wrap_date": wrap,
        "total_budget_cents": total_budget_cents,
    })
    return success_object(public(rec), status=201)


@bp.get("/productions")
def list_productions():
    return list_query("productions", {
        "production_company_id": request.args.get("production_company_id"),
    })


@bp.get("/productions/<productionId>")
def get_production(productionId):
    return get_one("productions", productionId)


# --- CreditBuyer ------------------------------------------------------------

@bp.post("/credit-buyers")
def create_buyer():
    authorized(["CreditBuyer"])
    body = get_body()
    reject_unknown_fields(body, {"legal_name", "tax_id", "contact_email"})
    rec = new_record("credit_buyers", {
        "legal_name": req_str(body, "legal_name"),
        "tax_id": req_str(body, "tax_id"),
        "contact_email": req_str(body, "contact_email"),
    })
    return success_object(public(rec), status=201)


@bp.get("/credit-buyers/<buyerId>")
def get_buyer(buyerId):
    return get_one("credit_buyers", buyerId)
