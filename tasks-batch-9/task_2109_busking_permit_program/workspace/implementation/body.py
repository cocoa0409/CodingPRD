"""Body well-formedness helpers (PRD section 2.6 rule 6, priority 45).

Keys outside an endpoint's declared input list are never read here, which is
how the specification's "silently ignored" rule is implemented: nothing in
this module ever inspects an undeclared key, so it can neither be honoured
nor raise.
"""
from errors import invalid_request
from utils import is_bool, is_int, is_str, parse_dt


class Body(object):
    def __init__(self, raw):
        self.raw = raw if isinstance(raw, dict) else {}

    def supplied(self, key):
        return key in self.raw and self.raw.get(key) is not None

    # ---------------------------------------------------------------- strings
    def req_str(self, key, max_len=None, min_len=1):
        value = self.raw.get(key)
        if not is_str(value) or len(value) < min_len:
            invalid_request("%s is required and must be a non-empty string" % key)
        if max_len is not None and len(value) > max_len:
            invalid_request("%s must be at most %d characters" % (key, max_len))
        return value

    def opt_str(self, key, default=None, max_len=None):
        if not self.supplied(key):
            return default
        return self.req_str(key, max_len=max_len)

    # --------------------------------------------------------------- integers
    def req_int(self, key, lo=None, hi=None):
        value = self.raw.get(key)
        if not is_int(value):
            invalid_request("%s is required and must be an integer" % key)
        if lo is not None and value < lo:
            invalid_request("%s must be at least %d" % (key, lo))
        if hi is not None and value > hi:
            invalid_request("%s must be at most %d" % (key, hi))
        return value

    def opt_int(self, key, default=None, lo=None, hi=None):
        if not self.supplied(key):
            return default
        return self.req_int(key, lo=lo, hi=hi)

    # --------------------------------------------------------------- booleans
    def req_bool(self, key):
        value = self.raw.get(key)
        if not is_bool(value):
            invalid_request("%s is required and must be a boolean" % key)
        return value

    def opt_bool(self, key, default=False):
        if not self.supplied(key):
            return default
        return self.req_bool(key)

    # ------------------------------------------------------------------ enums
    def req_enum(self, key, allowed):
        value = self.raw.get(key)
        if not is_str(value) or value not in allowed:
            invalid_request("%s must be one of %s" % (key, ", ".join(sorted(allowed))))
        return value

    def opt_enum(self, key, allowed, default=None):
        if not self.supplied(key):
            return default
        return self.req_enum(key, allowed)

    # -------------------------------------------------------------- datetimes
    def req_dt(self, key):
        parsed = parse_dt(self.raw.get(key))
        if parsed is None:
            invalid_request("%s is required and must be an ISO 8601 UTC instant" % key)
        return parsed

    def opt_dt(self, key, default=None):
        if not self.supplied(key):
            return default
        return self.req_dt(key)

    # ------------------------------------------------------------ identifiers
    def req_id(self, key):
        value = self.raw.get(key)
        if not is_str(value) or not value:
            invalid_request("%s is required" % key)
        return value

    def opt_id(self, key, default=None):
        if not self.supplied(key):
            return default
        return self.req_id(key)
