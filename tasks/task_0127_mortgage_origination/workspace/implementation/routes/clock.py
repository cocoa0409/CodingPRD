"""SystemClock + test-reset endpoints."""

from flask import Blueprint

import db
from config import (
    ROLE_ADMIN,
    ROLE_BORROWER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_LOAN_OFFICER,
)
from errors import ERR_VALIDATION, raise_error
from middleware import require_role
from response import get_json_body, success
from services import clock as svc
from services.validation import require_string


clock_bp = Blueprint("clock", __name__)


@clock_bp.post("/_clock/advance")
def clock_advance():
    require_role(ROLE_ADMIN)
    body = get_json_body()
    to_text = require_string(body, "to")
    try:
        now_iso = svc.advance_to(to_text)
    except Exception:
        raise_error(ERR_VALIDATION, "Invalid ISO 8601 timestamp for `to`.")
    return success({"now": now_iso})


@clock_bp.get("/_clock")
def clock_read():
    require_role(ROLE_ADMIN, ROLE_LOAN_OFFICER, ROLE_COMPLIANCE_OFFICER, ROLE_BORROWER)
    return success({"now": svc.get_now_iso()})


@clock_bp.post("/__test__/reset")
def test_reset():
    """Wipe all in-memory state (test-only convenience; conftest hits this between tests)."""
    require_role(ROLE_ADMIN)
    db.reset_all()
    return success({"reset": True})
