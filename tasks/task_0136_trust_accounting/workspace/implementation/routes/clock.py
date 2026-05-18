"""Logical-clock test-driving endpoint (PRD §2.10)."""
from __future__ import annotations

from flask import Blueprint

from db import store
from errors import err_bad_request
from middleware import require_auth
from response import success
from utils import parse_iso

from routes._helpers import get_json

bp = Blueprint("clock", __name__)


@bp.post("/_clock/advance")
@require_auth(["TaxPreparer", "Trustee", "Grantor"])
def advance_clock():
    body = get_json()
    raw = body.get("to_timestamp")
    if raw is None:
        raise err_bad_request("to_timestamp required.")
    try:
        target = parse_iso(raw)
    except Exception:
        raise err_bad_request("to_timestamp must be ISO 8601.")
    with store.lock:
        store.clock.advance_to(target)
    return success({}, 200)
