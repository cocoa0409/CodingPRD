"""Auth header extraction + RBAC, and shared request helpers.

Auth headers (PRD 2.1): X-User-ID and X-User-Role.
Recognized roles: Participant, RaceDirector, PacketStaff, TimingOfficial.
"""
import datetime

from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, ERR_INVALID_REQUEST

ROLES = {"Participant", "RaceDirector", "PacketStaff", "TimingOfficial"}


def auth():
    """Validate the two mandatory headers. Returns (user_id, role).

    Missing X-User-ID or X-User-Role, or unknown role => ERR_UNAUTHENTICATED.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unknown authentication headers")
    return user_id, role


def require_role(role, allowed):
    """RBAC: role must be one of the allowed roles for this operation."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role '%s' may not perform this operation" % role)


def get_json():
    """Parse the JSON body; tolerate empty bodies (return {})."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


# ----- ISO 8601 parsing / formatting -----

def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or raise
    ERR_INVALID_REQUEST. Accepts trailing 'Z'."""
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "Timestamp must be an ISO 8601 string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Invalid ISO 8601 timestamp: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def fmt_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits + Z."""
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def now_dt():
    """Current logical server clock (aware UTC)."""
    from db import clock
    return clock.now()
