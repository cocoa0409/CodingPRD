"""Supplier onboarding and lifecycle (PRD §3.3)."""

from flask import Blueprint, request

from db import store, new_entity, touch, public
from errors import err_not_found, err_state, ApiError, ERR_SUPPLIER_HAS_ACTIVE_PROGRAMS
from middleware import require_roles, body_json, req_str, opt_str
from response import success_object, success_list, parse_pagination, paginate

bp = Blueprint("suppliers", __name__)

READ_ROLES = ("CoopAdmin", "SupplierRep", "FinanceOfficer", "ProgramAuditor")
LIVE_PROGRAM_STATES = ("OPEN", "CLOSED_TO_NEW", "REOPENED")


def get_supplier_or_404(supplier_id):
    supplier = store.suppliers.get(supplier_id)
    if supplier is None:
        raise err_not_found("Supplier not found")
    return supplier


def _arg(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.route("/coop/suppliers", methods=["POST"])
@require_roles("CoopAdmin")
def create_supplier(uid, role):
    body = body_json(required=True)
    legal_name = req_str(body, "legal_name")
    notes = opt_str(body, "onboarding_notes", default="")
    supplier = new_entity()
    supplier.update({
        "legal_name": legal_name,
        "onboarding_notes": notes,
        "status": "PROSPECT",
    })
    store.suppliers[supplier["id"]] = supplier
    return success_object(public(supplier), code=201)


@bp.route("/coop/suppliers/<supplier_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_supplier(uid, role, supplier_id):
    return success_object(public(get_supplier_or_404(supplier_id)), code=200)


@bp.route("/coop/suppliers", methods=["GET"])
@require_roles(*READ_ROLES)
def list_suppliers(uid, role):
    limit, offset = parse_pagination()
    items = list(store.suppliers.values())
    status = _arg("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public(s) for s in page], limit, offset, total)


@bp.route("/coop/suppliers/<supplier_id>/onboard", methods=["POST"])
@require_roles("CoopAdmin")
def onboard_supplier(uid, role, supplier_id):
    supplier = get_supplier_or_404(supplier_id)
    if supplier["status"] != "PROSPECT":
        raise err_state("Only a PROSPECT supplier can be onboarded")
    supplier["status"] = "ONBOARDED"
    touch(supplier)
    return success_object(public(supplier), code=200)


@bp.route("/coop/suppliers/<supplier_id>/deactivate", methods=["POST"])
@require_roles("CoopAdmin")
def deactivate_supplier(uid, role, supplier_id):
    supplier = get_supplier_or_404(supplier_id)
    if supplier["status"] != "ONBOARDED":
        raise err_state("Only an ONBOARDED supplier can be deactivated")
    programs = [p for p in store.programs.values() if p["supplier_id"] == supplier["id"]]
    if any(p["status"] in LIVE_PROGRAM_STATES for p in programs):
        raise ApiError(ERR_SUPPLIER_HAS_ACTIVE_PROGRAMS, 409,
                       "Supplier has programs in OPEN/CLOSED_TO_NEW/REOPENED")
    for p in programs:
        if p["status"] == "DRAFT":
            p["status"] = "TERMINATED"
            touch(p)
    supplier["status"] = "INACTIVE"
    touch(supplier)
    return success_object(public(supplier), code=200)
