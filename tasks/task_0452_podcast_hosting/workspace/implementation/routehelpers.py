"""Shared per-request helpers used by every route module.

Centralizes the validation precedence from PRD §2.5:
  1 auth (ERR_UNAUTHENTICATED)  2 role (ERR_FORBIDDEN)
  3 ownership (ERR_NOT_RESOURCE_OWNER)  4 existence (ERR_NOT_FOUND)
  5 state (ERR_INVALID_STATE)  6+ business rules  last body (ERR_INVALID_REQUEST)
"""

from flask import request

import errors
from middleware import authenticate, require_role


def auth_and_role(allowed_roles):
    """Authenticate then check role. Returns the Caller."""
    caller = authenticate()
    require_role(caller, allowed_roles)
    return caller


def body():
    """Parse JSON body, tolerating an empty body as {}."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Body must be valid JSON")
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return data
