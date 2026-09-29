"""Request-shape validation (PRD 2.5 band 8) and pagination (PRD 2.3)."""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def parse_iso8601(value, field):
    """Parse an ISO-8601 UTC timestamp.  Returns an aware datetime in UTC."""
    if not isinstance(value, str) or not value.strip():
        raise bad("%s must be an ISO 8601 UTC timestamp." % field)
    m = _TS_RE.match(value.strip())
    if not m:
        raise bad("%s is not a valid ISO 8601 UTC timestamp." % field)
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour = int(m.group(4) or 0)
    minute = int(m.group(5) or 0)
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        raise bad("%s is not a valid ISO 8601 UTC timestamp." % field)
    if offset in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if offset[0] == "+" else -1
    off = offset[1:].replace(":", "")
    delta_minutes = sign * (int(off[:2]) * 60 + int(off[2:4]))
    from datetime import timedelta

    return (naive - timedelta(minutes=delta_minutes)).replace(tzinfo=timezone.utc)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def json_body():
    if request.data and request.data.strip():
        try:
            body = request.get_json(force=True, silent=False)
        except Exception:
            raise bad("Request body is not valid JSON.")
    else:
        body = {}
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise bad("Request body must be a JSON object.")
    return body


def precheck_fks(pairs):
    """Validation band 4: body foreign keys resolve, in declared input order.

    ``pairs`` is an ordered sequence of ``(field_name, collection_dict)``.
    Absent or malformed values are left to the band-8 shape check.
    """
    body = json_body()
    for name, collection in pairs:
        value = body.get(name)
        if not isinstance(value, str) or not value.strip():
            continue
        if value not in collection:
            raise ApiError("ERR_NOT_FOUND")


def validate(spec):
    """Validate the JSON body against ``spec``.

    ``spec`` is an ordered list of dicts:
        name, type, required (bool), and per-type extras
        (values, min, max, default).
    Returns a dict of coerced values.  Datetime fields yield a dict
    {"raw": <original string>, "dt": <datetime>}.
    """
    body = json_body()
    known = set(item["name"] for item in spec)
    for key in body:
        if key not in known:
            raise bad("Unknown field '%s'." % key)

    out = {}
    for item in spec:
        name = item["name"]
        kind = item["type"]
        present = name in body and body[name] is not None
        if not present:
            if item.get("required"):
                raise bad("Field '%s' is required." % name)
            out[name] = item.get("default")
            continue
        value = body[name]

        if kind == "string":
            if not isinstance(value, str) or not value.strip():
                raise bad("Field '%s' must be a non-empty string." % name)
            out[name] = value
        elif kind == "bool":
            if not isinstance(value, bool):
                raise bad("Field '%s' must be a boolean." % name)
            out[name] = value
        elif kind in ("int", "money"):
            if not _is_int(value):
                raise bad("Field '%s' must be an integer." % name)
            if value < 0:
                raise bad("Field '%s' may not be negative." % name)
            if "min" in item and value < item["min"]:
                raise bad("Field '%s' must be at least %s." % (name, item["min"]))
            if "max" in item and value > item["max"]:
                raise bad("Field '%s' may not exceed %s." % (name, item["max"]))
            out[name] = value
        elif kind == "enum":
            if not isinstance(value, str) or value not in item["values"]:
                raise bad("Field '%s' must be one of %s." % (name, ", ".join(item["values"])))
            out[name] = value
        elif kind == "datetime":
            from db import fmt_ms

            parsed = parse_iso8601(value, name)
            out[name] = {"raw": fmt_ms(parsed), "dt": parsed}
        elif kind == "decimal":
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise bad("Field '%s' must be a number." % name)
            try:
                dec = Decimal(str(value))
            except (InvalidOperation, ValueError):
                raise bad("Field '%s' must be a number." % name)
            if dec != dec:  # NaN guard
                raise bad("Field '%s' must be a number." % name)
            if "min" in item and dec < Decimal(str(item["min"])):
                raise bad("Field '%s' must be at least %s." % (name, item["min"]))
            if "max" in item and dec > Decimal(str(item["max"])):
                raise bad("Field '%s' may not exceed %s." % (name, item["max"]))
            out[name] = dec
        elif kind == "id":
            if not isinstance(value, str) or not value.strip():
                raise bad("Field '%s' must be a non-empty identifier." % name)
            out[name] = value
        else:  # pragma: no cover - defensive
            raise bad("Field '%s' has an unsupported type." % name)
    return out


def pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_v = 10
    else:
        if not re.match(r"^-?\d+$", limit.strip()):
            raise bad("limit must be an integer.")
        limit_v = int(limit)
        if limit_v < 1 or limit_v > 100:
            raise bad("limit must be between 1 and 100.")
    if offset is None or offset == "":
        offset_v = 0
    else:
        if not re.match(r"^-?\d+$", offset.strip()):
            raise bad("offset must be an integer.")
        offset_v = int(offset)
        if offset_v < 0:
            raise bad("offset may not be negative.")
    return limit_v, offset_v


def enum_query(name, values, required=False):
    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            raise bad("Query parameter '%s' is required." % name)
        return None
    if raw not in values:
        raise bad("Query parameter '%s' must be one of %s." % (name, ", ".join(values)))
    return raw


def int_query(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if not re.match(r"^-?\d+$", raw.strip()):
        raise bad("Query parameter '%s' must be an integer." % name)
    return int(raw)
