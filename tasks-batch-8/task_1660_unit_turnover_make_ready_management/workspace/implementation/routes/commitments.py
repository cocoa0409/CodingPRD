"""Lease commitment endpoints: pre-leasing and cancellation (PRD §3.8)."""
from flask import Blueprint

import db
import services
from db import store
from errors import ApiError
from middleware import authenticate, require_roles
from response import created, ok
from validation import get_body, validate_schema

bp = Blueprint("commitments", __name__)

COMMITMENT_SCHEMA = {
    "unit_id": ("string", True, None),
    "applicant_name": ("string", True, None),
    "committed_delivery_date": ("date", True, None),
}


@bp.post("/make-ready/lease-commitments")
def create_lease_commitment():
    authenticate()
    require_roles(["TurnCoordinator"])
    body = get_body()
    validate_schema(body, COMMITMENT_SCHEMA)
    unit = store.units.get(body["unit_id"])
    if unit is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Unit not found")
    turn = services.active_turn_of_unit(unit["id"])
    if turn is None or not turn.get("projected_ready_date"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Pre-leasing requires an active turn on the unit "
                       "whose projection has been established")
    for c in services.commitments_of_unit(unit["id"]):
        if c["status"] in ("ACTIVE", "AT_RISK"):
            raise ApiError("ERR_COMMITMENT_EXISTS", 422,
                           "Unit already has a lease commitment in ACTIVE or "
                           "AT_RISK")
    projected = db.parse_date(turn["projected_ready_date"])
    committed = db.parse_date(body["committed_delivery_date"])
    if committed < projected:
        raise ApiError("ERR_DELIVERY_BEFORE_PROJECTED", 422,
                       "committed_delivery_date is earlier than the active "
                       "turn's projected_ready_date")
    commitment = {
        "id": db.new_id(),
        "unit_id": unit["id"],
        "applicant_name": body["applicant_name"],
        "committed_delivery_date": body["committed_delivery_date"],
        "status": "ACTIVE",
    }
    db.new_common(commitment)
    store.commitments[commitment["id"]] = commitment
    return created(commitment)


@bp.post("/make-ready/lease-commitments/<commitment_id>/cancel")
def cancel_lease_commitment(commitment_id):
    authenticate()
    require_roles(["TurnCoordinator", "PropertyManager"])
    validate_schema(get_body(), {})
    commitment = store.commitments.get(commitment_id)
    if commitment is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Lease commitment not found")
    if commitment["status"] not in ("ACTIVE", "AT_RISK"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ACTIVE or AT_RISK commitment can be cancelled")
    commitment["status"] = "CANCELLED"
    db.touch(commitment)
    return ok(commitment)
