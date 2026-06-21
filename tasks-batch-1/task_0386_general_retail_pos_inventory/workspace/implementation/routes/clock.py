"""Logical clock test-driving endpoint (PRD §3.12)."""
from datetime import datetime, timezone

from flask import Blueprint

from db import DB
from middleware import auth_context, require_role
from common import touch, get_json_body, as_str
from response import success
from errors import err, ERR_INVALID_REQUEST

bp = Blueprint("clock", __name__)


@bp.route("/_clock/advance", methods=["POST"])
def advance_clock():
    _, role = auth_context()
    require_role(role, {"StoreManager"})
    body = get_json_body()
    to_iso = as_str(body, "to_iso8601")
    with DB.lock:
        DB.logical_clock = to_iso
        # layaway due-date sweep: every ACTIVE layaway whose due_date is now in
        # the past and whose balance remains > 0 moves ACTIVE -> DELINQUENT.
        for layaway in DB.layaways.values():
            if layaway["status"] != "ACTIVE":
                continue
            if layaway["balance_cents"] <= 0:
                continue
            if _is_past(layaway["due_date"], to_iso):
                layaway["status"] = "DELINQUENT"
                touch(layaway)
        # endpoint output is null (no resource) -> empty object data
        return success({})


def _parse_iso(s):
    """Parse an ISO 8601 string to an aware UTC datetime. Tolerates a trailing
    'Z' and a bare date (interpreted as midnight UTC)."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        try:
            dt = datetime.fromisoformat(txt + "T00:00:00")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_past(due_date, now_iso):
    """True when now_iso is strictly after due_date (PRD §3.12: now > due_date)."""
    due = _parse_iso(due_date)
    now = _parse_iso(now_iso)
    if due is None or now is None:
        # fall back to lexical compare on equal-format strings
        return str(now_iso) > str(due_date)
    return now > due
