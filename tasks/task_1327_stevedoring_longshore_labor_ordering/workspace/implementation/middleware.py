"""Auth header extraction, RBAC, request serialization lock, and input validators."""
import re
import threading
from datetime import datetime, timezone

from flask import g, request

import errors

LOCK = threading.RLock()

DECLARED_ROLES = (
    "StevedoreAdmin",
    "StevedoreSuperintendent",
    "LaborHallDispatcher",
    "GangForeman",
    "ClaimsAdjuster",
    "PayrollClerk",
    "BillingClerk",
)

ANY_ROLE = DECLARED_ROLES


def authenticate():
    """Priority 1: X-User-Role and X-User-ID present, role is declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in DECLARED_ROLES:
        raise errors.unauthenticated()
    g.user_id = uid
    g.user_role = role


def require_roles(*roles):
    """Priority 2: acting role must be admitted by the endpoint."""
    if g.user_role not in roles:
        raise errors.forbidden()


# ---------------------------------------------------------------------------
# Input validators (priority 4 — schema). All raise ERR_VALIDATION on failure.
# ---------------------------------------------------------------------------

def body_dict(body):
    if not isinstance(body, dict):
        raise errors.validation("Request body must be a JSON object")
    return body


def req_field(body, field):
    if field not in body or body[field] is None:
        raise errors.validation(f"Missing required field: {field}")
    return body[field]


def opt_field(body, field, default=None):
    v = body.get(field, default)
    return v


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise errors.validation(f"Field {field} must be a non-empty string")
    return value


def req_str(body, field):
    return as_str(req_field(body, field), field)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def as_int(value, field, min_value=None, max_value=None):
    if not _is_int(value):
        raise errors.validation(f"Field {field} must be an integer")
    if min_value is not None and value < min_value:
        raise errors.validation(f"Field {field} must be >= {min_value}")
    if max_value is not None and value > max_value:
        raise errors.validation(f"Field {field} must be <= {max_value}")
    return value


def req_int(body, field, min_value=None, max_value=None):
    return as_int(req_field(body, field), field, min_value, max_value)


def opt_int(body, field, min_value=None, max_value=None):
    if field not in body or body[field] is None:
        return None
    return as_int(body[field], field, min_value, max_value)


def req_num(body, field, min_value=None, gt=None):
    v = req_field(body, field)
    if not _is_num(v):
        raise errors.validation(f"Field {field} must be a number")
    if min_value is not None and v < min_value:
        raise errors.validation(f"Field {field} must be >= {min_value}")
    if gt is not None and not v > gt:
        raise errors.validation(f"Field {field} must be > {gt}")
    return v


def req_enum(body, field, allowed):
    v = req_field(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise errors.validation(f"Field {field} must be one of {sorted(allowed)}")
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], bool):
        raise errors.validation(f"Field {field} must be a boolean")
    return body[field]


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def req_date(body, field):
    v = req_field(body, field)
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise errors.validation(f"Field {field} must be a YYYY-MM-DD date")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise errors.validation(f"Field {field} must be a valid YYYY-MM-DD date")
    return v


def parse_dt(value, field):
    """Parse an ISO 8601 instant; naive values are treated as UTC."""
    if not isinstance(value, str) or not value:
        raise errors.validation(f"Field {field} must be an ISO 8601 datetime string")
    t = value
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        raise errors.validation(f"Field {field} must be an ISO 8601 datetime string")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def req_datetime(body, field):
    """Returns (raw_string, parsed_datetime)."""
    raw = req_field(body, field)
    return raw, parse_dt(raw, field)


def pagination_params():
    """limit: default 10, min 1, max 100; offset: default 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.validation("limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise errors.validation("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.validation("offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise errors.validation("offset must be >= 0")
    return limit, offset


def list_response(kind, filters):
    """Filter, order (created_at ASC, creation sequence tie-break), paginate."""
    from db import all_of, pub
    from response import ok_list

    limit, offset = pagination_params()
    items = []
    for rec in all_of(kind):
        if all(rec.get(k) == v for k, v in filters.items() if v is not None):
            items.append(rec)
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([pub(r) for r in page], total, limit, offset)


def require_version(body, field, current, stale_error):
    """OCC: the expected-version field is non-optional (schema) and must match (412)."""
    v = req_field(body, field)
    if not _is_int(v):
        raise errors.validation(f"Field {field} must be an integer")
    if v != current:
        raise stale_error()
    return v
