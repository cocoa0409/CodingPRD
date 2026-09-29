"""Request screening steps 1-3, 5, 15 and 16 (PRD 2.5)."""

from flask import request

from constants import ROLES
from errors import ApiError

PARTNER = "PartnerAccountLead"


def authenticate(allowed_roles):
    """Steps 1-3.  Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip() or role is None or not str(role).strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return uid, role


def body():
    """The parsed JSON body, or {} when absent/unparseable."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    return data


def check_action_role(role, action, mapping):
    """Step 5."""
    allowed = mapping.get(action)
    if allowed is None:  # pragma: no cover - enum validated at step 4
        return
    if role not in allowed:
        raise ApiError("ERR_ACTION_ROLE_NOT_PERMITTED")


def check_scope(role, uid, partnership_id):
    """Step 15."""
    if role == PARTNER and uid != partnership_id:
        raise ApiError("ERR_PARTNERSHIP_SCOPE_VIOLATION")


def scope_filter(role, uid, partnership_id_filter):
    """List-endpoint scoping: a PartnerAccountLead only ever sees its own
    partnership's records, and an explicit filter naming a different partnership
    is a scope violation."""
    if role != PARTNER:
        return partnership_id_filter
    if partnership_id_filter is not None and partnership_id_filter != uid:
        raise ApiError("ERR_PARTNERSHIP_SCOPE_VIOLATION")
    return uid
