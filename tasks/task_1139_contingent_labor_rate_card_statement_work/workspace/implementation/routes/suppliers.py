from flask import Blueprint, request

from db import stamp_new, store, touch
from envelope import ok, ok_list
from errors import ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_VALIDATION, raise_err
from security import ALL_READ, require_roles
from services import run_tier_evaluation
from validators import apply_filters, get_body, paginate, req_enum, req_str
import serializers

bp = Blueprint("suppliers", __name__)

TIERS = {"PREFERRED", "APPROVED", "PROBATION"}


def _get_supplier(supplier_id):
    sup = store.suppliers.get(supplier_id)
    if sup is None:
        raise_err(ERR_NOT_FOUND, f"Supplier {supplier_id} not found.")
    return sup


@bp.post("/v1/suppliers")
def create_supplier():
    require_roles("ProgramAdmin")
    body = get_body()
    name = req_str(body, "name")
    code = req_str(body, "supplier_code")
    tier = req_enum(body, "tier", TIERS)
    for s in store.suppliers.values():
        if s["supplier_code"] == code:
            raise_err(ERR_VALIDATION, f"supplier_code '{code}' is already in use.")
    rec = {
        "name": name,
        "supplier_code": code,
        "tier": tier,
        "status": "ACTIVE",
        "tier_score": None,
        "offers_made_count": 0,
        "offers_filled_count": 0,
        "open_offers_count": 0,
        "completed_assignments_count": 0,
        "open_violation_count": 0,
        "milestones_delivered_count": 0,
        "milestones_accepted_count": 0,
        "spend_ytd_cents": 0,
    }
    stamp_new(rec)
    store.suppliers[rec["id"]] = rec
    return ok(serializers.supplier(rec), 201)


@bp.get("/v1/suppliers")
def list_suppliers():
    require_roles(*ALL_READ)
    filters = {
        "tier": request.args.get("tier"),
        "status": request.args.get("status"),
    }
    records = apply_filters(list(store.suppliers.values()), filters)
    page, total, limit, offset = paginate(records, serializers.supplier)
    return ok_list(page, total, limit, offset)


@bp.get("/v1/suppliers/<supplier_id>")
def get_supplier(supplier_id):
    require_roles(*ALL_READ)
    return ok(serializers.supplier(_get_supplier(supplier_id)))


@bp.post("/v1/suppliers/<supplier_id>/suspend")
def suspend_supplier(supplier_id):
    require_roles("ProgramAdmin")
    sup = _get_supplier(supplier_id)
    if sup["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE supplier can be suspended.")
    for o in store.offers.values():
        if o["supplier_id"] == sup["id"] and o["status"] == "OFFERED":
            o["status"] = "WITHDRAWN"
            touch(o)
            sup["open_offers_count"] -= 1
    sup["status"] = "SUSPENDED"
    touch(sup)
    return ok(serializers.supplier(sup))


@bp.post("/v1/suppliers/<supplier_id>/reinstate")
def reinstate_supplier(supplier_id):
    require_roles("ProgramAdmin")
    sup = _get_supplier(supplier_id)
    if sup["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "Only a SUSPENDED supplier can be reinstated.")
    sup["status"] = "ACTIVE"
    touch(sup)
    return ok(serializers.supplier(sup))


@bp.post("/v1/suppliers/<supplier_id>/tier-evaluation")
def tier_evaluation(supplier_id):
    require_roles("ProgramAdmin")
    sup = _get_supplier(supplier_id)
    scored = sup["completed_assignments_count"] >= 3
    run_tier_evaluation(sup)
    if scored:
        touch(sup)
    return ok(serializers.supplier(sup))
