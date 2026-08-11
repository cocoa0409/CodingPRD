"""Firm endpoints."""
import re

from flask import Blueprint

from db import store
from middleware import auth
from common import body, get_or_404, required, new_entity, touch, serialize, list_page
from response import success_obj, success_list
from errors import err_duplicate, err_invalid_request
from services import open_inquiry_count

bp = Blueprint("firms", __name__)

CRD_RE = re.compile(r"^\d{1,7}$")
READ_ROLES = ("SystemOperator", "ComplianceOfficer", "RegistrationPrincipal", "FinanceClerk", "Regulator")


def firm_out(firm):
    return serialize(firm, {"open_inquiry_count": open_inquiry_count(firm["id"])})


@bp.post("/registration-desk/firms")
def create_firm():
    auth("SystemOperator")
    data = body()
    # Priority 4: uniqueness of crd_number.
    crd = data.get("crd_number")
    if isinstance(crd, str) and any(f["crd_number"] == crd for f in store.firms.values()):
        raise err_duplicate("crd_number must be unique across firms")
    # Priority 9: field shape.
    crd = required(data, "crd_number")
    legal_name = required(data, "legal_name")
    if not isinstance(crd, str) or not CRD_RE.match(crd):
        raise err_invalid_request("crd_number must be 1-7 digits")
    if not isinstance(legal_name, str) or not (1 <= len(legal_name) <= 120):
        raise err_invalid_request("legal_name must be 1-120 characters")
    firm = new_entity()
    firm.update({
        "crd_number": crd,
        "legal_name": legal_name,
        "status": "ACTIVE",
        "deadline_basis": "CALENDAR",
    })
    store.firms[firm["id"]] = firm
    return success_obj(firm_out(firm), 201)


@bp.get("/registration-desk/firms/<id>")
def get_firm(id):
    auth(*READ_ROLES)
    firm = get_or_404(store.firms, id)
    return success_obj(firm_out(firm), 200)


@bp.get("/registration-desk/firms")
def list_firms():
    auth(*READ_ROLES)
    page, limit, offset, total = list_page(store.firms)
    return success_list([firm_out(f) for f in page], limit, offset, total)


@bp.patch("/registration-desk/firms/<id>")
def patch_firm(id):
    auth("SystemOperator")
    firm = get_or_404(store.firms, id)
    data = body()
    if "legal_name" in data and data["legal_name"] is not None:
        v = data["legal_name"]
        if not isinstance(v, str) or not (1 <= len(v) <= 120):
            raise err_invalid_request("legal_name must be 1-120 characters")
        firm["legal_name"] = v
    if "deadline_basis" in data and data["deadline_basis"] is not None:
        v = data["deadline_basis"]
        if v not in ("CALENDAR", "REGULATORY"):
            raise err_invalid_request("deadline_basis must be CALENDAR or REGULATORY")
        firm["deadline_basis"] = v
    if "status" in data and data["status"] is not None:
        v = data["status"]
        if v not in ("ACTIVE", "SUSPENDED"):
            raise err_invalid_request("status must be ACTIVE or SUSPENDED")
        firm["status"] = v
    touch(firm)
    return success_obj(firm_out(firm), 200)
