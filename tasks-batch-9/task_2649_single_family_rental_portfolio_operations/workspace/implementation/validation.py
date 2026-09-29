"""Auth (PRD 2.1) and rank-10/12 payload validation (PRD 2.7)."""
import datetime
import re

from flask import request

import store
from errors import fail

ROLES = {
    "System",
    "PortfolioAdmin",
    "AcquisitionAnalyst",
    "InvestmentCommittee",
    "OperationsManager",
    "VendorManager",
    "Vendor",
    "LeasingAgent",
    "Prospect",
    "Anonymous",
    "ComplianceOfficer",
    "RegionalDirector",
}

ALL_ROLES = sorted(ROLES)

UTC = datetime.timezone.utc


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------


def role_header():
    return request.headers.get("X-User-Role")


def user_header():
    return request.headers.get("X-User-ID")


def authorize(allowed_roles, require_user=True):
    """Ranks 20, 30 and 40 in that order.  Returns (role, user_id)."""
    role = role_header()
    if role is None or role not in ROLES:
        fail("ERR_INVALID_ROLE")
    user_id = user_header()
    if require_user and (user_id is None or user_id == ""):
        fail("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    return role, (user_id or "")


# ---------------------------------------------------------------------------
# Value parsing
# ---------------------------------------------------------------------------

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date_value(text):
    if not isinstance(text, str) or not DATE_RE.match(text):
        raise ValueError("bad date")
    return datetime.datetime.strptime(text, "%Y-%m-%d").date()


def parse_instant_value(text):
    if not isinstance(text, str) or not text:
        raise ValueError("bad instant")
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


# ---------------------------------------------------------------------------
# Field descriptors
# ---------------------------------------------------------------------------


class F(object):
    def __init__(self, name, kind, required=True, default=None, enum=None,
                 minimum=None, maximum=None, pattern=None, item_kind=None,
                 item_fields=None, min_items=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.pattern = pattern
        self.item_kind = item_kind
        self.item_fields = item_fields
        self.min_items = min_items


def _bad(name, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def _check_scalar(field, value, name=None):
    name = name or field.name
    kind = field.kind
    if kind in ("int", "money", "count", "bps"):
        if not is_int(value):
            _bad(name, "must be an integer")
        if kind in ("money", "count") and value < 0:
            _bad(name, "may not be negative")
        if kind == "bps" and (value < 0 or value > 1000000):
            _bad(name, "must be between 0 and 1000000 basis points")
    elif kind == "number":
        if not is_number(value):
            _bad(name, "must be numeric")
        if value < 0:
            _bad(name, "may not be negative")
    elif kind == "bool":
        if not isinstance(value, bool):
            _bad(name, "must be a boolean")
    elif kind == "string":
        if not isinstance(value, str):
            _bad(name, "must be a string")
        if field.pattern and not re.match(field.pattern, value):
            _bad(name, "does not match the required format")
    elif kind == "date":
        try:
            parse_date_value(value)
        except Exception:
            _bad(name, "must be a valid YYYY-MM-DD date")
    elif kind == "datetime":
        try:
            parse_instant_value(value)
        except Exception:
            _bad(name, "must be a valid ISO 8601 instant")
    if field.enum is not None and value not in field.enum:
        _bad(name, "carries a value outside its declared set")
    if field.minimum is not None and is_number(value) and value < field.minimum:
        _bad(name, "is below its permitted minimum")
    if field.maximum is not None and is_number(value) and value > field.maximum:
        _bad(name, "is above its permitted maximum")
    return value


def validate(body, fields):
    """Rank 10 validation.  Returns a dict of parsed values with defaults."""
    if body is None:
        body = {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    out = {}
    for field in fields:
        present = field.name in body and body[field.name] is not None
        if not present:
            if field.required:
                _bad(field.name, "is required")
            out[field.name] = field.default
            continue
        value = body[field.name]
        if field.kind == "array":
            if not isinstance(value, list):
                _bad(field.name, "must be an array")
            if field.min_items is not None and len(value) < field.min_items:
                _bad(field.name, "must carry at least %d entries" % field.min_items)
            items = []
            for entry in value:
                if field.item_fields is not None:
                    if not isinstance(entry, dict):
                        _bad(field.name, "must be an array of objects")
                    items.append(validate(entry, field.item_fields))
                else:
                    sub = F(field.name, field.item_kind or "string")
                    items.append(_check_scalar(sub, entry))
            out[field.name] = items
            continue
        out[field.name] = _check_scalar(field, value)
    return out


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    return data


# ---------------------------------------------------------------------------
# Existence lookups
# ---------------------------------------------------------------------------


def must_find(collection, row_id, error_id):
    row = store.get(collection, row_id)
    if row is None:
        fail(error_id)
    return row


def query_filter(rows, param, field, transform=None):
    raw = request.args.get(param)
    if raw is None:
        return rows
    if transform is not None:
        raw = transform(raw)
    return [r for r in rows if r.get(field) == raw]


def bool_param(raw):
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Boolean query parameter must be true or false.")
