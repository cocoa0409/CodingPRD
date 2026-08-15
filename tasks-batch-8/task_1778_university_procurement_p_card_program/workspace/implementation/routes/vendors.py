"""Vendor registry and the suspension cascade (PRD 3.1)."""

import db
import services as svc
from middleware import authenticate, ROLES
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    apply_filters,
    require_fk,
)
from errors import ApiError, ERR_VENDOR_STATE_INVALID

bp = make_blueprint("vendors")

DIVERSITY_CERTS = ["NONE", "WBE", "MBE", "DBE", "VBE", "SBE"]
SUSTAINABILITY_TIERS = ["NONE", "BRONZE", "SILVER", "GOLD"]


@bp.post("/vendors")
def create_vendor():
    authenticate(["Buyer"])
    body = body_json()
    check_shape(body, {
        "legal_name": {"type": "string", "required": True},
        "diversity_certification": {"type": "enum", "values": DIVERSITY_CERTS},
        "sustainability_tier": {"type": "enum", "values": SUSTAINABILITY_TIERS},
        "payment_terms_days": {"type": "integer"},
    })
    vendor = db.new_entity("vendors", {
        "legal_name": body["legal_name"],
        "diversity_certification": body.get("diversity_certification") or "NONE",
        "sustainability_tier": body.get("sustainability_tier") or "NONE",
        "payment_terms_days": body.get("payment_terms_days", 30),
        "status": "ACTIVE",
    })
    return success_obj(db.public(vendor), 201)


@bp.get("/vendors")
def list_vendors():
    authenticate(ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("vendors"), ["status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(v) for v in page], limit, offset, total, has_more)


@bp.get("/vendors/<vid>")
def get_vendor(vid):
    authenticate(ROLES)
    vendor = require_fk("vendors", vid)
    return success_obj(db.public(vendor), 200)


@bp.get("/vendors/<vid>/quotes")
def list_vendor_quotes(vid):
    authenticate(ROLES)
    vendor = require_fk("vendors", vid)
    limit, offset = pagination_params()
    items = [q for q in db.all_of("quotes") if q["vendor_id"] == vendor["id"]]
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(q) for q in page], limit, offset, total, has_more)


@bp.post("/vendors/<vid>/suspend")
def suspend_vendor(vid):
    authenticate(["ProcurementAdmin"])
    body = body_json()
    check_shape(body, {"reason": {"type": "string"}})
    vendor = require_fk("vendors", vid)
    if vendor["status"] != "ACTIVE":
        raise ApiError(ERR_VENDOR_STATE_INVALID, 409, "suspend requires an ACTIVE vendor")
    vendor["status"] = "SUSPENDED"
    db.touch(vendor)
    svc.vendor_suspension_cascade(vendor)
    return success_obj(db.public(vendor), 200)


@bp.post("/vendors/<vid>/reinstate")
def reinstate_vendor(vid):
    """Reinstatement does NOT resurrect DISQUALIFIED quotes or CANCELLED
    solicitations (PRD 3.1)."""
    authenticate(["ProcurementAdmin"])
    vendor = require_fk("vendors", vid)
    if vendor["status"] != "SUSPENDED":
        raise ApiError(ERR_VENDOR_STATE_INVALID, 409, "reinstate requires a SUSPENDED vendor")
    vendor["status"] = "ACTIVE"
    db.touch(vendor)
    return success_obj(db.public(vendor), 200)
