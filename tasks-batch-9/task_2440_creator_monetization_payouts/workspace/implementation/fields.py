"""Request-shape validation: PRD 2.9 band 2, in its five normative steps.

Step order inside the band is global across the whole payload:
  required -> type/enum/datetime -> numeric range -> free-text bounds.
"""
from datetime import datetime, timezone

from apierrors import fail

MISSING = object()
UTC = timezone.utc


class F(object):
    def __init__(self, name, kind, required=False, default=MISSING, enum=None,
                 minv=None, maxv=None, exclusive_min=None, text=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.minv = minv
        self.maxv = maxv
        self.exclusive_min = exclusive_min
        self.text = text


def parse_datetime(raw):
    """Parse an ISO 8601 UTC instant.  Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    if value.endswith("z") or value.endswith("Z"):
        value = value[:-1] + "+00:00"
    # normalise over-long fractional parts (fromisoformat accepts 3 or 6 digits)
    if "." in value:
        head, tail = value.split(".", 1)
        digits = ""
        for ch in tail:
            if ch.isdigit():
                digits += ch
            else:
                break
        rest = tail[len(digits):]
        if not digits:
            return None
        digits = (digits + "000000")[:6]
        value = head + "." + digits + rest
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def validate(body, specs):
    """Run the four steps of PRD 2.9 band 2 and return coerced values."""
    if not isinstance(body, dict):
        body = {}

    # step 1 - required presence
    for spec in specs:
        if spec.required:
            if spec.name not in body or body[spec.name] is None:
                fail("ERR_MISSING_REQUIRED_FIELD",
                     "Field '%s' is required." % spec.name)

    # step 2 - declared JSON types, enum membership, datetime parsing
    parsed = {}
    for spec in specs:
        if spec.name not in body or body[spec.name] is None:
            continue
        raw = body[spec.name]
        if spec.kind == "int":
            if not _is_int(raw):
                fail("ERR_INVALID_FIELD_VALUE",
                     "Field '%s' must be an integer." % spec.name)
            parsed[spec.name] = raw
        elif spec.kind == "bool":
            if not isinstance(raw, bool):
                fail("ERR_INVALID_FIELD_VALUE",
                     "Field '%s' must be a boolean." % spec.name)
            parsed[spec.name] = raw
        elif spec.kind == "str":
            if not isinstance(raw, str):
                fail("ERR_INVALID_FIELD_VALUE",
                     "Field '%s' must be a string." % spec.name)
            parsed[spec.name] = raw
        elif spec.kind == "enum":
            if not isinstance(raw, str) or raw not in (spec.enum or ()):
                fail("ERR_INVALID_FIELD_VALUE",
                     "Field '%s' must be one of %s." % (spec.name, ", ".join(spec.enum or ())))
            parsed[spec.name] = raw
        elif spec.kind == "datetime":
            value = parse_datetime(raw)
            if value is None:
                fail("ERR_INVALID_FIELD_VALUE",
                     "Field '%s' must be an ISO 8601 UTC datetime." % spec.name)
            parsed[spec.name] = value
        else:  # pragma: no cover - unknown kind
            parsed[spec.name] = raw

    # step 3 - numeric range constraints
    for spec in specs:
        if spec.name not in parsed or spec.kind != "int":
            continue
        value = parsed[spec.name]
        if spec.exclusive_min is not None and value <= spec.exclusive_min:
            fail("ERR_FIELD_OUT_OF_RANGE",
                 "Field '%s' must be greater than %s." % (spec.name, spec.exclusive_min))
        if spec.minv is not None and value < spec.minv:
            fail("ERR_FIELD_OUT_OF_RANGE",
                 "Field '%s' must be at least %s." % (spec.name, spec.minv))
        if spec.maxv is not None and value > spec.maxv:
            fail("ERR_FIELD_OUT_OF_RANGE",
                 "Field '%s' must be at most %s." % (spec.name, spec.maxv))

    # step 4 - free-text non-blankness and length bounds
    for spec in specs:
        if spec.name not in parsed or not spec.text:
            continue
        value = parsed[spec.name]
        lo, hi = spec.text
        if not value.strip() or len(value) < lo or len(value) > hi:
            fail("ERR_INVALID_FIELD_VALUE",
                 "Field '%s' must be non-blank and %s..%s characters." % (spec.name, lo, hi))

    data = {}
    for spec in specs:
        if spec.name in parsed:
            data[spec.name] = parsed[spec.name]
        elif spec.name in body and body[spec.name] is None:
            data[spec.name] = None
        elif spec.default is not MISSING:
            data[spec.name] = spec.default
    data["__supplied__"] = set(k for k in body.keys() if isinstance(k, str))
    return data


def parse_pagination(args):
    limit, offset = 10, 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not _int_str(raw):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer between 1 and 100.")
        limit = int(raw)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be an integer between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not _int_str(raw):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer of at least 0.")
        offset = int(raw)
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be an integer of at least 0.")
    return limit, offset


def _int_str(raw):
    text = raw.strip()
    if not text:
        return False
    if text[0] in "+-":
        text = text[1:]
    return text.isdigit()
