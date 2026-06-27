"""Agency endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db, lock
from middleware import get_identity, require_role
from response import object_response
from services.common import (
    mint_common,
    public,
    get_json_body,
    require_str,
    require_int,
    lookup,
)

bp = Blueprint("agencies", __name__)

ALL_ROLES = {"Agent", "CastingDirector", "Talent"}


@bp.route("/agencies", methods=["POST"])
def create_agency():
    _, role = get_identity()
    require_role(role, {"Agent"})
    body = get_json_body()
    name = require_str(body, "name")
    commission_rate_bps = require_int(body, "commission_rate_bps", minimum=0, maximum=5000)
    with lock:
        record = mint_common({
            "name": name,
            "commission_rate_bps": commission_rate_bps,
            "escrow_balance_cents": 0,
            "booked_day_count": 0,
        })
        db.agencies[record["id"]] = record
        return object_response(public(record), status=201)


@bp.route("/agencies/<agency_id>", methods=["GET"])
def get_agency(agency_id):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        record = lookup("Agency", agency_id)
        return object_response(public(record), status=200)
