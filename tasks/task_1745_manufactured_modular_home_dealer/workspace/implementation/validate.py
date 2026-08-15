"""Field-shape validation (layer 33, ERR_VALIDATION 400) — deliberately run
LAST in each handler per PRD 2.8. Shape errors are accumulated; business
checks read cleaned values via .value() guarded by .ok()."""

from datetime import datetime, timezone

from errors import fail


def parse_dt(raw):
    """Parse an ISO 8601 datetime; naive values are treated as UTC."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Shape:
    def __init__(self, body):
        self.body = body if isinstance(body, dict) else {}
        self.errnames = set()
        self.values = {}
        self.message = None

    def _err(self, name, msg):
        self.errnames.add(name)
        self.values[name] = None
        if self.message is None:
            self.message = f"{name}: {msg}"

    def ok(self, name):
        return name in self.values and name not in self.errnames

    def value(self, name, default=None):
        return self.values.get(name, default)

    def req_str(self, name):
        v = self.body.get(name)
        if not isinstance(v, str) or v == "":
            self._err(name, "is required and must be a non-empty string")
        else:
            self.values[name] = v

    def opt_str(self, name):
        if name not in self.body or self.body[name] is None:
            self.values[name] = None
            return
        v = self.body[name]
        if not isinstance(v, str) or v == "":
            self._err(name, "must be a non-empty string")
        else:
            self.values[name] = v

    def _int(self, name, v, minimum):
        if isinstance(v, bool) or not isinstance(v, int):
            self._err(name, "must be an integer")
            return None
        if minimum is not None and v < minimum:
            self._err(name, f"must be >= {minimum}")
            return None
        return v

    def req_int(self, name, minimum=None):
        if name not in self.body:
            self._err(name, "is required")
            return
        v = self._int(name, self.body.get(name), minimum)
        if v is not None:
            self.values[name] = v

    def opt_int(self, name, minimum=None):
        if name not in self.body or self.body[name] is None:
            self.values[name] = None
            return
        v = self._int(name, self.body.get(name), minimum)
        if v is not None:
            self.values[name] = v

    def req_num(self, name, gt0=False):
        v = self.body.get(name)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            self._err(name, "must be a number")
            return
        if gt0 and not v > 0:
            self._err(name, "must be > 0")
            return
        self.values[name] = v

    def req_bool(self, name):
        v = self.body.get(name)
        if not isinstance(v, bool):
            self._err(name, "must be a boolean")
        else:
            self.values[name] = v

    def req_enum(self, name, allowed):
        v = self.body.get(name)
        if not isinstance(v, str) or v not in allowed:
            self._err(name, f"must be one of {', '.join(allowed)}")
        else:
            self.values[name] = v

    def req_dt(self, name):
        if name not in self.body:
            self._err(name, "is required")
            return
        dt = parse_dt(self.body.get(name))
        if dt is None:
            self._err(name, "must be an ISO 8601 datetime")
        else:
            self.values[name] = dt

    def raise_if_errors(self):
        if self.errnames:
            fail("ERR_VALIDATION", self.message or "request body failed validation")


def get_body():
    from flask import request

    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def pagination_params():
    """limit (default 10, min 1, max 100) and offset (default 0)."""
    from flask import request

    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        fail("ERR_VALIDATION", "limit and offset must be integers")
    if not (1 <= limit <= 100):
        fail("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset < 0:
        fail("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset
