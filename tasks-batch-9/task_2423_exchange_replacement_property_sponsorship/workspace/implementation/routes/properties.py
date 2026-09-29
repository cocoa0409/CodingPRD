"""Property endpoints (PRD 3.1)."""
import re

from flask import Blueprint

import clock
import constants as C
import db
import middleware
from errors import ApiError, bad_request
from response import created_response, object_response
from routes._common import listing, read_one
from services import calc, domain

bp = Blueprint("properties", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


@bp.post("/properties")
def create_property():
    middleware.actor([C.SPONSOR])
    payload = middleware.body_or_400()
    name = middleware.req_str(payload, "name")
    state_code = middleware.req_str(payload, "state_code")
    if not STATE_CODE_RE.match(state_code):
        raise bad_request("Field 'state_code' must be exactly two uppercase letters.")
    asset_type = middleware.req_enum(payload, "asset_type", C.ASSET_TYPES)
    purchase_price_cents = middleware.req_int(payload, "purchase_price_cents", 1)
    appraised_value_cents = middleware.req_int(payload, "appraised_value_cents", 1)
    annual_noi_cents = middleware.req_int(payload, "annual_noi_cents", 0)
    occupancy_rate = middleware.req_ratio(payload, "occupancy_rate", 0, 1)
    contract_close_deadline = middleware.req_dt(payload, "contract_close_deadline")

    row = db.new_row(db.properties, {
        "name": name,
        "state_code": state_code,
        "asset_type": asset_type,
        "purchase_price_cents": purchase_price_cents,
        "appraised_value_cents": appraised_value_cents,
        "annual_noi_cents": annual_noi_cents,
        "occupancy_rate": occupancy_rate,
        "contract_close_deadline": contract_close_deadline,
        "depreciable_basis_cents": None,
        "acquired_at": None,
        "status": "UNDER_CONTRACT",
    })
    return created_response(db.serialize(row))


@bp.get("/properties/<property_id>")
def get_property(property_id):
    return read_one("property", C.READ_ALL, property_id)


@bp.get("/properties")
def list_properties():
    return listing(db.properties, C.READ_ALL,
                   str_filters=("state_code", "asset_type", "status"))


@bp.post("/properties/<property_id>/acquire")
def acquire_property(property_id):
    middleware.actor([C.SPONSOR])
    prop = domain.require("property", property_id)
    if prop["status"] != "UNDER_CONTRACT":
        raise ApiError("ERR_PROPERTY_INVALID_STATE")
    if clock.now() > prop["contract_close_deadline"]:
        raise ApiError("ERR_PROPERTY_CONTRACT_EXPIRED")
    prop["acquired_at"] = clock.now()
    prop["depreciable_basis_cents"] = calc.depreciable_basis(prop["purchase_price_cents"])
    prop["status"] = "ACQUIRED"
    db.touch(prop)
    return object_response(db.serialize(prop))


@bp.post("/properties/<property_id>/expire-contract")
def expire_property_contract(property_id):
    middleware.actor([C.SPONSOR])
    prop = domain.require("property", property_id)
    if prop["status"] != "UNDER_CONTRACT":
        raise ApiError("ERR_PROPERTY_INVALID_STATE")
    if clock.now() <= prop["contract_close_deadline"]:
        # a contract cannot be declared lapsed while it is still live
        raise ApiError("ERR_PROPERTY_INVALID_STATE")
    prop["status"] = "CONTRACT_EXPIRED"
    db.touch(prop)
    for trust in db.sorted_rows(db.trusts):
        if trust["property_id"] == prop["id"] and trust["status"] in ("FORMING", "FUNDING"):
            domain.refresh_posture(trust, force=True)
    return object_response(db.serialize(prop))
