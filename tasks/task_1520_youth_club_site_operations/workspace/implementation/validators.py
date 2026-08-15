"""Request-body well-formedness (pipeline stage 4) and pagination parsing."""

import re
from datetime import date as date_cls
from datetime import datetime

from flask import request

from errors import validation


def get_body(allow_empty=False):
    body = request.get_json(silent=True)
    if body is None:
        if allow_empty:
            return {}
        raise validation("request body must be a JSON object")
    if not isinstance(body, dict):
        raise validation("request body must be a JSON object")
    return body


def reject_unknown(body, allowed):
    for key in body:
        if key not in allowed:
            raise validation("unknown field: %s" % key)


def _type_ok(value, typ):
    if typ == "string":
        return isinstance(value, str)
    if typ == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if typ == "number":
        return (isinstance(value, (int, float)) and not isinstance(value, bool))
    if typ == "boolean":
        return isinstance(value, bool)
    if typ == "object":
        return isinstance(value, dict)
    return True


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def valid_date_str(v):
    return isinstance(v, str) and bool(_DATE_RE.match(v)) and _parseable_date(v)


def _parseable_date(v):
    try:
        date_cls.fromisoformat(v)
        return True
    except ValueError:
        return False


def valid_month_str(v):
    if not (isinstance(v, str) and _MONTH_RE.match(v)):
        return False
    month = int(v[5:7])
    return 1 <= month <= 12


def valid_datetime_str(v):
    if not isinstance(v, str):
        return False
    s = v[:-1] + "+00:00" if v.endswith("Z") else v
    try:
        datetime.fromisoformat(s)
        return True
    except ValueError:
        return False


def require_fields(body, spec):
    """spec: {field: (type, required, {enum: [...], positive: bool, date/datetime/month: True, allow_null: bool})}

    On missing required field or type/enum/positivity/format violation -> ERR_VALIDATION.
    Returns dict of coerced values for the fields present.
    """
    out = {}
    for name, rule in spec.items():
        typ = rule.get("type", "string")
        required = rule.get("required", False)
        present = name in body
        if not present or (body.get(name) is None and not rule.get("allow_null")):
            if present and body.get(name) is None and required and not rule.get("allow_null"):
                raise validation("field %s may not be null" % name)
            if not present and required:
                raise validation("missing required field: %s" % name)
            if present and body.get(name) is None and rule.get("allow_null"):
                out[name] = None
            continue
        value = body[name]
        if not _type_ok(value, typ):
            raise validation("field %s has wrong type (expected %s)" % (name, typ))
        if rule.get("date") and not valid_date_str(value):
            raise validation("field %s must be a YYYY-MM-DD date" % name)
        if rule.get("month") and not valid_month_str(value):
            raise validation("field %s must be a YYYY-MM month" % name)
        if rule.get("datetime") and not valid_datetime_str(value):
            raise validation("field %s must be an ISO 8601 datetime" % name)
        if "enum" in rule and value not in rule["enum"]:
            raise validation("field %s must be one of %s" % (name, rule["enum"]))
        if rule.get("positive") and not (value > 0):
            raise validation("field %s must be positive" % name)
        if rule.get("nonnegative") and not (value >= 0):
            raise validation("field %s must be non-negative" % name)
        if "min" in rule and value < rule["min"]:
            raise validation("field %s is below its minimum" % name)
        if "max" in rule and value > rule["max"]:
            raise validation("field %s is above its maximum" % name)
        out[name] = value
    return out


def parse_pagination():
    """limit defaults to 10 (min 1, max 100), offset defaults to 0 (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise validation("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise validation("offset must be an integer")
        if offset < 0:
            raise validation("offset must be non-negative")
    return limit, offset


def paginate(records, limit, offset):
    """PRD §2.3: lists sorted by created_at ascending. Records are stored in
    creation order (db.all_records), so a stable sort by created_at alone keeps
    creation order for same-instant timestamps — sorting by the random UUID id
    on ties would scramble creation order whenever two records share a
    millisecond."""
    ordered = sorted(records, key=lambda r: (r.get("created_at") or ""))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
