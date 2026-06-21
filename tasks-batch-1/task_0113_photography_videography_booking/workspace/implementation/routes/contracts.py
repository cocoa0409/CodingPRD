"""Contracts and the model-release gate (PRD §3.3)."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_RESOURCE,
    ERR_NOT_RESOURCE_OWNER,
)
from middleware import require_auth, ROLE_CLIENT, ROLE_STUDIO_ADMIN
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_str, optional_bool, serialize, serialize_list,
    parse_pagination, paginate, order_by_created_at,
)
from services.common import stamp_create, touch

bp = Blueprint("contracts", __name__)


@bp.post("/studio/contracts")
def create_contract():
    require_auth([ROLE_STUDIO_ADMIN])
    body = get_body()
    booking_id = require_str(body, "booking_id")
    includes_model_release = optional_bool(body, "includes_model_release", False)

    if booking_id not in db.bookings:
        raise APIError(ERR_INVALID_REFERENCE, 422, "Booking does not exist")

    # At most one non-VOID contract per booking (priority 18).
    for c in db.contracts.values():
        if c["booking_id"] == booking_id and c["status"] != "VOID":
            raise APIError(ERR_DUPLICATE_RESOURCE, 409,
                           "A non-VOID contract already exists for this booking")

    contract = {
        "booking_id": booking_id,
        "includes_model_release": includes_model_release,
        "status": "DRAFT",
        "signed_at": None,
    }
    stamp_create(contract)
    db.contracts[contract["id"]] = contract
    return ok_object(serialize(contract), 201)


def _find_contract_or_404(id):
    c = db.contracts.get(id)
    if c is None:
        raise APIError(ERR_NOT_FOUND, 404, "Contract not found")
    return c


@bp.get("/studio/contracts/<id>")
def get_contract(id):
    require_auth([ROLE_CLIENT, ROLE_STUDIO_ADMIN])
    c = _find_contract_or_404(id)
    _assert_contract_owner(c)
    return ok_object(serialize(c), 200)


def _assert_contract_owner(contract):
    if g.user_role == ROLE_CLIENT:
        booking = db.bookings.get(contract["booking_id"])
        if booking is None or g.user_id != booking["client_id"]:
            raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller does not own this contract")


@bp.get("/studio/contracts")
def list_contracts():
    require_auth([ROLE_CLIENT, ROLE_STUDIO_ADMIN])
    limit, offset = parse_pagination()
    items = list(db.contracts.values())
    for field in ("booking_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [c for c in items if c[field] == val]
    if g.user_role == ROLE_CLIENT:
        owned = {b["id"] for b in db.bookings.values() if b["client_id"] == g.user_id}
        items = [c for c in items if c["booking_id"] in owned]
    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/studio/contracts/<id>/send")
def send_contract(id):
    require_auth([ROLE_STUDIO_ADMIN])
    c = _find_contract_or_404(id)
    if c["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Contract is not DRAFT")
    c["status"] = "SENT"
    touch(c)
    return ok_object(serialize(c), 200)


@bp.post("/studio/contracts/<id>/sign")
def sign_contract(id):
    require_auth([ROLE_CLIENT])
    c = _find_contract_or_404(id)
    # Ownership (priority 4): the acting Client must own the contract's booking.
    booking = db.bookings.get(c["booking_id"])
    if booking is None or g.user_id != booking["client_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller does not own this contract")
    if c["status"] != "SENT":
        raise APIError(ERR_INVALID_STATE, 409, "Contract is not SENT")
    c["status"] = "SIGNED"
    c["signed_at"] = db.get_clock_iso()
    touch(c)
    return ok_object(serialize(c), 200)
