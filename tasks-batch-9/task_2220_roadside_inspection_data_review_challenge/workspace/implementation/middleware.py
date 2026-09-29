"""Authentication, role authorisation and carrier scoping (PRD 2.1, 2.8)."""

from flask import request

from errors import err

ROLES = (
    "CarrierAnalyst",
    "CarrierSafetyManager",
    "StateInspectionOfficer",
    "FmcsaReviewOfficer",
    "FmcsaProgramAuditor",
)

ALL_ROLES = ROLES
CARRIER_ROLES = ("CarrierAnalyst", "CarrierSafetyManager")


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_carrier_side(self):
        return self.role in CARRIER_ROLES


def actor(*allowed):
    """Tier 1 then tier 2 of the rejection order."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise err("ERR_UNAUTHENTICATED")
    if not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED")
    if allowed and role not in allowed:
        raise err("ERR_ROLE_NOT_PERMITTED")
    return Actor(user_id, role)


def scope(act, carrier_id):
    """Tier 6: single-resource carrier ownership."""
    if act.is_carrier_side and carrier_id != act.user_id:
        raise err("ERR_CARRIER_SCOPE_VIOLATION")


def scope_rows(act, rows, key):
    """List endpoints are silently filtered rather than rejected."""
    if not act.is_carrier_side:
        return rows
    return [r for r in rows if r.get(key) == act.user_id]
