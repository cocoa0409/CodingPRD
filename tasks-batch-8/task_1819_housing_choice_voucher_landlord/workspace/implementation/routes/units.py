"""Unit endpoints."""

from flask import Blueprint

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import (
    parse_pagination, get_or_404, sorted_page, landlord_of_unit, assert_landlord_owns,
)

bp = Blueprint("units", __name__)


def serialize_unit(u):
    return {
        "id": u["id"],
        "property_id": u["property_id"],
        "unit_label": u["unit_label"],
        "bedroom_count": u["bedroom_count"],
        "status": u["status"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


@bp.route("/hcv/units/<uid>", methods=["GET"])
def get_unit(uid):
    require_roles("HousingAuthorityAdmin", "Landlord")
    u = get_or_404(db.units, uid, "Unit")
    return success_object(serialize_unit(u))


@bp.route("/hcv/units/<uid>/delist", methods=["POST"])
def delist_unit(uid):
    role, user_id = require_roles("Landlord")
    u = get_or_404(db.units, uid, "Unit")
    if u["status"] != "LISTED":
        raise errors.invalid_state("Unit must be LISTED to delist")
    owner = landlord_of_unit(u)
    assert_landlord_owns(user_id, owner)
    u["status"] = "DELISTED"
    db.touch(u)
    return success_object(serialize_unit(u))


@bp.route("/hcv/units/<uid>/contracts", methods=["GET"])
def list_unit_contracts(uid):
    require_roles("HousingAuthorityAdmin", "Landlord")
    get_or_404(db.units, uid, "Unit")
    limit, offset = parse_pagination()
    rows = [c for c in db.hap_contracts.values() if c["unit_id"] == uid]
    page, total = sorted_page(rows, limit, offset)
    from routes.contracts import serialize_contract
    return success_list([serialize_contract(c) for c in page], total, limit, offset)
