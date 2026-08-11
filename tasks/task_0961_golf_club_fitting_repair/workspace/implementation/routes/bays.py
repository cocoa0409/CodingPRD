"""Launch monitor bay endpoints."""
from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import get_auth, require_role
from response import success_response
from services.common import new_entity, touch, get_bay
from services.serializers import serialize_bay

bp = Blueprint("bays", __name__)


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/launch-monitor-bays")
def create_bay():
    user_id, role = get_auth()
    require_role(role, {"ShopManager", "ShopAdmin"})
    data = _body()
    bay_name = data.get("bay_name")
    cleanup_buffer_minutes = data.get("cleanup_buffer_minutes", 15)
    if not isinstance(bay_name, str) or not bay_name.strip():
        raise_err("ERR_VALIDATION", "bay_name is required")
    if not isinstance(cleanup_buffer_minutes, int) or isinstance(cleanup_buffer_minutes, bool):
        raise_err("ERR_VALIDATION", "cleanup_buffer_minutes must be an integer")
    for existing in db.bays.values():
        if existing["bay_name"] == bay_name:
            raise_err("ERR_VALIDATION", "bay_name must be unique")
    b = new_entity()
    b.update({
        "bay_name": bay_name,
        "status": "AVAILABLE",
        "cleanup_buffer_minutes": cleanup_buffer_minutes,
    })
    db.bays[b["id"]] = b
    return success_response(serialize_bay(b), status=201)


@bp.get("/launch-monitor-bays/<bid>")
def read_bay(bid):
    user_id, role = get_auth()
    require_role(role, {"ShopAdmin", "ShopManager", "FittingSpecialist",
                        "RepairTechnician", "Instructor"})
    b = get_bay(bid)
    return success_response(serialize_bay(b))


@bp.post("/launch-monitor-bays/<bid>/set-status")
def set_bay_status(bid):
    user_id, role = get_auth()
    require_role(role, {"ShopManager"})
    data = _body()
    target_status = data.get("target_status")
    if target_status not in ("AVAILABLE", "MAINTENANCE"):
        raise_err("ERR_VALIDATION", "target_status must be AVAILABLE or MAINTENANCE")
    b = get_bay(bid)
    b["status"] = target_status
    touch(b)
    return success_response(serialize_bay(b))
