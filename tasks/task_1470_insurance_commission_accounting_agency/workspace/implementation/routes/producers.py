"""Producer endpoints."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import auth, ADMIN, ADMIN_ACCT, ALL_ROLES
from response import ok
from services import (
    TIERS,
    has_pending_chargebacks,
    new_resource,
    ser_producer,
    touch,
)
from util import (
    apply_filters,
    as_bool,
    as_enum,
    as_str,
    get_body,
    is_int,
    req,
    respond_list,
)

bp = Blueprint("producers", __name__)


@bp.post("/agency/producers")
def create_producer():
    auth(ADMIN_ACCT)
    data = get_body()
    # Priority 3: body FK references.
    upline = data.get("upline_producer_id")
    if isinstance(upline, str) and upline not in DB["producers"]:
        raise ApiError("ERR_NOT_FOUND", 404, "upline_producer_id does not reference an existing producer")
    # Priority 8: uniqueness.
    lic = data.get("license_number")
    if isinstance(lic, str) and any(
        p["license_number"] == lic for p in DB["producers"].values()
    ):
        raise ApiError("ERR_LICENSE_NUMBER_EXISTS", 409, "license_number already in use")
    # Priority 10: shape.
    name = as_str(req(data, "name"), "name")
    license_number = as_str(req(data, "license_number"), "license_number")
    tier = as_enum(data.get("tier", "STANDARD"), "tier", TIERS)
    if upline is not None:
        as_str(upline, "upline_producer_id")
    tax_form = as_bool(data.get("tax_form_on_file", False), "tax_form_on_file")
    p = new_resource({
        "name": name,
        "license_number": license_number,
        "tier": tier,
        "upline_producer_id": upline,
        "tax_form_on_file": tax_form,
        "status": "ACTIVE",
    })
    DB["producers"][p["id"]] = p
    return ok(ser_producer(p), 201)


@bp.get("/agency/producers")
def list_producers():
    auth(ALL_ROLES)
    items = apply_filters(
        DB["producers"].values(),
        {"upline_producer_id": "upline_producer_id", "status": "status", "tier": "tier"},
    )
    return respond_list(items, ser_producer)


@bp.get("/agency/producers/<producerId>")
def get_producer(producerId):
    auth(ALL_ROLES)
    p = DB["producers"].get(producerId)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Producer not found")
    return ok(ser_producer(p))


@bp.post("/agency/producers/<producerId>/reactivate")
def reactivate_producer(producerId):
    auth(ADMIN_ACCT)
    p = DB["producers"].get(producerId)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Producer not found")
    # Priority 4: state admissibility.
    if p["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Producer is not SUSPENDED")
    # Priority 8: aggregate constraint.
    if has_pending_chargebacks(p["id"]):
        raise ApiError(
            "ERR_PRODUCER_STILL_SUSPENDED",
            409,
            "Producer still has PENDING chargebacks",
        )
    p["status"] = "ACTIVE"
    touch(p)
    return ok(ser_producer(p))


@bp.post("/agency/producers/<producerId>/terminate")
def terminate_producer(producerId):
    auth(ADMIN)
    p = DB["producers"].get(producerId)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Producer not found")
    if p["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Producer is already TERMINATED")
    p["status"] = "TERMINATED"
    touch(p)
    return ok(ser_producer(p))
