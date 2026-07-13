from flask import Blueprint, request

import errors
from auth import require
from common import (
    get_body,
    lookup,
    paginate,
    parse_pagination,
    require_int,
    require_present,
    require_string,
)
from constants import DEVICE_CATEGORIES
from envelope import array_response, object_response
from services.logic import serialize_inspector
from store import base_fields, db

bp = Blueprint("inspectors", __name__)


@bp.route("/inspectors", methods=["POST"])
@require("Registrar")
def create_inspector():
    body = get_body()
    name = require_string(body, "name")
    license_number = require_string(body, "license_number")
    license_expiry_period = require_int(body, "license_expiry_period")
    require_present(body, "certified_categories")
    cats = body["certified_categories"]
    if not isinstance(cats, list) or any(
        not isinstance(c, str) or c not in DEVICE_CATEGORIES for c in cats
    ):
        raise errors.invalid_request("certified_categories must be a list of valid categories.")
    inspector = base_fields()
    inspector.update({
        "name": name,
        "license_number": license_number,
        "license_expiry_period": license_expiry_period,
        "certified_categories": list(cats),
    })
    db.inspectors[inspector["id"]] = inspector
    return object_response(serialize_inspector(inspector), 201)


@bp.route("/inspectors/<inspector_id>", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "LicensedInspector", "BuildingOwner")
def get_inspector(inspector_id):
    inspector = lookup(db.inspectors, inspector_id, "ERR_INSPECTOR_NOT_FOUND")
    return object_response(serialize_inspector(inspector), 200)


@bp.route("/inspectors", methods=["GET"])
@require("Registrar", "SafetyAdministrator")
def list_inspectors():
    limit, offset = parse_pagination()
    category = request.args.get("certified_category")
    items = list(db.inspectors.values())
    if category is not None:
        items = [i for i in items if category in i["certified_categories"]]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_inspector(i) for i in page], limit, offset, total)
