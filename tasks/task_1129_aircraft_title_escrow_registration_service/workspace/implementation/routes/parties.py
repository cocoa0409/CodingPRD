"""Party endpoints."""

from flask import Blueprint

from db import party_store, make_common_fields
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import require_roles, ALL_ROLES
from response import success_object
from validators import get_body, require_fields, require_string, require_enum

bp = Blueprint("parties", __name__)

VALID_PARTY_TYPES = ["BUYER", "SELLER", "LENDER", "TRUSTEE"]


@bp.route("/api/parties", methods=["POST"])
def create_party():
    user_id, role = require_roles(["EscrowOfficer"])
    body = get_body()
    require_fields(body, ["party_type", "legal_name"], ["email", "is_citizenship_verified"])

    party_type = require_enum(body["party_type"], "party_type", VALID_PARTY_TYPES)
    legal_name = require_string(body["legal_name"], "legal_name")
    email = body.get("email")
    if email is not None and not isinstance(email, str):
        raise ApiError(ERR_INVALID_REQUEST, "email must be a string.", 400)
    is_cv = body.get("is_citizenship_verified", False)
    if not isinstance(is_cv, bool):
        raise ApiError(ERR_INVALID_REQUEST, "is_citizenship_verified must be a boolean.", 400)

    fields = make_common_fields()
    party = {
        **fields,
        "party_type": party_type,
        "legal_name": legal_name,
        "email": email,
        "is_citizenship_verified": is_cv,
    }
    party_store[party["id"]] = party
    return success_object(party, 201)


@bp.route("/api/parties/<id>", methods=["GET"])
def get_party(id):
    user_id, role = require_roles(ALL_ROLES)
    p = party_store.get(id)
    if not p:
        raise ApiError(ERR_NOT_FOUND, "Party not found.", 404)
    return success_object(p)
