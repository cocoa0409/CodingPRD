"""Property routes (PRD §3.1) — create, get, list, trust funding."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, require_enum, optional_int, require_int,
    parse_pagination, paginate, filter_param,
)
from services import domain

bp = Blueprint("properties", __name__)

STATE_CODES = {"CA", "NY", "TX", "IL", "FL"}


@bp.route("/properties", methods=["POST"])
def create_property():
    require_role({"PropertyManager"})
    body = get_json_body()
    owner_id = require_string(body, "owner_id")
    name = require_string(body, "name")
    state_code = require_enum(body, "state_code", STATE_CODES)
    address = require_string(body, "address")
    reserve_floor = optional_int(body, "reserve_floor_cents", 0, minimum=0)
    with db.LOCK:
        if owner_id not in db.owners:
            raise err(errors.ERR_FK_NOT_FOUND, "owner_id does not resolve")
        common = db.new_common()
        record = {
            **{k: common[k] for k in ("id", "created_at", "updated_at", "version", "_seq")},
            "owner_id": owner_id,
            "name": name,
            "state_code": state_code,
            "address": address,
            "trust_balance_cents": 0,
            "distributable_cents": 0,
            "reserve_floor_cents": reserve_floor,
            "unit_count": 0,
        }
        db.properties[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/properties/<id>", methods=["GET"])
def get_property(id):
    require_role({"PropertyManager", "Owner"})
    with db.LOCK:
        record = db.properties.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Property not found")
        return object_response(serialize(record), 200)


@bp.route("/properties", methods=["GET"])
def list_properties():
    require_role({"PropertyManager", "Owner"})
    owner_id = filter_param(request.args, "owner_id")
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.properties.values())
        if owner_id is not None:
            records = [r for r in records if r["owner_id"] == owner_id]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/properties/<id>/trust-deposits", methods=["POST"])
def trust_deposit(id):
    require_role({"PropertyManager"})
    body = get_json_body()
    amount = require_int(body, "amount_cents", minimum=1)
    with db.LOCK:
        prop = db.properties.get(id)
        if prop is None:
            raise err(errors.ERR_NOT_FOUND, "Property not found")
        domain.credit_trust(prop, amount)
        return object_response(serialize(prop), 201)
