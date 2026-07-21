"""Vendor endpoints, including deactivate and the savings report."""

from flask import Blueprint, request

import store
import envelope
import logic
from store import touch
from common import get_or_404, single, list_result, filter_by, as_str, as_bool
from auth import authenticate
from validate import get_body, req_str, req_enum, req_int, opt_bool
from errors import invalid_state

bp = Blueprint("vendors", __name__)

VENDOR_TYPES = {"AIR", "HOTEL", "CAR"}
READERS = {"TravelManager", "Traveler", "Approver", "FinanceOfficer"}


@bp.post("/tmc/vendors")
def create_vendor():
    authenticate({"TravelManager"})
    body = get_body()
    rec = {
        "name": req_str(body, "name"),
        "vendor_type": req_enum(body, "vendor_type", VENDOR_TYPES),
        "is_preferred": opt_bool(body, "is_preferred", default=False),
        "capacity": req_int(body, "capacity", min_value=0),
        "status": "ACTIVE",
    }
    store.stamp_new(rec)
    store.vendors[rec["id"]] = rec
    return single(rec, 201)


@bp.get("/tmc/vendors/<vid>")
def get_vendor(vid):
    authenticate(READERS)
    return single(get_or_404(store.vendors, vid))


@bp.get("/tmc/vendors")
def list_vendors():
    authenticate(READERS)
    recs = filter_by(store.vendors.values(), request.args,
                     {"vendor_type": as_str, "is_preferred": as_bool, "status": as_str})
    return list_result(recs)


@bp.post("/tmc/vendors/<vid>/deactivate")
def deactivate_vendor(vid):
    authenticate({"TravelManager"})
    vendor = get_or_404(store.vendors, vid)
    if vendor["status"] != "ACTIVE":
        raise invalid_state("Vendor is not ACTIVE")
    vendor["status"] = "INACTIVE"
    touch(vendor)
    return single(vendor)


@bp.get("/tmc/vendors/<vid>/savings-report")
def savings_report(vid):
    authenticate({"TravelManager", "FinanceOfficer"})
    vendor = get_or_404(store.vendors, vid)
    return envelope.success(logic.savings_report(vendor), "object", 200)
