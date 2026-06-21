"""Landlord and Tenant routes."""

from flask import Blueprint

import db
from errors import err
from middleware import get_auth, require_role
from response import object_response
from routes.helpers import lookup
from services import domain
import validation as V

bp = Blueprint("parties", __name__)


@bp.post("/landlords")
def create_landlord():
    _, role = get_auth()
    require_role(role, {"Landlord"})
    body = V.get_body()
    legal_name = V.require_str(body, "legal_name")
    email = V.require_str(body, "email")
    payout_account_ref = V.require_str(body, "payout_account_ref")

    rec = {
        "id": db.new_id(),
        "legal_name": legal_name,
        "email": email,
        "payout_account_ref": payout_account_ref,
    }
    domain._stamp_new(rec)
    db.landlords[rec["id"]] = rec
    return object_response(domain.serialize_landlord(rec), 201)


@bp.get("/landlords/<rid>")
def get_landlord(rid):
    _, role = get_auth()
    require_role(role, {"Landlord", "Tenant", "EscrowAgent"})
    rec = lookup(db.landlords, rid)
    return object_response(domain.serialize_landlord(rec), 200)


@bp.post("/tenants")
def create_tenant():
    _, role = get_auth()
    require_role(role, {"Tenant"})
    body = V.get_body()
    legal_name = V.require_str(body, "legal_name")
    email = V.require_str(body, "email")
    credit_score = V.require_int(body, "credit_score")
    if credit_score < 300 or credit_score > 850:
        raise err("ERR_INVALID_REQUEST", "credit_score must be between 300 and 850")

    rec = {
        "id": db.new_id(),
        "legal_name": legal_name,
        "email": email,
        "credit_score": credit_score,
    }
    domain._stamp_new(rec)
    db.tenants[rec["id"]] = rec
    return object_response(domain.serialize_tenant(rec), 201)


@bp.get("/tenants/<rid>")
def get_tenant(rid):
    _, role = get_auth()
    require_role(role, {"Landlord", "Tenant", "EscrowAgent"})
    rec = lookup(db.tenants, rid)
    return object_response(domain.serialize_tenant(rec), 200)
