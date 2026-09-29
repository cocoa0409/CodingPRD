"""Request pipeline: envelope, authentication, field validation, pagination.

Enforces rejection-precedence steps 1 through 10 of PRD 2.7. Steps 11 onwards
are endpoint-specific and live in the route modules, executed in ascending
priority order there.
"""
import json

from flask import jsonify, request

import store
from errors import fail
from util import new_request_id, parse_dt, pub, wall_now_iso

ROLES = (
    "ClubAdmin",
    "RegattaChair",
    "Measurer",
    "RaceOfficer",
    "JuryChair",
    "Competitor",
)

MEMBER_BACKED = ("RegattaChair", "Measurer", "RaceOfficer", "JuryChair", "Competitor")


# --------------------------------------------------------------------------
# response envelope (PRD 2.2)
# --------------------------------------------------------------------------


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_row(row, code=200):
    return ok(pub(row), code)


def ok_list(rows, limit, offset, total_count):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(rows)) < total_count,
        }
    )
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


# --------------------------------------------------------------------------
# steps 1-3: headers, actor resolution, endpoint role list
# --------------------------------------------------------------------------


class Ctx(object):
    def __init__(self, roles, actor_exempt=False):
        role = request.headers.get("X-User-Role")
        user_id = request.headers.get("X-User-ID")
        # 1. both headers present and the role is one of the six declared ones
        if not user_id or not role or role not in ROLES:
            fail("ERR_UNAUTHENTICATED")
        self.role = role
        self.user_id = user_id
        self.actor = None
        # 2. a member-backed X-User-ID resolves to a ClubMember row
        if role in MEMBER_BACKED and not actor_exempt:
            self.actor = store.get("club_members", user_id)
            if self.actor is None:
                fail("ERR_UNKNOWN_ACTOR")
        # 3. the acting role is listed against the endpoint
        if role not in roles:
            fail("ERR_FORBIDDEN_ROLE")
        self.raw = None

    # 4. measurer licence
    def require_license(self):
        if self.role == "Measurer":
            if not self.actor or self.actor.get("measurer_license_id") in (None, ""):
                fail("ERR_MEASURER_NOT_LICENSED")

    # 6. body shape
    def body(self):
        if self.raw is None:
            self.raw = _read_json()
        return self.raw

    def has(self, name):
        return name in self.body()

    def raw_value(self, name):
        return self.body().get(name)


