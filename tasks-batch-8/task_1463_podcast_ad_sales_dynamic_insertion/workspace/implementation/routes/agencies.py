"""Agency endpoints: create, get."""

from flask import Blueprint, request

import db
from errors import err_not_found
from helpers import body_of, new_id, now_timestamp, require_string, require_int
from middleware import require_roles, ALL_ROLES
from response import success_object, serialize

bp = Blueprint("agencies", __name__)


def get_agency_or_404(agency_id):
    agency = db.agencies.get(agency_id)
    if agency is None:
        raise err_not_found(f"Agency '{agency_id}' not found")
    return agency


@bp.route("/adnet/agencies", methods=["POST"])
def create_agency():
    require_roles({"AdOps"})
    body = body_of(request)
    name = require_string(body, "name")
    commission_bps = require_int(body, "commission_bps", minimum=0, maximum=5000)

    ts = now_timestamp()
    agency = {
        "id": new_id(),
        "name": name,
        "commission_bps": commission_bps,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.agencies[agency["id"]] = agency
    return success_object(serialize(agency), 201)


@bp.route("/adnet/agencies/<agency_id>", methods=["GET"])
def get_agency(agency_id):
    require_roles(ALL_ROLES)
    return success_object(serialize(get_agency_or_404(agency_id)))
