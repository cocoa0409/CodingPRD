"""ScreeningVendor endpoints."""
from flask import Blueprint

import db
from db import bump
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_VENDOR_NOT_ACTIVE, ERR_VENDOR_NOT_SUSPENDED,
)
from middleware import (
    auth, require_role, get_body, req_str, req_int, opt_int, ALL_ROLES,
)
from response import success_object

bp = Blueprint("vendors", __name__)


@bp.route("/vendors", methods=["POST"])
def create_vendor():
    auth_uid, role = auth()
    require_role(role, {"HRAdmin"})
    body = get_body()
    name = req_str(body, "name")
    base_tat = req_int(body, "base_tat_business_hours")
    max_conc = req_int(body, "max_concurrent_orders", minimum=1)
    surcharge = opt_int(body, "surcharge_cents")
    if surcharge is None:
        surcharge = 0
    vendor = db.new_entity({
        "name": name,
        "base_tat_business_hours": base_tat,
        "max_concurrent_orders": max_conc,
        "surcharge_cents": surcharge,
        "status": "ACTIVE",
        "active_order_count": 0,
        "consecutive_sla_breaches": 0,
        "accuracy_bps_finalized": 10000,
        "accuracy_bps_including_draft": 10000,
    })
    db.vendors[vendor["id"]] = vendor
    return success_object(vendor, 201)


def _load_vendor(vendor_id):
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Vendor not found")
    return vendor


@bp.route("/vendors/<vendor_id>", methods=["GET"])
def get_vendor(vendor_id):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return success_object(_load_vendor(vendor_id), 200)


@bp.route("/vendors/<vendor_id>/suspend", methods=["POST"])
def suspend_vendor(vendor_id):
    auth_uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    vendor = _load_vendor(vendor_id)
    if vendor["status"] != "ACTIVE":
        raise ApiError(ERR_VENDOR_NOT_ACTIVE, 409,
                       "Suspend requires vendor ACTIVE")
    vendor["status"] = "SUSPENDED"
    bump(vendor)
    return success_object(vendor, 200)


@bp.route("/vendors/<vendor_id>/reinstate", methods=["POST"])
def reinstate_vendor(vendor_id):
    auth_uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    vendor = _load_vendor(vendor_id)
    if vendor["status"] not in ("SUSPENDED", "PROBATION"):
        raise ApiError(ERR_VENDOR_NOT_SUSPENDED, 409,
                       "Reinstate requires vendor SUSPENDED or PROBATION")
    vendor["status"] = "ACTIVE"
    bump(vendor)
    return success_object(vendor, 200)
