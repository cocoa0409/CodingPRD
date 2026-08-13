"""Auth header extraction, role checking, request-shape validation, pagination."""
from datetime import datetime, date

import db
from errors import (
    err_unauthenticated,
    err_invalid_request,
    err_forbidden,
)

DECLARED_ROLES = {
    "SupplyAdmin",
    "SupplyPlanner",
    "PricingDesk",
    "CreditManager",
    "Dispatcher",
    "DealerUser",
    "SystemAdmin",
}

# Roles whose X-User-ID is the id of an existing Dealer (entity_backed).
ENTITY_BACKED_ROLES = {"DealerUser"}


def authenticate():
    """Priority 1a: headers present, role declared, entity-backed id resolves."""
    role = None
    user_id = None
    from flask import request

    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise err_unauthenticated()
    if role not in DECLARED_ROLES:
        raise err_unauthenticated()
    if role in ENTITY_BACKED_ROLES and user_id not in db.dealers:
        raise err_unauthenticated("Entity-backed identity does not resolve")
    return {"role": role, "user_id": user_id}


def authorize(caller, allowed_roles):
    """Priority 2: caller role must be listed for the endpoint."""
    if caller["role"] not in allowed_roles:
        raise err_forbidden()


# ---------------------------------------------------------------------------
# Request-shape validation helpers (priority 1b -> ERR_INVALID_REQUEST 400)
# ---------------------------------------------------------------------------

def get_json_body(required=False):
    from flask import request

    if not request.data:
        if required:
            raise err_invalid_request("Request body required")
        return {}
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return body


def req_string(body, field):
    v = body.get(field)
    if v is None:
        raise err_invalid_request(f"Missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, str):
        raise err_invalid_request(f"Field {field} must be a string")
    return v


def opt_string(body, field):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, str):
        raise err_invalid_request(f"Field {field} must be a string")
    return v


def req_int(body, field):
    v = body.get(field)
    if v is None:
        raise err_invalid_request(f"Missing required field: {field}")
    return _as_int(v, field)


def opt_int(body, field):
    v = body.get(field)
    if v is None:
        return None
    return _as_int(v, field)


def _as_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"Field {field} must be an integer")
    return v


def req_enum(body, field, members):
    v = req_string(body, field)
    if v not in members:
        raise err_invalid_request(f"Field {field} must be one of {sorted(members)}")
    return v


def req_date(body, field):
    v = req_string(body, field)
    try:
        d = date.fromisoformat(v)
    except (ValueError, TypeError):
        raise err_invalid_request(f"Field {field} must be an ISO date")
    if "T" in v or " " in v:
        raise err_invalid_request(f"Field {field} must be an ISO date (YYYY-MM-DD)")
    return d


def req_datetime(body, field):
    v = req_string(body, field)
    return _parse_dt(v, field)


def _parse_dt(v, field):
    s = v
    try:
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err_invalid_request(f"Field {field} must be an ISO 8601 datetime")
    if dt.tzinfo is None:
        from datetime import timezone

        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_iso_dt(s):
    """Lenient internal parse for stored timestamps."""
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def pagination_params():
    from flask import request

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit out of range [1, 100]")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def opt_query_string(field):
    from flask import request

    v = request.args.get(field)
    return v if v is not None else None


def opt_query_enum(field, members):
    v = opt_query_string(field)
    if v is not None and v not in members:
        raise err_invalid_request(f"Query {field} must be one of {sorted(members)}")
    return v
