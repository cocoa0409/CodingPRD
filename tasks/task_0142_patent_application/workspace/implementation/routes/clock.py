"""Logical-clock endpoints (SCAFFOLD §1.5).

GET    /_clock           -> any authenticated role
POST   /_clock/advance   -> USPTOAdmin
"""

from flask import Blueprint

from config import ROLE_APPLICANT, ROLE_EXAMINER, ROLE_USPTO_ADMIN
from db import store
from errors import make_error
from middleware import parse_json_body, require_auth
from response import success
from services.patent_engine import advance_clock
from utils import iso_now


clock_bp = Blueprint("clock", __name__)


@clock_bp.get("/_clock")
@require_auth(allowed_roles=[ROLE_APPLICANT, ROLE_EXAMINER, ROLE_USPTO_ADMIN])
def get_clock_route():
    return success({"now": iso_now(store.now())})


@clock_bp.post("/_clock/advance")
@require_auth(allowed_roles=[ROLE_USPTO_ADMIN])
def advance_clock_route():
    body = parse_json_body(required_fields=["to"])
    to_value = body["to"]
    if not isinstance(to_value, str):
        raise make_error("ERR_VALIDATION", "to must be an ISO 8601 string.")
    with store.lock:
        result = advance_clock(to_value)
    return success(result)
