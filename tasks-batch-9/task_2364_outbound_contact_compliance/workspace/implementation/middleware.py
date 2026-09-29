"""Authentication, role authorisation and request-body access.

Implements steps 1-3 of the compliance gate ladder (PRD §2.8):
  1. header presence and role validity -> ERR_UNAUTHENTICATED
  2. the acting role appearing on the endpoint -> ERR_FORBIDDEN_ROLE
  3. Consumer ownership of the payload contact_id -> ERR_NOT_CONTACT_OWNER
Body well-formedness (step 4) is deliberately deferred until the handler asks
for the payload, so that step 3 can run first.
"""

import functools
import json

from flask import g, request

from errors import ApiError

ROLES = ("Consumer", "CampaignManager", "ComplianceOfficer", "DialerOperator", "PlatformAdmin")

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def _authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def _parse_body():
    """Parse the JSON body lazily; remember a parse failure for step 4."""
    raw = request.get_data(cache=True)
    g.body_error = False
    if raw is None or not raw.strip():
        g.body = {}
        return
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        g.body = {}
        g.body_error = True
        return
    if not isinstance(parsed, dict):
        g.body = {}
        g.body_error = True
        return
    g.body = parsed


def payload():
    """Return the parsed JSON body, raising ERR_INVALID_REQUEST if malformed."""
    if getattr(g, "body_error", False):
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not a JSON object.")
    return getattr(g, "body", {})


def endpoint(roles, consumer_owns_contact=False):
    """Wrap a view with ladder steps 1-3."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            _authenticate()
            if g.role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            _parse_body()
            if consumer_owns_contact and g.role == "Consumer" and not g.body_error:
                if "contact_id" in g.body and g.body.get("contact_id") != g.user_id:
                    raise ApiError("ERR_NOT_CONTACT_OWNER")
            return view(*args, **kwargs)

        return wrapper

    return decorator
