"""Property endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import (
    parse_pagination, get_or_404, sorted_page, assert_landlord_owns,
)

bp = Blueprint("properties", __name__)


def serialize_property(p):
    return {
        "id": p["id"],
        "landlord_id": p["landlord_id"],
        "address": p["address"],
        "zip_code": p["zip_code"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/hcv/properties", methods=["POST"])
def create_property():
    role, user_id = require_roles("HousingAuthorityAdmin", "Landlord")
    body = request.get_json(force=True, silent=True) or {}
    landlord_id = body.get("landlord_id")
    address = body.get("address")
    zip_code = body.get("zip_code")
    landlord = get_or_404(db.landlords, landlord_id, "Landlord")
    if role == "Landlord":
        assert_landlord_owns(user_id, landlord)
    if landlord["status"] != "ACTIVE":
        raise errors.landlord_suspended()
    rec = db.make_record({
        "landlord_id": landlord_id,
        "address": address,
        "zip_code": zip_code,
    })
    db.properties[rec["id"]] = rec
    return success_object(serialize_property(rec), 201)


@bp.route("/hcv/properties/<pid>", methods=["GET"])
def get_property(pid):
    require_roles("HousingAuthorityAdmin", "Landlord")
    p = get_or_404(db.properties, pid, "Property")
    return success_object(serialize_property(p))


@bp.route("/hcv/properties/<pid>/units", methods=["GET"])
def list_property_units(pid):
    require_roles("HousingAuthorityAdmin", "Landlord")
    get_or_404(db.properties, pid, "Property")
    limit, offset = parse_pagination()
    rows = [u for u in db.units.values() if u["property_id"] == pid]
    page, total = sorted_page(rows, limit, offset)
    from routes.units import serialize_unit
    return success_list([serialize_unit(u) for u in page], total, limit, offset)


@bp.route("/hcv/properties/<pid>/units", methods=["POST"])
def create_unit(pid):
    role, user_id = require_roles("HousingAuthorityAdmin", "Landlord")
    body = request.get_json(force=True, silent=True) or {}
    prop = get_or_404(db.properties, pid, "Property")
    landlord = db.landlords.get(prop["landlord_id"])
    if role == "Landlord":
        assert_landlord_owns(user_id, landlord)
    if landlord and landlord["status"] != "ACTIVE":
        raise errors.landlord_suspended()
    unit_label = body.get("unit_label")
    bedroom_count = body.get("bedroom_count")
    rec = db.make_record({
        "property_id": pid,
        "unit_label": unit_label,
        "bedroom_count": bedroom_count,
        "status": "LISTED",
    })
    db.units[rec["id"]] = rec
    from routes.units import serialize_unit
    return success_object(serialize_unit(rec), 201)
