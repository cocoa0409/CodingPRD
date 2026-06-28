import re

from flask import Blueprint

from clock import clock
from db import db, stamp_create, touch
from errors import err
from middleware import auth
from response import object_response, list_response
from services.query import get_or_404, paginate
from validate import (
    get_body, req_str, req_int, opt_datetime, req_datetime,
    req_str_list_subset, pagination_params,
)

bp = Blueprint("vendors", __name__)

UEI_RE = re.compile(r"^[A-Za-z0-9]{12}$")
SET_ASIDE_CERTS = {"EIGHT_A", "SDVOSB", "WOSB", "HUBZONE"}
SAM_STATUSES = {"DRAFT", "ACTIVE", "EXPIRED", "EXCLUDED"}


@bp.route("/vendors", methods=["POST"])
def create_vendor():
    auth(["Vendor"])
    body = get_body()
    legal_name = req_str(body, "legal_name")
    uei = req_str(body, "uei")
    if not UEI_RE.match(uei):
        raise err("ERR_INVALID_REQUEST", "uei must be exactly 12 alphanumeric characters.")
    employee_count = req_int(body, "employee_count", minimum=0)
    certs = req_str_list_subset(body, "set_aside_certifications", SET_ASIDE_CERTS, default=[])
    expires_at = req_datetime(body, "registration_expires_at")

    entity = {
        "legal_name": legal_name,
        "uei": uei,
        "employee_count": employee_count,
        "set_aside_certifications": certs,
        "sam_status": "DRAFT",
        "registration_expires_at": _iso(body["registration_expires_at"]),
        "performance_index": None,
        "_expires_dt": expires_at,
    }
    stamp_create(entity)
    db.vendors[entity["id"]] = entity
    return object_response(entity, status=201)


def _iso(raw):
    # Preserve the client-supplied datetime string verbatim in the stored entity.
    return raw


@bp.route("/vendors/<vendor_id>", methods=["GET"])
def get_vendor(vendor_id):
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    return object_response(get_or_404(db.vendors, vendor_id))


@bp.route("/vendors", methods=["GET"])
def list_vendors():
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    from flask import request
    uei = request.args.get("uei")
    sam_status = request.args.get("sam_status")
    limit, offset = pagination_params()
    items = list(db.vendors.values())
    if uei is not None:
        items = [v for v in items if v["uei"].lower() == uei.lower()]
    if sam_status is not None:
        items = [v for v in items if v["sam_status"] == sam_status]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


def _duplicate_uei_exists(uei, exclude_id):
    target = uei.lower()
    for v in db.vendors.values():
        if v["id"] == exclude_id:
            continue
        if v["uei"].lower() == target and v["sam_status"] in ("ACTIVE", "EXPIRED"):
            return True
    return False


@bp.route("/vendors/<vendor_id>/activate", methods=["POST"])
def activate_vendor(vendor_id):
    auth(["Vendor"])
    vendor = get_or_404(db.vendors, vendor_id)
    body = get_body()
    renewed = opt_datetime(body, "registration_expires_at")

    status = vendor["sam_status"]
    if status not in ("DRAFT", "EXPIRED"):
        raise err("ERR_INVALID_STATE", "Vendor cannot be activated from its current state.")

    # If a renewed expiry was supplied (required on revival), apply it.
    if renewed is not None:
        vendor["registration_expires_at"] = body["registration_expires_at"]
        vendor["_expires_dt"] = renewed

    # UEI must remain exactly 12 alphanumeric chars.
    if not UEI_RE.match(vendor["uei"]):
        raise err("ERR_INVALID_REQUEST", "uei must be exactly 12 alphanumeric characters.")

    # Duplicate UEI over non-DRAFT (ACTIVE/EXPIRED) registrations.
    if _duplicate_uei_exists(vendor["uei"], vendor["id"]):
        raise err("ERR_DUPLICATE_UEI", "Another registration already holds this UEI.")

    # Expiry must lie strictly after the current logical clock.
    if not (vendor["_expires_dt"] > clock.now()):
        raise err("ERR_VALIDATION", "registration_expires_at must be after the current clock.")

    vendor["sam_status"] = "ACTIVE"
    touch(vendor)
    return object_response(vendor)


@bp.route("/vendors/<vendor_id>/expire", methods=["POST"])
def expire_vendor(vendor_id):
    auth(["ContractingOfficer"])
    vendor = get_or_404(db.vendors, vendor_id)
    if vendor["sam_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE registration can be expired.")
    vendor["sam_status"] = "EXPIRED"
    touch(vendor)
    return object_response(vendor)


@bp.route("/vendors/<vendor_id>/exclude", methods=["POST"])
def exclude_vendor(vendor_id):
    auth(["ContractingOfficer"])
    vendor = get_or_404(db.vendors, vendor_id)
    if vendor["sam_status"] not in ("ACTIVE", "EXPIRED"):
        raise err("ERR_INVALID_STATE", "Only ACTIVE or EXPIRED registrations can be excluded.")
    vendor["sam_status"] = "EXCLUDED"
    touch(vendor)
    return object_response(vendor)
