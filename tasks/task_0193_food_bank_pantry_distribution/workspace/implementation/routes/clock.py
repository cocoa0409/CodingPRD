"""Test-driving clock: set current UTC, run expiry + certification aging sweeps."""
from datetime import timedelta

from flask import Blueprint

from db import db
from errors import err, ERR_INVALID_REQUEST
from middleware import get_identity, require_role
from response import object_response
from services import models
from services.validate import get_json_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    user_id, role = get_identity()
    require_role(role, {"FoodBankOperator", "AllocationManager"})
    body = get_json_body()
    if "to_iso8601" not in body or not isinstance(body.get("to_iso8601"), str):
        raise err(ERR_INVALID_REQUEST, "Missing or invalid to_iso8601.")
    try:
        new_now = models.parse_iso(body["to_iso8601"])
    except Exception:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be ISO 8601.")

    db.current_utc = new_now

    # Shelf-life sweep: AVAILABLE lots with expiration_date <= now -> EXPIRED.
    touched_units = set()
    for lot in db.inventory_lots.values():
        if lot["disposition"] == "AVAILABLE" and (
            models.parse_iso(lot["expiration_date"]) <= new_now
        ):
            lot["disposition"] = "EXPIRED"
            models.touch(lot)
            touched_units.add(lot["cold_storage_unit_id"])
    for unit_id in touched_units:
        unit = db.cold_storage_units.get(unit_id)
        if unit is not None:
            models.recompute_unit_occupancy(unit)

    # Certification aging: CERTIFIED households 365d past certified_at -> EXPIRED.
    for h in db.client_households.values():
        if h["certification_status"] == "CERTIFIED" and h.get("certified_at"):
            certified_at = models.parse_iso(h["certified_at"])
            if new_now >= certified_at + timedelta(days=365):
                h["certification_status"] = "EXPIRED"
                models.touch(h)

    return object_response({})
