"""Attendee endpoints incl. self-registration and ban (PRD §3.2)."""
from flask import Blueprint

import common
import db
import errors
from middleware import authenticate, authorize, get_identity, KNOWN_ROLES
from services import lookup
import response

bp = Blueprint("attendees", __name__)

LOYALTY_TIERS = {"NONE", "SILVER", "GOLD", "PLATINUM"}
READ_ROLES = {"ConventionAdmin", "RegistrationAgent", "Attendee"}


@bp.route("/attendees", methods=["POST"])
def create_attendee():
    # Self-registration: may be performed by an unauthenticated (Anonymous) caller
    # (PRD §2.1). If auth headers are present, the role must be one of the allowed
    # roles for this operation.
    user_id, role = get_identity()
    if role is not None:
        if not user_id or role not in KNOWN_ROLES:
            raise errors.err(errors.ERR_UNAUTHENTICATED, "Invalid authentication headers")
        authorize(role, {"Anonymous", "ConventionAdmin", "RegistrationAgent"})

    body = common.get_body()
    email = common.require_str(body, "email")
    full_name = common.require_str(body, "full_name")
    loyalty = common.optional_enum(body, "loyalty_tier", LOYALTY_TIERS, "NONE")

    # Unique email, case-insensitive (PRD §3.2).
    lowered = email.lower()
    for att in db.attendees.values():
        if att["email"].lower() == lowered:
            raise errors.err(errors.ERR_DUPLICATE_EMAIL, "Attendee email already exists")

    row = common.common_fields()
    row.update({
        "email": email,
        "full_name": full_name,
        "loyalty_tier": loyalty,
        "status": "ACTIVE",
    })
    db.attendees[row["id"]] = row
    return response.success(common.serialize(row), 201)


@bp.route("/attendees/<aid>", methods=["GET"])
def get_attendee(aid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    att = lookup.attendee(aid)
    return response.success(common.serialize(att), 200)


@bp.route("/attendees/<aid>/ban", methods=["POST"])
def ban_attendee(aid):
    _, role = authenticate()
    authorize(role, {"ConventionAdmin"})
    att = lookup.attendee(aid)
    body = common.get_body()
    expected = common.require_int(body, "expected_attendee_version")
    if expected != att["version"]:
        raise errors.err(errors.ERR_STALE_ATTENDEE_VERSION, "Stale attendee version")
    att["status"] = "BANNED"
    common.touch(att)
    return response.success(common.serialize(att), 200)
