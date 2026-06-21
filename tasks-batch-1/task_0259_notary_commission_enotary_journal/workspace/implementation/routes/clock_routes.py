"""Test-driving clock endpoints (PRD §3.9). Auth-exempt.

set_current_utc pins the clock to an instant. advance moves the clock forward
and, as it does, marks expiries: any ACTIVE notary whose commission_expires_at
is now in the past transitions to EXPIRED (enotary off, audit).
"""
from flask import Blueprint

from clock import parse_iso8601
from db import store, touch
from domain import audit
from errors import err
from middleware import endpoint
from response import success
from validation import get_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(("CommissionAuthority",), exempt_auth=True)
def set_current_utc():
    body = get_body()
    raw = body.get("to_iso8601")
    instant = parse_iso8601(raw) if raw is not None else None
    if instant is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant")
    store.clock.set(instant)
    return success({})


@bp.post("/_clock/advance")
@endpoint(("CommissionAuthority",), exempt_auth=True)
def advance():
    body = get_body()
    raw = body.get("to_iso8601")
    instant = parse_iso8601(raw) if raw is not None else None
    if instant is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant")
    store.clock.advance(instant)
    now = store.clock.now()
    # Mark expiries: ACTIVE notary past commission_expires_at -> EXPIRED.
    for notary in store.notaries.values():
        if notary["status"] != "ACTIVE":
            continue
        expires = notary.get("commission_expires_at")
        if not expires:
            continue
        expires_dt = parse_iso8601(expires)
        if expires_dt is not None and now > expires_dt:
            notary["status"] = "EXPIRED"
            notary["enotary_authorized"] = False
            touch(notary)
            audit(notary["id"], "NOTARY", notary["id"], "NOTARY_EXPIRED", "SYSTEM",
                  "Commission expired")
    return success({})
