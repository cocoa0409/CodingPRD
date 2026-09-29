"""Request pipeline primitives: envelope, auth, field validation, pagination.

Header names, envelope field names, pagination field names and error ids are all
taken from PRD sections 2.1 - 2.5 and SCAFFOLD `response_envelope`.
"""

import random
import re
import string
import uuid as _uuid
from datetime import datetime, timezone
from decimal import Decimal

from flask import g, jsonify, request

from errors import ApiError
from store import iso, now

ROLES = (
    "ProgramAdministrator",
    "PermitClerk",
    "AlarmCompanyOperator",
    "AlarmUser",
    "PoliceDispatchSupervisor",
    "FalseAlarmReviewOfficer",
    "HearingOfficer",
    "BillingClerk",
)

OPAQUE_ROLES = (
    "ProgramAdministrator",
    "PermitClerk",
    "PoliceDispatchSupervisor",
    "FalseAlarmReviewOfficer",
    "HearingOfficer",
    "BillingClerk",
)

HDR_USER = "X-User-ID"
HDR_ROLE = "X-User-Role"

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?[Zz]$"
)


class Instant(datetime):
    """A datetime that remembers the exact string the client supplied."""

    raw = None


def parse_instant(value):
    """Parse an RFC 3339 UTC instant with a trailing Z, else return None."""
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    if micro >= 1000000:
        micro = 999999
    try:
        out = Instant(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)), micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    out.raw = value
    return out


def plain(dt):
    if dt is None:
        return None
    return datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
                    dt.microsecond, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# envelope
# ---------------------------------------------------------------------------

def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        # Nothing in this program consults wall-clock time (PRD 2.9): the
        # envelope stamp reads the server-held logical clock as well.
        "api_request_timestamp": iso(now()),
    }


def _jsonable(value):
    if isinstance(value, datetime):
        raw = getattr(value, "raw", None)
        return raw if raw else iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict((k, _jsonable(v)) for k, v in value.items()
                    if not str(k).startswith("_"))
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def public(row):
    if row is None:
        return None
    return dict((k, _jsonable(v)) for k, v in row.items()
                if not str(k).startswith("_"))


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object",
            "data": public(data) if isinstance(data, dict) else (data or {})}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_raw(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array",
            "data": [public(r) for r in items]}
    return jsonify(body), 200


def error_response(exc):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": exc.error_id, "message": exc.message}}
    return jsonify(body), exc.http_status


# ---------------------------------------------------------------------------
# auth (rejection positions 1-3)
# ---------------------------------------------------------------------------

class Ctx(object):
    __slots__ = ("user_id", "role", "body")

    def __init__(self, user_id, role, body):
        self.user_id = user_id
        self.role = role
        self.body = body

    @property
    def is_opaque(self):
        return self.role in OPAQUE_ROLES


def _read_body():
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=True)
    except Exception:
        parsed = None
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def authenticate(allowed_roles):
    """Positions 1-3: headers, then role recognition, then endpoint membership."""
    user_id = request.headers.get(HDR_USER)
    role = request.headers.get(HDR_ROLE)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS",
                       "Both X-User-ID and X-User-Role headers are required.")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS",
                       "Both X-User-ID and X-User-Role headers are required.")
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE", "Unrecognized role '%s'." % role)
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "Role %s may not invoke this operation." % role)
    ctx = Ctx(user_id, role, _read_body())
    g.ctx = ctx
    return ctx


def check_owner(ctx, site_id=None, company_id=None):
    """Position 8. Opaque roles skip the check; unreachable owners skip too."""
    if ctx.role == "AlarmUser":
        if site_id is not None and ctx.user_id != site_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER",
                           "Acting user is not the premises of this resource.")
    elif ctx.role == "AlarmCompanyOperator":
        if company_id is not None and ctx.user_id != company_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER",
                           "Acting user is not the monitoring company of this resource.")


# ---------------------------------------------------------------------------
# field validation (rejection positions 4-5)
# ---------------------------------------------------------------------------

class F(object):
    """One declared input field, in declared order."""

    def __init__(self, name, kind, required=True, values=None, min=None,
                 max=None, nonempty=False):
        self.name = name
        self.kind = kind
        self.required = required
        self.values = values
        self.min = min
        self.max = max
        self.nonempty = nonempty


