"""Building routes."""
from flask import Blueprint, request, g

import db
from errors import err
from middleware import require_auth
from response import success
from services.lookups import get_building
from services.validation import require_body, require_str, require_int
from services.occ import check_version


bp = Blueprint("buildings", __name__)


@bp.post("/buildings")
@require_auth(roles={"PropertyManager"})
def create_building():
    body = require_body(request)
    name = require_str(body, "name")
    address = require_str(body, "address")
    floors_count = require_int(body, "floors_count", min_value=1)
    b = {
        "name": name,
        "address": address,
        "floors_count": floors_count,
        "status": "ACTIVE",
    }
    db.stamp_create(b)
    db.buildings[b["id"]] = b
    return success(db.public(b), status=201)


@bp.get("/buildings/<building_id>")
@require_auth(roles={"PropertyManager", "LeasingAgent", "FinanceOfficer"})
def get_building_route(building_id):
    b = get_building(building_id)
    return success(db.public(b))
