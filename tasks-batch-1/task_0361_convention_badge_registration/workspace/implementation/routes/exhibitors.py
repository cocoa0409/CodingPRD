"""Exhibitor endpoints incl. self-registration (PRD §3.2, §3.7)."""
from flask import Blueprint, request

import common
import db
import errors
from middleware import authenticate, authorize, get_identity, KNOWN_ROLES
from services import lookup
import response

bp = Blueprint("exhibitors", __name__)

READ_ROLES = {"ConventionAdmin", "RegistrationAgent", "Exhibitor"}


@bp.route("/exhibitors", methods=["POST"])
def create_exhibitor():
    # Self-registration: may be performed by an unauthenticated (Anonymous) caller
    # (PRD §2.1). Allowed roles: Anonymous, ConventionAdmin.
    user_id, role = get_identity()
    if role is not None:
        if not user_id or role not in KNOWN_ROLES:
            raise errors.err(errors.ERR_UNAUTHENTICATED, "Invalid authentication headers")
        authorize(role, {"Anonymous", "ConventionAdmin"})

    body = common.get_body()
    # Existence of the body FK convention_id is checked before well-formedness of
    # other fields per left-to-right resolution (PRD §2.8); but required-field
    # presence for convention_id is itself part of resolution.
    convention_id = common.require_str(body, "convention_id")
    company_name = common.require_str(body, "company_name")
    contact_email = common.require_str(body, "contact_email")

    lookup.convention(convention_id)

    lowered = contact_email.lower()
    for ex in db.exhibitors.values():
        if ex["contact_email"].lower() == lowered:
            raise errors.err(errors.ERR_DUPLICATE_EMAIL, "Exhibitor contact email already exists")

    row = common.common_fields()
    row.update({
        "convention_id": convention_id,
        "company_name": company_name,
        "contact_email": contact_email,
        "estimated_booth_cents": 0,
        "actual_booth_cents": 0,
    })
    db.exhibitors[row["id"]] = row
    return response.success(common.serialize(row), 201)


@bp.route("/exhibitors/<eid>", methods=["GET"])
def get_exhibitor(eid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    ex = lookup.exhibitor(eid)
    return response.success(common.serialize(ex), 200)


@bp.route("/exhibitors", methods=["GET"])
def list_exhibitors():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    rows = list(db.exhibitors.values())
    conv_filter = request.args.get("convention_id")
    if conv_filter is not None:
        rows = [e for e in rows if e["convention_id"] == conv_filter]
    items, limit, offset, total = common.paginate(rows)
    return response.success_list(items, limit, offset, total)
