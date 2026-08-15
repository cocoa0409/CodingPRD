"""Outside vendor registry endpoints."""
from flask import Blueprint

from db import store, new_id, new_common
from response import ok, created, paginate
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity
from services.audit import audit

bp = Blueprint("vendors", __name__)

READ_ROLES = ["ShopManager", "Estimator", "ProductionPlanner"]


@bp.post("/fab/outside-vendors")
def create_vendor():
    uid, role, _ = get_context()
    require_roles(["ShopManager"])
    body = parse_body({
        "name": ("string", True, None),
        "process": ("enum", True, ["PLATING", "ANODIZING"]),
        "lead_time_days": ("integer", True, None),
        "base_cost_cents_per_part": ("integer", True, None),
    }, allow_empty=False)
    vendor = {
        "id": new_id(),
        "name": body["name"],
        "process": body["process"],
        "lead_time_days": body["lead_time_days"],
        "base_cost_cents_per_part": body["base_cost_cents_per_part"],
        "status": "ACTIVE",
    }
    new_common(vendor)
    store.outside_vendors[vendor["id"]] = vendor
    audit("OutsideVendor", vendor["id"], "VENDOR_CREATED", role, uid,
          {"after": {"process": vendor["process"], "status": "ACTIVE"}})
    return created(vendor)


@bp.get("/fab/outside-vendors")
def list_vendors():
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    rows = list(store.outside_vendors.values())
    for f in ("process", "status"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/fab/outside-vendors/<vendor_id>")
def get_vendor(vendor_id):
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.outside_vendors, vendor_id))


@bp.get("/fab/outside-vendors/<vendor_id>/routing-steps")
def vendor_queue(vendor_id):
    uid, role, _ = get_context()
    require_roles(["ShopManager", "ProductionPlanner"])
    v = require_path_entity(store.outside_vendors, vendor_id)
    rows = [st for st in store.routing_steps.values() if st.get("vendor_id") == v["id"]]
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)
