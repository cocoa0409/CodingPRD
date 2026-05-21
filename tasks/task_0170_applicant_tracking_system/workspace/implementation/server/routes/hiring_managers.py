"""HiringManager routes."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..common import get_json_body, positive_int, require_fields, require_str, stamp_new
from ..errors import ApiError
from ..response import respond
from ..serializers import serialize_hiring_manager
from ..store import store


hiring_managers_bp = Blueprint("hiring_managers", __name__)


@hiring_managers_bp.post("/hiring-managers")
@require_auth("PlatformAdmin")
def create_hiring_manager():
    body = get_json_body()
    require_fields(body, "email", "full_name", "department_code", "budget_cents")
    email = require_str(body["email"], "email")
    full_name = require_str(body["full_name"], "full_name")
    department_code = require_str(body["department_code"], "department_code")
    budget_cents = positive_int(body["budget_cents"], "budget_cents", allow_zero=True)

    with store.lock:
        for h in store.hiring_managers.values():
            if h["email"] == email:
                raise ApiError("ERR_VALIDATION", "hiring manager email is already in use")
        manager = stamp_new({
            "email": email,
            "full_name": full_name,
            "department_code": department_code,
            "budget_cents": budget_cents,
        })
        store.hiring_managers[manager["id"]] = manager
    return respond(serialize_hiring_manager(manager), 201)
