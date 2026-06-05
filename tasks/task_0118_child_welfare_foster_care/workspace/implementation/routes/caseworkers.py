"""Caseworker routes (PRD §2.1, §3). Admin registers caseworkers."""
from flask import Blueprint, request

import db
import errors
import helpers
import middleware
import response
from services import serialize

bp = Blueprint("caseworkers", __name__)

ROLE_TYPES = {"SCREENER", "INVESTIGATOR", "CASEWORKER", "LICENSING"}
ALL_ROLES = {"Admin", "IntakeScreener", "Investigator", "Caseworker", "LicensingWorker", "Judge"}


@bp.route("/caseworkers", methods=["POST"])
def create_caseworker():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin"})
    body = helpers.get_body()
    full_name = helpers.require_str(body, "full_name")
    role_type = helpers.require_enum(body, "role_type", ROLE_TYPES)
    email = helpers.require_str(body, "email")
    active = helpers.optional_bool(body, "active", default=True)
    # Email must be unique across all caseworker rows.
    for cw in db.caseworkers.values():
        if cw["email"] == email:
            raise errors.invalid_request("email must be unique across all caseworkers.")
    record = {
        "full_name": full_name,
        "role_type": role_type,
        "email": email,
        "active": active,
    }
    db.stamp_create(record)
    db.caseworkers[record["id"]] = record
    return response.success(serialize.caseworker(record), 201)


@bp.route("/caseworkers/<cid>", methods=["GET"])
def get_caseworker(cid):
    _, role = middleware.authenticate()
    middleware.authorize(role, ALL_ROLES)
    record = db.caseworkers.get(cid)
    if record is None:
        raise errors.not_found("Caseworker not found.")
    return response.success(serialize.caseworker(record), 200)


@bp.route("/caseworkers", methods=["GET"])
def list_caseworkers():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin"})
    limit, offset = helpers.pagination()
    role_type = request.args.get("role_type")
    records = list(db.caseworkers.values())
    if role_type is not None:
        records = [r for r in records if r["role_type"] == role_type]
    page, total = helpers.paginate(records, limit, offset)
    return response.list_success([serialize.caseworker(r) for r in page], limit, offset, total)
