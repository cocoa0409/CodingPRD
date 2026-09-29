"""Shared helpers for the status-transition endpoints (PRD 2.8 precedence)."""
from errors import ApiError


def reject_system_only(to_status, target_roles):
    """A target no client role may drive is refused regardless of role or state."""
    if to_status not in target_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED_FOR_STATUS")


def require_target_role(role, to_status, target_roles):
    allowed = target_roles.get(to_status)
    if allowed is None or role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED_FOR_STATUS")


def require_transition(current, to_status, table):
    if to_status not in table.get(current, ()):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")


def filter_rows(rows, spec):
    """spec: iterable of (query-param-name, row-field-name) pairs."""
    from flask import request

    out = rows
    for param, field in spec:
        value = request.args.get(param)
        if value is None:
            continue
        out = [row for row in out if row.get(field) == value]
    return out
