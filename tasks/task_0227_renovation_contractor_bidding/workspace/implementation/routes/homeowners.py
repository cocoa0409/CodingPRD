"""Homeowner routes."""
from flask import Blueprint

import db
import errors
import response
from middleware import require_roles
from services import common, lookups

bp = Blueprint("homeowners", __name__)


@bp.route("/homeowners", methods=["POST"])
def create_homeowner():
    # Anonymous (public) — no auth headers required.
    body = common.get_body()
    full_name = common.as_str(common.require_field(body, "full_name"), "full_name")
    email = common.as_str(common.require_field(body, "email"), "email")
    # email unique across homeowners
    for h in db.homeowners.values():
        if h["email"] == email:
            raise errors.invalid_request("email must be unique across homeowners.")
    rec = {
        "full_name": full_name,
        "email": email,
    }
    common.stamp_new(rec)
    db.homeowners[rec["id"]] = rec
    return response.success(common.public(rec), 201)


@bp.route("/homeowners/<rid>", methods=["GET"])
def get_homeowner(rid):
    require_roles("Homeowner", "PlatformAdmin")
    rec = lookups.get_homeowner(rid)
    return response.success(common.public(rec), 200)
