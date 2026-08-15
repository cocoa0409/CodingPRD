"""Request-body validation helpers (rung: business_request -> ERR_INVALID_REQUEST)."""
from flask import request
from db import parse_dt, parse_date
from errors import invalid_request


def get_body():
    """Parse the JSON body; absent body -> {}; malformed JSON -> 400."""
    raw = request.get_data()
    if not raw:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


class Body:
    def __init__(self, data, allowed_fields):
        extra = set(data.keys()) - set(allowed_fields)
        if extra:
            raise invalid_request("Unknown fields: %s" % ", ".join(sorted(extra)))
        self.d = data

    def has(self, name):
        return name in self.d and self.d[name] is not None

    def present(self, name):
        return name in self.d

    def req_str(self, name):
        v = self.d.get(name)
        if not isinstance(v, str) or v == "":
            raise invalid_request("%s is required and must be a non-empty string" % name)
        return v

    def opt_str(self, name):
        v = self.d.get(name)
        if v is None:
            return None
        if not isinstance(v, str):
            raise invalid_request("%s must be a string" % name)
        return v

    def req_int(self, name):
        v = self.d.get(name)
        if not isinstance(v, int) or isinstance(v, bool):
            raise invalid_request("%s is required and must be an integer" % name)
        return v

    def opt_int(self, name):
        v = self.d.get(name)
        if v is None:
            return None
        if not isinstance(v, int) or isinstance(v, bool):
            raise invalid_request("%s must be an integer" % name)
        return v

    def req_bool(self, name):
        v = self.d.get(name)
        if not isinstance(v, bool):
            raise invalid_request("%s is required and must be a boolean" % name)
        return v

    def opt_bool(self, name):
        v = self.d.get(name)
        if v is None:
            return None
        if not isinstance(v, bool):
            raise invalid_request("%s must be a boolean" % name)
        return v

    def req_number(self, name):
        v = self.d.get(name)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise invalid_request("%s is required and must be a number" % name)
        return v

    def req_enum(self, name, values):
        v = self.d.get(name)
        if not isinstance(v, str) or v not in values:
            raise invalid_request("%s must be one of %s" % (name, ", ".join(values)))
        return v

    def req_date(self, name):
        v = self.d.get(name)
        if not isinstance(v, str):
            raise invalid_request("%s must be a YYYY-MM-DD date string" % name)
        try:
            parse_date(v)
        except (ValueError, TypeError):
            raise invalid_request("%s must be a valid YYYY-MM-DD date" % name)
        return v

    def req_datetime(self, name):
        v = self.d.get(name)
        if not isinstance(v, str):
            raise invalid_request("%s must be an ISO8601 datetime string" % name)
        try:
            parse_dt(v)
        except (ValueError, TypeError):
            raise invalid_request("%s must be a valid ISO8601 datetime" % name)
        return v