def _read_json():
    data = request.get_data(cache=True)
    if data is None or len(data.strip()) == 0:
        return {}
    try:
        parsed = json.loads(data.decode("utf-8"))
    except Exception:
        fail("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return parsed


# --------------------------------------------------------------------------
# step 6: field specification
# --------------------------------------------------------------------------

MISSING = object()


class F(object):
    """One declared input field of an endpoint."""

    def __init__(
        self,
        name,
        kind,
        required=True,
        default=None,
        enum=None,
        gt=None,
        ge=None,
        lt=None,
        le=None,
        one_of=None,
        min_len=None,
        max_len=None,
        nonblank=False,
        contains=None,
        defer=False,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.gt = gt
        self.ge = ge
        self.lt = lt
        self.le = le
        self.one_of = one_of
        self.min_len = min_len
        self.max_len = max_len
        self.nonblank = nonblank
        self.contains = contains
        self.defer = defer

    def bad(self, why):
        fail("ERR_INVALID_REQUEST", "field '%s' %s" % (self.name, why))

    def coerce(self, value):
        kind = self.kind
        if kind == "string":
            if not isinstance(value, str):
                self.bad("must be a string")
            if self.nonblank and value.strip() == "":
                self.bad("must not be blank")
            if self.min_len is not None and len(value) < self.min_len:
                self.bad("is shorter than %d characters" % self.min_len)
            if self.max_len is not None and len(value) > self.max_len:
                self.bad("is longer than %d characters" % self.max_len)
            if self.contains is not None and self.contains not in value:
                self.bad("must contain %r" % self.contains)
            return value
        if kind == "enum":
            if not isinstance(value, str):
                self.bad("must be a string")
            if self.enum is not None and value not in self.enum:
                self.bad("must be one of %s" % ", ".join(self.enum))
            return value
        if kind == "integer":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                self.bad("must be an integer")
            if isinstance(value, float):
                if not value.is_integer():
                    self.bad("must be an integer")
                value = int(value)
            self._range(value)
            return value
        if kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                self.bad("must be a number")
            value = float(value)
            self._range(value)
            return value
        if kind == "boolean":
            if not isinstance(value, bool):
                self.bad("must be a boolean")
            return value
        if kind == "datetime":
            if not isinstance(value, str):
                self.bad("must be an ISO 8601 datetime string")
            try:
                parse_dt(value)
            except ValueError:
                self.bad("must be an ISO 8601 datetime string")
            return value
        if kind == "array":
            if not isinstance(value, list):
                self.bad("must be an array")
            return value
        if kind == "object":
            if not isinstance(value, dict):
                self.bad("must be an object")
            return value
        return value

    def _range(self, value):
        if self.defer:
            # range deferred to a later, more specific precedence step
            return
        if self.one_of is not None and value not in self.one_of:
            self.bad("must be one of %s" % ", ".join(str(v) for v in self.one_of))
        if self.gt is not None and not value > self.gt:
            self.bad("must be greater than %s" % (self.gt,))
        if self.ge is not None and not value >= self.ge:
            self.bad("must be >= %s" % (self.ge,))
        if self.lt is not None and not value < self.lt:
            self.bad("must be less than %s" % (self.lt,))
        if self.le is not None and not value <= self.le:
            self.bad("must be <= %s" % (self.le,))


def validate(ctx, spec):
    """Step 6. Returns a dict carrying every declared field (defaults applied)."""
    body = ctx.body()
    names = set(f.name for f in spec)
    for key in body.keys():
        if key not in names:
            fail("ERR_INVALID_REQUEST", "unknown field '%s'" % key)
    out = {}
    for f in spec:
        if f.name not in body or body[f.name] is None:
            if f.required:
                fail("ERR_INVALID_REQUEST", "field '%s' is required" % f.name)
            out[f.name] = f.default
            continue
        out[f.name] = f.coerce(body[f.name])
    return out


def no_body(ctx):
    """An endpoint that declares no input rejects any field."""
    validate(ctx, [])


# --------------------------------------------------------------------------
# step 7: pagination, plus the shared list-read implementation
# --------------------------------------------------------------------------


def _q_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        text = raw.strip()
        if text.startswith("+"):
            text = text[1:]
        negative = text.startswith("-")
        digits = text[1:] if negative else text
        if not digits.isdigit():
            raise ValueError(name)
        value = int(text)
    except (ValueError, AttributeError):
        fail("ERR_INVALID_PAGINATION", "%s must be an integer" % name)
    return value


def pagination():
    limit = _q_int("limit", 10)
    offset = _q_int("offset", 0)
    if limit < 1 or limit > 100:
        fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    if offset < 0:
        fail("ERR_INVALID_PAGINATION", "offset must not be negative")
    return limit, offset


def _match(row, field, raw):
    value = row.get(field)
    if isinstance(value, bool):
        return raw.strip().lower() == ("true" if value else "false")
    if value is None:
        return raw == "" or raw.lower() == "null"
    return str(value) == raw


def list_read(collection, filters):
    """Step 7 then the filtered, created_at-ascending page."""
    limit, offset = pagination()
    rows = store.rows(collection)
    for field in filters:
        raw = request.args.get(field)
        if raw is None:
            continue
        rows = [r for r in rows if _match(r, field, raw)]
    total = len(rows)
    page = rows[offset : offset + limit]
    return ok_list([pub(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# step 8: reference resolution
# --------------------------------------------------------------------------


def must(collection, row_id):
    row = store.get(collection, row_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no such %s: %s" % (collection, row_id))
    return row


def soft(collection, row_id):
    """Lenient lookup used by the acting-party step, which runs before step 8."""
    if not isinstance(row_id, str):
        return None
    return store.get(collection, row_id)
