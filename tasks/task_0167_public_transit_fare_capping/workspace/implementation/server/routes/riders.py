"""Rider routes."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..common import get_json_body, require_fields, stamp_new
from ..errors import ApiError
from ..response import respond
from ..serializers import rider_view
from ..store import store


bp = Blueprint("riders", __name__, url_prefix="/transit/riders")


@bp.post("")
@require_auth("AgencyOfficer")
def create_rider():
    body = get_json_body()
    require_fields(body, "full_name", "email")
    email = body["email"]
    if not isinstance(email, str) or not email.strip():
        raise ApiError("ERR_VALIDATION", "email is required")
    full_name = body["full_name"]
    if not isinstance(full_name, str) or not full_name.strip():
        raise ApiError("ERR_VALIDATION", "full_name is required")

    with store.lock:
        for r in store.riders.values():
            if r["email"] == email:
                raise ApiError("ERR_VALIDATION", "email already in use")
        rider = {
            "full_name": full_name,
            "email": email,
            "low_income_verified": False,
            "employer_id": None,
        }
        stamp_new(rider)
        store.riders[rider["id"]] = rider
    return respond(rider_view(rider), 201)


@bp.get("/<rider_id>")
@require_auth("Rider", "AgencyOfficer", "Auditor")
def get_rider(rider_id: str):
    with store.lock:
        rider = store.riders.get(rider_id)
        if rider is None:
            raise ApiError("ERR_NOT_FOUND", "Rider not found")
        if g.user_role == "Rider" and g.user_id != rider_id:
            raise ApiError("ERR_FORBIDDEN", "Riders may only view their own resource")
        return respond(rider_view(rider), 200)
