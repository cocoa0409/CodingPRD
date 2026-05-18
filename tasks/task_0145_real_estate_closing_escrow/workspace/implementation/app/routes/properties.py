"""Property endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify

from app import store
from app.auth import require_role
from app.errors import ApiError
from app.envelope import success_envelope
from app.idempotency import lookup as idem_lookup, remember as idem_remember, require_idempotency_key
from app.request_helpers import get_json_body
from app.serializers import serialize_property
from app.util import new_uuid, now_ts, optional_number, require_str, round_half_up_money

bp = Blueprint("properties", __name__)


@bp.post("/properties")
def create_property():
    require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    street = require_str(body, "street_address")
    parcel = require_str(body, "parcel_id")
    hoa = round_half_up_money(optional_number(body, "hoa_annual_dues", 0))
    tax = round_half_up_money(optional_number(body, "tax_annual", 0))
    if hoa < 0 or tax < 0:
        raise ApiError("ERR_BAD_REQUEST", "hoa_annual_dues and tax_annual must be non-negative.")

    pid = new_uuid()
    ts = now_ts()
    prop = {
        "id": pid,
        "street_address": street,
        "parcel_id": parcel,
        "hoa_annual_dues": hoa,
        "tax_annual": tax,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.properties[pid] = prop
    response = success_envelope(serialize_property(prop))
    idem_remember(idem_key, body, 201, response)
    return jsonify(response), 201


@bp.get("/properties/<property_id>")
def read_property(property_id: str):
    require_role(["EscrowOfficer", "TitleOfficer", "Buyer", "Seller"])
    prop = store.properties.get(property_id)
    if prop is None:
        raise ApiError("ERR_NOT_FOUND", "Property not found.")
    return jsonify(success_envelope(serialize_property(prop))), 200
