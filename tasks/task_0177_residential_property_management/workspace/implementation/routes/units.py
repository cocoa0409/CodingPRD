"""Unit routes (PRD §3.1)."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, require_int, parse_pagination, paginate,
    filter_param,
)

bp = Blueprint("units", __name__)


@bp.route("/units", methods=["POST"])
def create_unit():
    require_role({"PropertyManager"})
    body = get_json_body()
    property_id = require_string(body, "property_id")
    label = require_string(body, "label")
    market_rent = require_int(body, "market_rent_cents", minimum=1)
    with db.LOCK:
        prop = db.properties.get(property_id)
        if prop is None:
            raise err(errors.ERR_FK_NOT_FOUND, "property_id does not resolve")
        common = db.new_common()
        record = {
            **{k: common[k] for k in ("id", "created_at", "updated_at", "version", "_seq")},
            "property_id": property_id,
            "label": label,
            "market_rent_cents": market_rent,
            "occupancy_status": "VACANT_READY",
            "active_lease_id": None,
        }
        db.units[record["id"]] = record
        # Increment the property unit_count (mutation -> version bump).
        prop["unit_count"] += 1
        db.touch(prop)
        return object_response(serialize(record), 201)


@bp.route("/units/<id>", methods=["GET"])
def get_unit(id):
    require_role({"PropertyManager", "Owner", "Tenant"})
    with db.LOCK:
        record = db.units.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Unit not found")
        return object_response(serialize(record), 200)


@bp.route("/units", methods=["GET"])
def list_units():
    require_role({"PropertyManager", "Owner"})
    property_id = filter_param(request.args, "property_id")
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.units.values())
        if property_id is not None:
            records = [r for r in records if r["property_id"] == property_id]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)
