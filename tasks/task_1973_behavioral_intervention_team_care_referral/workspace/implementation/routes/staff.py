from flask import Blueprint

import errors as E
import response
from db import store, new_record, serialize
from errors import ApiError
from middleware import require_auth, ALL_ROLES
from routes.util import body, get_or_404
from services.domain import OFFICES

bp = Blueprint("staff", __name__)


@bp.post("/bit/staff")
def create_staff():
    require_auth(["SystemAdmin"])
    b = body()
    full_name = b.get("full_name")
    office = b.get("office")
    active = b.get("active", True)
    if not isinstance(full_name, str) or not full_name:
        raise ApiError(E.ERR_VALIDATION, 400, "full_name is required")
    if office not in OFFICES:
        raise ApiError(E.ERR_VALIDATION, 400, "office must be a declared office value")
    if not isinstance(active, bool):
        raise ApiError(E.ERR_VALIDATION, 400, "active must be a boolean")
    rec = new_record()
    rec.update({"full_name": full_name, "office": office, "active": active})
    store.staff[rec["id"]] = rec
    return response.obj(serialize(rec), 201)


@bp.get("/bit/staff/<sid>")
def get_staff(sid):
    require_auth(list(ALL_ROLES))
    rec = get_or_404(store.staff, sid, "staff member")
    return response.obj(serialize(rec))
