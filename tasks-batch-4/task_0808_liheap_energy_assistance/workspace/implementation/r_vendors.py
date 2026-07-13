"""Vendor registry and enrollment endpoints (§3.5)."""
from store import db, stamp_new, touch, public
from common import endpoint, object_response, get_body, req_str, req_enum, ApiError
from helpers import get_path, forbid

VENDOR_TYPES = {"ELECTRIC", "GAS", "OIL", "PROPANE", "WATER"}


def register(app):
    @app.route("/liheap/vendors", methods=["POST"])
    @endpoint(["ProgramAdmin"])
    def create_vendor(role, user_id):
        body = get_body()
        vendor = {
            "name": req_str(body, "name"),
            "vendor_type": req_enum(body, "vendor_type", VENDOR_TYPES),
            "remittance_account": req_str(body, "remittance_account"),
            "status": "PENDING",
        }
        stamp_new(vendor)
        db.vendors[vendor["id"]] = vendor
        return object_response(public(vendor), 201)

    @app.route("/liheap/vendors/<id_>", methods=["GET"])
    @endpoint(["VendorAgent", "Caseworker", "ProgramAdmin"])
    def get_vendor(role, user_id, id_):
        if role == "VendorAgent" and id_ != user_id:
            forbid()
        vendor = get_path(db.vendors, id_)
        return object_response(public(vendor), 200)

    @app.route("/liheap/vendors/<id_>/enroll", methods=["POST"])
    @endpoint(["VendorAgent", "ProgramAdmin"])
    def enroll_vendor(role, user_id, id_):
        if role == "VendorAgent" and id_ != user_id:
            forbid()
        vendor = get_path(db.vendors, id_)
        if vendor["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Vendor is not PENDING")
        vendor["status"] = "ENROLLED"
        touch(vendor)
        return object_response(public(vendor), 200)