def _bad(name):
    return ApiError("ERR_INVALID_FIELD_VALUE",
                    "Field '%s' holds an invalid value." % name)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def _coerce(spec, value):
    kind = spec.kind
    name = spec.name
    if kind == "string":
        if not isinstance(value, str):
            raise _bad(name)
        if spec.nonempty and value.strip() == "":
            raise _bad(name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in spec.values:
            raise _bad(name)
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise _bad(name)
        return value
    if kind == "int":
        if not _is_int(value):
            raise _bad(name)
        lo = 0 if spec.min is None else spec.min
        if value < lo:
            raise _bad(name)
        if spec.max is not None and value > spec.max:
            raise _bad(name)
        return value
    if kind == "number":
        if not _is_num(value):
            raise _bad(name)
        lo = 0 if spec.min is None else spec.min
        if value < lo:
            raise _bad(name)
        if spec.max is not None and value > spec.max:
            raise _bad(name)
        return value
    if kind == "pct":
        if not _is_num(value):
            raise _bad(name)
        if value < 0 or value > 1:
            raise _bad(name)
        return value
    if kind == "ts":
        parsed = parse_instant(value)
        if parsed is None:
            raise _bad(name)
        return parsed
    if kind == "uuid":
        if not isinstance(value, str):
            raise _bad(name)
        try:
            _uuid.UUID(value)
        except Exception:
            raise _bad(name)
        return value
    if kind == "array":
        if not isinstance(value, list):
            raise _bad(name)
        if spec.nonempty and len(value) == 0:
            raise _bad(name)
        return value
    if kind == "object":
        if not isinstance(value, dict):
            raise _bad(name)
        if spec.nonempty and len(value) == 0:
            raise _bad(name)
        return value
    return value


def validate(body, fields):
    """Two passes in declared order: missing first (4), then malformed (5)."""
    if not isinstance(body, dict):
        body = {}
    for spec in fields:
        if spec.required:
            if spec.name not in body or body.get(spec.name) is None:
                raise ApiError("ERR_MISSING_REQUIRED_FIELD",
                               "Field '%s' is required." % spec.name)
    out = {}
    for spec in fields:
        if spec.name in body and body.get(spec.name) is not None:
            out[spec.name] = _coerce(spec, body[spec.name])
    return out


# ---------------------------------------------------------------------------
# pagination (rejection position 59 — always evaluated last)
# ---------------------------------------------------------------------------

def _int_arg(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        if re.match(r"^-?\d+$", raw.strip()) is None:
            raise ValueError
        return int(raw.strip())
    except Exception:
        raise ApiError("ERR_INVALID_PAGINATION",
                       "Query parameter '%s' must be an integer." % name)


def page_window(sortable_fields):
    page = _int_arg("page")
    per_page = _int_arg("per_page")
    if page is None:
        page = 1
    if per_page is None:
        per_page = 10
    if page < 1:
        raise ApiError("ERR_INVALID_PAGINATION", "page must be at or above 1.")
    if per_page < 1 or per_page > 100:
        raise ApiError("ERR_INVALID_PAGINATION",
                       "per_page must lie between 1 and 100 inclusive.")
    sort = request.args.get("sort") or request.args.get("sort_by")
    sort_field = None
    descending = False
    if sort:
        key = sort.strip()
        if key.startswith("-"):
            descending = True
            key = key[1:]
        if key not in sortable_fields:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "'%s' is not a declared field of this entity." % key)
        sort_field = key
    return per_page, per_page * (page - 1), sort_field, descending


def listing(rows_in, sortable_fields):
    """Apply sort key, window the result and emit the array envelope."""
    limit, offset, sort_field, descending = page_window(sortable_fields)
    items = list(rows_in)
    if sort_field:
        items.sort(key=lambda r: (r.get(sort_field) is None,
                                  _sortable(r.get(sort_field)),
                                  r.get("_seq", 0)),
                   reverse=descending)
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


def _sortable(v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return iso(v)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    if isinstance(v, str):
        return v
    return str(v)


def q(name):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v


def q_bool(name):
    v = q(name)
    if v is None:
        return None
    low = v.strip().lower()
    if low in ("true", "1", "yes"):
        return True
    if low in ("false", "0", "no"):
        return False
    return None


def q_instant(name):
    v = q(name)
    if v is None:
        return None
    return parse_instant(v)


def sortable_fields(row_template):
    return set(row_template)
