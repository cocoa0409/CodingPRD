"""Technician roster endpoints (PRD §3.12)."""

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_auth, require_roles
from response import object_response
from serializers import technician_view
import common as C

bp = Blueprint("technicians", __name__)


@bp.post("/aquatics/technicians")
def create_technician():
    _, role = get_auth()
    require_roles(role, {"Dispatcher"})
    data = C.require_body(request.get_json(silent=True))
    tech_user_id = C.req_str(data, "tech_user_id")
    full_name = C.req_str(data, "full_name")
    certified = C.req_bool(data, "certified_for_reef", allow_missing=True, default=False)
    active = C.req_bool(data, "active", allow_missing=True, default=True)

    # tech_user_id unique among technicians
    for t in store.technicians.values():
        if t["tech_user_id"] == tech_user_id:
            raise ApiError("ERR_INVALID_REQUEST", "tech_user_id must be unique.")

    rec = C.make_record({
        "tech_user_id": tech_user_id,
        "full_name": full_name,
        "certified_for_reef": certified,
        "active": active,
    })
    store.technicians[rec["id"]] = rec
    return object_response(technician_view(rec), 201)


@bp.get("/aquatics/technicians/<tid>")
def get_technician(tid):
    _, role = get_auth()
    require_roles(role, {"Dispatcher", "AccountManager", "FieldTech"})
    rec = store.technicians.get(tid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Technician not found.")
    return object_response(technician_view(rec))
