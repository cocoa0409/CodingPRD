"""Payload validation DSL. Malformed payloads -> ERR_INVALID_REQUEST (400):
missing required field, unknown field, invalid enum, bad window, out-of-range."""
import timeutil
from errors import raise_err, ERR_INVALID_REQUEST

MISSING = object()


class Field:
    def __init__(self, name, kind, required=False, default=MISSING, enum=None,
                 minv=None, maxv=None, allow_empty_str=True):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.minv = minv
        self.maxv = maxv
        self.allow_empty_str = allow_empty_str

    def convert(self, value):
        bad = lambda msg: raise_err(ERR_INVALID_REQUEST, "Field '%s': %s" % (self.name, msg))
        if value is None:
            bad("must not be null")
        k = self.kind
        if k == "str":
            if not isinstance(value, str):
                bad("must be a string")
            if not self.allow_empty_str and value.strip() == "":
                bad("must be non-empty")
            return value
        if k == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                bad("must be an integer")
            if self.minv is not None and value < self.minv:
                bad("out of range (min %s)" % self.minv)
            if self.maxv is not None and value > self.maxv:
                bad("out of range (max %s)" % self.maxv)
            return value
        if k == "bool":
            if not isinstance(value, bool):
                bad("must be a boolean")
            return value
        if k == "enum":
            if not isinstance(value, str) or value not in self.enum:
                bad("must be one of %s" % sorted(self.enum))
            return value
        if k == "date":
            d = timeutil.parse_date(value)
            if d is None:
                bad("must be an ISO date YYYY-MM-DD")
            return d
        if k == "dt":
            dt = timeutil.parse_dt(value)
            if dt is None:
                bad("must be an ISO 8601 datetime")
            return dt
        if k == "hm":
            mins = timeutil.parse_hm(value)
            if mins is None:
                bad("must be HH:MM 24h")
            return value  # keep original string; minutes derived on demand
        if k == "month":
            if timeutil.parse_month(value) is None:
                bad("must be YYYY-MM")
            return value
        if k == "list_str":
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                bad("must be an array of strings")
            if self.enum:
                for x in value:
                    if x not in self.enum:
                        bad("array values must be within %s" % sorted(self.enum))
            return list(value)
        if k == "items5":
            if (not isinstance(value, list) or len(value) != 5
                    or any(isinstance(x, bool) or not isinstance(x, int) or x < 1 or x > 5
                           for x in value)):
                bad("must be exactly 5 integers each 1..5")
            return list(value)
        raise AssertionError("unknown kind " + k)


def validate_payload(body, spec, partial=False):
    """Validate body against spec. When partial=True (PATCH), only present
    fields are validated and no required checks run. Returns cleaned dict."""
    if body is None:
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    allowed = {f.name for f in spec}
    for key in body:
        if key not in allowed:
            raise_err(ERR_INVALID_REQUEST, "Unknown field '%s'" % key)
    out = {}
    for f in spec:
        if f.name in body and body[f.name] is not None:
            out[f.name] = f.convert(body[f.name])
        elif not partial:
            if f.required:
                raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % f.name)
            if f.default is not MISSING:
                out[f.name] = f.default() if callable(f.default) else f.default
    return out


def parse_pagination(args):
    limit, offset = 10, 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (ValueError, TypeError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (ValueError, TypeError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def parse_bool_filter(args, name):
    if name not in args:
        return None
    v = args.get(name)
    if isinstance(v, str) and v.lower() == "true":
        return True
    if isinstance(v, str) and v.lower() == "false":
        return False
    raise_err(ERR_INVALID_REQUEST, "%s must be true or false" % name)


def sort_items(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
