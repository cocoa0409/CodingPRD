"""Company endpoints (PRD §3.1)."""
from flask import Blueprint

from db import STORE
from errors import raise_error, ERR_DUPLICATE
from middleware import get_auth, require_roles, ALL_ROLES
from response import success_object, success_list
from services.core import (get_body, req_str, base_fields, serialize, lookup,
                           paginated, query_str)

bp = Blueprint("companies", __name__)


@bp.post("/safety/companies")
def create_company():
    auth = get_auth()
    require_roles(auth, ("PlatformAdmin",))
    data = get_body()
    legal_name = req_str(data, "legal_name", non_empty=True)
    fein = req_str(data, "fein", non_empty=True)
    if any(c["fein"] == fein for c in STORE.companies.values()):
        raise_error(ERR_DUPLICATE,
                    "A company with this fein already exists")
    company = base_fields()
    company.update({"legal_name": legal_name, "fein": fein})
    STORE.companies[company["id"]] = company
    return success_object(serialize(company), status=201)


@bp.get("/safety/companies/<companyId>")
def get_company(companyId):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    company = lookup(STORE.companies, companyId)
    return success_object(serialize(company))


@bp.get("/safety/companies/<companyId>/employees")
def list_company_employees(companyId):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    lookup(STORE.companies, companyId)
    status = query_str("employment_status")
    items = [e for e in STORE.employees.values()
             if e["company_id"] == companyId
             and (status is None or e["employment_status"] == status)]
    page, limit, offset, total = paginated(items)
    return success_list([serialize(e) for e in page], limit, offset, total)


@bp.get("/safety/companies/<companyId>/establishments")
def list_company_establishments(companyId):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    lookup(STORE.companies, companyId)
    items = [e for e in STORE.establishments.values()
             if e["company_id"] == companyId]
    page, limit, offset, total = paginated(items)
    return success_list([serialize(e) for e in page], limit, offset, total)
