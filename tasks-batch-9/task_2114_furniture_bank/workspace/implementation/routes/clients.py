"""Households (PRD 3.1)."""

from flask import Blueprint

from auth import authenticate, require_agency_scope, resolve
from core import COUNTIES
from db import db, new_entity, serialize
from envelope import object_response
from routes._common import filtered, respond_list
from validation import Field, pagination_params, validate_body

bp = Blueprint("clients", __name__)


@bp.route("/clients", methods=["POST"])
def create_client():
    actor = authenticate(["CaseManager"])
    payload = validate_body([
        Field("agency_id", "string"),
        Field("household_size", "integer", minimum=1, maximum=12),
        Field("county", "enum", members=COUNTIES),
        Field("has_infant", "boolean", required=False, default=False),
    ])
    agency = resolve("agency", payload["agency_id"])
    require_agency_scope(actor, agency["id"])

    client = new_entity(
        agency_id=agency["id"],
        household_size=payload["household_size"],
        county=payload["county"],
        has_infant=bool(payload["has_infant"]),
        bed_bug_status="CLEAR",
        bed_bug_confirmed_at=None,
        no_show_strikes=0,
        delivery_ban_until=None,
        lifetime_vouchers_delivered=0,
        status="ACTIVE",
    )
    db.clients[client["id"]] = client
    return object_response(serialize(client), 201)


@bp.route("/clients/<client_id>", methods=["GET"])
def get_client(client_id):
    actor = authenticate(["CaseManager", "DispatchPlanner", "PlatformAdmin"])
    client = resolve("client", client_id)
    require_agency_scope(actor, client["agency_id"])
    return object_response(serialize(client))


@bp.route("/clients", methods=["GET"])
def list_clients():
    authenticate(["CaseManager", "PlatformAdmin"])
    limit, offset = pagination_params()
    rows = filtered(list(db.clients.values()), {
        "agency_id": "agency_id",
        "status": "status",
        "county": "county",
    })
    return respond_list(rows, limit, offset)
