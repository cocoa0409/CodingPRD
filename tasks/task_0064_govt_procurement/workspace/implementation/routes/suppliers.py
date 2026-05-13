"""Supplier routes."""

from flask import Blueprint

from common import get_json_body, optional_field, require_non_empty_string
from middleware import require_roles
from response import success
from services import supplier as svc


bp = Blueprint("suppliers", __name__, url_prefix="/procurement")


@bp.post("/suppliers")
@require_roles("Supplier", "ProcurementOfficer")
def create_supplier():
    body = get_json_body()
    legal_name = require_non_empty_string(body, "legal_name")
    tax_id = require_non_empty_string(body, "tax_id")
    qualifications = optional_field(body, "qualifications", list, default=[])
    s = svc.create_supplier(legal_name, tax_id, qualifications)
    return success(s, 201)


@bp.post("/suppliers/<sid>/verify")
@require_roles("ProcurementOfficer")
def verify_supplier(sid):
    s = svc.verify_supplier(sid)
    return success(s, 200)


@bp.post("/suppliers/<sid>/blacklist")
@require_roles("Regulator")
def blacklist_supplier(sid):
    body = get_json_body()
    bu = require_non_empty_string(body, "blacklist_until")
    s = svc.blacklist_supplier(sid, bu)
    return success(s, 200)


@bp.get("/suppliers/<sid>")
@require_roles("Supplier", "ProcurementOfficer", "Regulator")
def get_supplier(sid):
    s = svc.get_supplier_or_404(sid)
    return success(s, 200)
