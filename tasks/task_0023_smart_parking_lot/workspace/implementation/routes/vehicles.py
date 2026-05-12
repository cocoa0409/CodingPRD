"""Vehicle endpoints."""
import re

from flask import Blueprint

import db
from errors import err
from middleware import require_auth
from response import success
from services.validation import get_body, require_str, optional_enum
from services.projection import vehicle_view


bp = Blueprint("vehicles", __name__)


VEHICLE_KINDS = {"REGULAR", "EMERGENCY", "DISABLED"}
PLATE_REGEX = re.compile(r"^[A-Z0-9-]{1,12}$")


def normalize_plate(raw: str) -> str:
    """Uppercase and strip ALL whitespace per PRD §3.2."""
    if not isinstance(raw, str):
        raise err("ERR_BAD_REQUEST", "plate must be a string")
    s = "".join(raw.split()).upper()
    return s


def recompute_vehicle_violation_state(vehicle_id: str) -> None:
    """Recompute open_violation_count and binding_eligible from current Violations."""
    v = db.vehicles.get(vehicle_id)
    if v is None:
        return
    n = 0
    for vio in db.violations.values():
        if vio.get("vehicle_id") != vehicle_id:
            continue
        if vio.get("status") in ("PENDING", "DISPUTED"):
            n += 1
    new_count = n
    new_eligible = (n == 0)
    if v.get("open_violation_count") != new_count or v.get("binding_eligible") != new_eligible:
        v["open_violation_count"] = new_count
        v["binding_eligible"] = new_eligible
        db.stamp_update(v)


@bp.route("/vehicles", methods=["POST"])
@require_auth(roles={"Operator", "GateSystem"})
def create_vehicle():
    body = get_body()
    raw_plate = body.get("plate")
    if raw_plate is None:
        raise err("ERR_BAD_REQUEST", "plate is required")
    plate = normalize_plate(raw_plate)
    if not plate or not PLATE_REGEX.match(plate):
        raise err("ERR_BAD_REQUEST", "plate must match /^[A-Z0-9-]{1,12}$/ after normalization")
    # Global uniqueness on normalized plate
    for v in db.vehicles.values():
        if v.get("plate") == plate:
            raise err("ERR_BAD_REQUEST", "Vehicle with this plate already exists")
    kind = optional_enum(body, "kind", VEHICLE_KINDS, default="REGULAR")
    veh = {
        "plate": plate,
        "kind": kind,
        "binding_eligible": True,
        "open_violation_count": 0,
    }
    db.stamp_create(veh)
    db.vehicles[veh["id"]] = veh
    return success(vehicle_view(veh), status=201)


@bp.route("/vehicles/<vehicle_id>", methods=["GET"])
@require_auth(roles={"Operator", "Driver", "EnforcementOfficer", "GateSystem", "Auditor"})
def get_vehicle(vehicle_id):
    v = db.vehicles.get(vehicle_id)
    if v is None:
        raise err("ERR_NOT_FOUND", "Vehicle not found")
    return success(vehicle_view(v))
