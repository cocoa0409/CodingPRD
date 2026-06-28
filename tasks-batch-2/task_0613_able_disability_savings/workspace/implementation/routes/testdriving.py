"""Test-driving capabilities: logical clock and market earnings crediting."""
from datetime import datetime, timezone

from flask import Blueprint

from db import db, touch
from middleware import get_identity, require_role
from response import ok
from errors import err
from services import domain
from clock import clock
from routes.common import get_body, find_or_404, require_string, require_int

bp = Blueprint("testdriving", __name__)


def _parse_iso(s):
    """Parse an ISO 8601 instant. Accept trailing Z."""
    if not isinstance(s, str) or s == "":
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 string")
    raw = s
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        # date-only fallback
        try:
            dt = datetime.fromisoformat(s[:10])
        except ValueError:
            raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    body = get_body()
    require_string(body, "to_iso8601")
    dt = _parse_iso(body["to_iso8601"])
    clock.set(dt)
    # side effects: expire certs past expires_on, suspend OPEN accounts
    domain.apply_clock_effects()
    return ok({"current_utc": clock.iso()})


@bp.post("/_market/credit_earnings")
def credit_earnings():
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    body = get_body()
    require_string(body, "account_id")
    delta = require_int(body, "earnings_delta_cents")
    a = find_or_404(db.accounts, body["account_id"], "Account")
    a["earnings_cents"] += delta
    a["balance_cents"] += delta
    domain.recompute_ssi_posture(a)
    touch(a)
    return ok(domain.serialize_account(a))
