"""Suppliers: onboarding, reads, reinstatement and offboarding."""
from flask import Blueprint

import auth
import cascade
import response
import store
import validate
from errors import ApiError
from store import db, touch

from routes import common

bp = Blueprint("suppliers", __name__)

SUPPLIER_TYPES = ("HOTEL", "AIR")
VISIBILITY = ("PENDING_CERT", "ACTIVE", "SUSPENDED", "OFFBOARDED")
CERT_LEVELS = ("NONE", "PROVISIONAL", "CERTIFIED")
LIVE_LEVELS = ("PROVISIONAL", "CERTIFIED")


@bp.post("/suppliers")
def create_supplier():
    auth.authenticate(("PlatformAdmin", "CommercialManager"))
    data = validate.body()
    raw_market = data.get("home_market_id")
    if isinstance(raw_market, str) and raw_market:
        common.find("markets", raw_market)          # body reference: priority 5
    legal_name = validate.str_req(data, "legal_name")
    supplier_type = validate.enum_req(data, "supplier_type", SUPPLIER_TYPES)
    market_id = validate.str_req(data, "home_market_id")
    contact_email = validate.str_req(data, "contact_email")
    conversion_index = validate.num_opt(data, "conversion_index", 50, 0, 100)
    supplier = store.new_row("suppliers", {
        "legal_name": legal_name,
        "supplier_type": supplier_type,
        "home_market_id": market_id,
        "contact_email": contact_email,
        "conversion_index": conversion_index,
        "certification_level": "NONE",
        "content_score": 0,
        "connectivity_score": 0,
        "visibility_status": "PENDING_CERT",
        "current_model": "NONE",
        "parity_strikes": 0,
        "suspension_reason": None,
        "_backing_cert_id": None,
    })
    return response.obj(supplier, 201)


@bp.get("/suppliers/<supplier_id>")
def read_supplier(supplier_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("suppliers", supplier_id), 200)


@bp.get("/suppliers")
def list_suppliers():
    auth.authenticate(auth.ALL_ROLES)
    market_id = validate.filter_str("home_market_id")
    visibility = validate.filter_enum("visibility_status", VISIBILITY)
    level = validate.filter_enum("certification_level", CERT_LEVELS)
    rows = []
    for row in db["suppliers"].values():
        if market_id is not None and row["home_market_id"] != market_id:
            continue
        if visibility is not None and row["visibility_status"] != visibility:
            continue
        if level is not None and row["certification_level"] != level:
            continue
        rows.append(row)
    return common.paged(rows)


@bp.post("/suppliers/<supplier_id>/reinstate")
def reinstate(supplier_id):
    auth.authenticate(("ComplianceOfficer",))
    supplier = common.find("suppliers", supplier_id)
    data = validate.body()
    validate.str_opt(data, "note")
    common.guard_offboarded(supplier)
    if supplier["visibility_status"] != "SUSPENDED" \
            or supplier["certification_level"] not in LIVE_LEVELS:
        raise ApiError("ERR_SUPPLIER_NOT_SUSPENDED")
    supplier["visibility_status"] = "ACTIVE"
    supplier["suspension_reason"] = None
    touch(supplier)
    return response.obj(supplier, 200)


@bp.post("/suppliers/<supplier_id>/offboard")
def offboard(supplier_id):
    auth.authenticate(("PlatformAdmin",))
    supplier = common.find("suppliers", supplier_id)
    data = validate.body()
    validate.str_req(data, "reason")
    common.guard_offboarded(supplier)
    held = {o["id"] for o in cascade.offers_of_supplier(supplier["id"])}
    for booking in db["bookings"].values():
        if booking["fulfillment_status"] not in ("RESERVED", "CONFIRMED"):
            continue
        for offer in common.booking_components(booking):
            if offer["id"] in held:
                raise ApiError("ERR_BOOKING_NOT_RESERVED",
                               "The supplier still has bookings in RESERVED or CONFIRMED.")
    cascade.offboard_supplier(supplier)
    return response.obj(supplier, 200)
