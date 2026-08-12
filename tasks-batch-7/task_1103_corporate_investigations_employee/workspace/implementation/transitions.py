"""Shared helpers for state-transition endpoints."""
from flask import g

import errors


def parse_to_status(p, allowed_statuses):
    """to_status is mandatory; an out-of-enum value is ERR_VALIDATION, an
    in-enum but illegal transition is handled later as ERR_INVALID_STATE."""
    to = p.get("to_status", None)
    if to is None:
        errors.missing_field("to_status")
    if to not in allowed_statuses:
        errors.validation(f"to_status must be one of {sorted(allowed_statuses)}")
    return to


def require_actor(to, mapping):
    """Per-transition actor restriction (RBAC §1.7). mapping values are role
    names or frozensets of role names; targets absent from the map have no
    actor restriction beyond the endpoint role set."""
    req = mapping.get(to)
    if req is None:
        return
    if isinstance(req, str):
        req = frozenset([req])
    if g.role not in req:
        errors.unauthorized_role(f"role {g.role} may not drive transition to {to}")


def need_rationale(p, field="rationale"):
    v = p.get(field, None)
    if v is None or (isinstance(v, str) and not v.strip()):
        errors.missing_field(field)
    if not isinstance(v, str):
        errors.validation(f"field {field} must be a string")
    return v
