"""Logical clock (test-driving) — PRD §2.10."""
from flask import Blueprint

from db import STORE
from middleware import get_auth, require_roles
from response import success
from services.validation import require_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.route("/disaster-relief/_clock/set", methods=["POST"])
def set_clock():
    _uid, role = get_auth()
    require_roles(role, ["ProgramAdmin"])
    body = require_body()
    to = req_datetime(body, "to_iso8601")
    with STORE.lock:
        STORE.current_utc = to
    return success({}, status=200)
