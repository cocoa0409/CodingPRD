"""Recruiter routes."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..common import get_json_body, require_fields, require_str, stamp_new
from ..errors import ApiError
from ..lookups import path_recruiter
from ..response import respond
from ..serializers import serialize_recruiter
from ..store import store


recruiters_bp = Blueprint("recruiters", __name__)


@recruiters_bp.post("/recruiters")
@require_auth("PlatformAdmin")
def create_recruiter():
    body = get_json_body()
    require_fields(body, "email", "full_name", "department_code")
    email = require_str(body["email"], "email")
    full_name = require_str(body["full_name"], "full_name")
    department_code = require_str(body["department_code"], "department_code")
    is_active = body.get("is_active", True)
    if not isinstance(is_active, bool):
        raise ApiError("ERR_VALIDATION", "is_active must be a boolean")

    with store.lock:
        for r in store.recruiters.values():
            if r["email"] == email:
                raise ApiError("ERR_VALIDATION", "recruiter email is already in use")
        recruiter = stamp_new({
            "email": email,
            "full_name": full_name,
            "department_code": department_code,
            "is_active": is_active,
        })
        store.recruiters[recruiter["id"]] = recruiter
    return respond(serialize_recruiter(recruiter), 201)


@recruiters_bp.get("/recruiters/<rid>")
@require_auth("PlatformAdmin", "Recruiter", "HiringManager")
def get_recruiter(rid):
    with store.lock:
        return respond(serialize_recruiter(path_recruiter(rid)))
