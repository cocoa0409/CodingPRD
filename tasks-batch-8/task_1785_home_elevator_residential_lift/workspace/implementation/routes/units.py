"""ElevatorUnit endpoints (read-only; units are created by complete-installation)."""

from flask import Blueprint

import db
from errors import ERR_UNIT_NOT_FOUND
from middleware import ALL_ROLES, require_roles
from response import ok
from routes.common import get_or_404, list_endpoint
from util import serialize

bp = Blueprint("units", __name__)


@bp.get("/api/units")
@require_roles(*ALL_ROLES)
def list_units():
    return list_endpoint(db.units, {
        "property_id": "property_id",
        "project_id": "project_id",
        "product_model_id": "product_model_id",
        "modernized_from_unit_id": "modernized_from_unit_id",
        "equipment_status": "equipment_status",
        "registration_status": "registration_status",
    })


@bp.get("/api/units/<unitId>")
@require_roles(*ALL_ROLES)
def get_unit(unitId):
    rec = get_or_404(db.units, unitId, ERR_UNIT_NOT_FOUND, "Unit")
    return ok(serialize(rec))
