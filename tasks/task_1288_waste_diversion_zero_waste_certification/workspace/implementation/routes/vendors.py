"""Vendor endpoints, including set_status with its suspension cascade."""

from flask import Blueprint

from db import base_record, store, touch
from errors import ApiError, ERR_INVALID_STATE, not_found
from middleware import (
    ALL_ROLES,
    authenticate,
    check_unknown,
    f_enum,
    f_str,
    get_body,
)
from response import success_object
from services.lifecycle import pub_vendor, reject_ticket
from util import VENDOR_TYPES

bp = Blueprint("vendors", __name__)


@bp.route("/vendors", methods=["POST"])
def create_vendor():
    authenticate(["CertificationOfficer"])
    b = get_body()
    check_unknown(b, ["name", "vendor_type"])
    name = f_str(b, "name")
    vtype = f_enum(b, "vendor_type", VENDOR_TYPES)

    rec = base_record({"name": name, "vendor_type": vtype, "status": "ACTIVE"})
    store.vendors[rec["id"]] = rec
    return success_object(pub_vendor(rec), 201)


@bp.route("/vendors/<vendor_id>", methods=["GET"])
def get_vendor(vendor_id):
    authenticate(ALL_ROLES)
    rec = store.vendors.get(vendor_id)
    if rec is None:
        raise not_found("Vendor not found")
    return success_object(pub_vendor(rec))


@bp.route("/vendors/<vendor_id>/set_status", methods=["POST"])
def set_vendor_status(vendor_id):
    authenticate(["CertificationOfficer"])
    b = get_body()
    check_unknown(b, ["to_status"])
    to_status = f_enum(b, "to_status", ["ACTIVE", "SUSPENDED"])

    v = store.vendors.get(vendor_id)
    if v is None:
        raise not_found("Vendor not found")

    # Target-state legality: ACTIVE -> SUSPENDED and SUSPENDED -> ACTIVE only.
    if v["status"] == to_status:
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Vendor is already {to_status}")

    v["status"] = to_status
    touch(v)

    if to_status == "SUSPENDED":
        # Cascade: ACTIVE contracts -> SUSPENDED; their PENDING tickets reject.
        for c in store.contracts.values():
            if c["vendor_id"] == v["id"] and c["status"] == "ACTIVE":
                c["status"] = "SUSPENDED"
                touch(c)
                for t in store.tickets.values():
                    if t["contract_id"] == c["id"] and t["validation_status"] == "PENDING":
                        reject_ticket(t, "CONTRACT_SUSPENDED")
    else:
        # Reactivation: SUSPENDED contracts -> ACTIVE; rejected tickets stay.
        for c in store.contracts.values():
            if c["vendor_id"] == v["id"] and c["status"] == "SUSPENDED":
                c["status"] = "ACTIVE"
                touch(c)

    return success_object(pub_vendor(v))
