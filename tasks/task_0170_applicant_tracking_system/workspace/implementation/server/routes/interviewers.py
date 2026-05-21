"""Interviewer routes."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..common import get_json_body, require_fields, require_str, stamp_new
from ..errors import ApiError
from ..response import respond
from ..serializers import serialize_interviewer
from ..store import store


interviewers_bp = Blueprint("interviewers", __name__)


@interviewers_bp.post("/interviewers")
@require_auth("PlatformAdmin")
def create_interviewer():
    body = get_json_body()
    require_fields(body, "email", "full_name", "department_code")
    email = require_str(body["email"], "email")
    full_name = require_str(body["full_name"], "full_name")
    department_code = require_str(body["department_code"], "department_code")
    is_certified = body.get("is_certified_for_eeo", False)
    if not isinstance(is_certified, bool):
        raise ApiError("ERR_VALIDATION", "is_certified_for_eeo must be a boolean")

    with store.lock:
        for i in store.interviewers.values():
            if i["email"] == email:
                raise ApiError("ERR_VALIDATION", "interviewer email is already in use")
        interviewer = stamp_new({
            "email": email,
            "full_name": full_name,
            "department_code": department_code,
            "is_certified_for_eeo": is_certified,
        })
        store.interviewers[interviewer["id"]] = interviewer
    return respond(serialize_interviewer(interviewer), 201)
