"""Staff endpoints."""
from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import get_auth, require_role
from response import success_response
from services.common import new_entity, get_staff
from services.serializers import serialize_staff

bp = Blueprint("staff", __name__)

STAFF_ROLES = {"FITTING_SPECIALIST", "REPAIR_TECHNICIAN", "INSTRUCTOR", "SHOP_MANAGER"}


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/staff")
def create_staff():
    user_id, role = get_auth()
    require_role(role, {"ShopAdmin"})
    data = _body()
    full_name = data.get("full_name")
    staff_role = data.get("staff_role")
    active = data.get("active", True)
    if not isinstance(full_name, str) or not full_name.strip():
        raise_err("ERR_VALIDATION", "full_name is required")
    if staff_role not in STAFF_ROLES:
        raise_err("ERR_VALIDATION", "invalid staff_role")
    if not isinstance(active, bool):
        raise_err("ERR_VALIDATION", "active must be a boolean")
    s = new_entity()
    s.update({
        "full_name": full_name,
        "staff_role": staff_role,
        "active": active,
    })
    db.staff[s["id"]] = s
    return success_response(serialize_staff(s), status=201)


@bp.get("/staff/<sid>")
def read_staff(sid):
    user_id, role = get_auth()
    require_role(role, {"ShopAdmin", "ShopManager"})
    s = get_staff(sid)
    return success_response(serialize_staff(s))
