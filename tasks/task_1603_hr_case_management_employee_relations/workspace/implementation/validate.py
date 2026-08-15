"""Deferred syntactic validation (validation priority 24 — the FINAL screen).

PRD §2.6: syntactic validity (required fields present, values well-typed, enum
values in declared sets -> ERR_INVALID_REQUEST, HTTP 400) is the last screen of
all. Handlers therefore collect syntactic problems in a Payload while running
the higher-priority layers first, then call raise_if_errors() at the end.
"""
from errors import raise_error, ERR_INVALID_REQUEST
from util import parse_dt


class Payload:
    def __init__(self, raw):
        self.raw = raw if isinstance(raw, dict) else {}
        self.errors = []

    def _absent(self, field, required):
        if required:
            self.errors.append(f"{field} is required")
        return None

    def present(self, field) -> bool:
        return field in self.raw and self.raw[field] is not None

    def get_str(self, field, required=False):
        if not self.present(field):
            return self._absent(field, required)
        v = self.raw[field]
        if not isinstance(v, str):
            self.errors.append(f"{field} must be a string")
            return None
        return v

    def get_bool(self, field, required=False):
        if not self.present(field):
            return self._absent(field, required)
        v = self.raw[field]
        if not isinstance(v, bool):
            self.errors.append(f"{field} must be a boolean")
            return None
        return v

    def get_int(self, field, required=False, minimum=None, maximum=None):
        if not self.present(field):
            return self._absent(field, required)
        v = self.raw[field]
        if isinstance(v, bool):
            self.errors.append(f"{field} must be an integer")
            return None
        if isinstance(v, str) and v.strip().lstrip("-").isdigit():
            v = int(v.strip())
        if not isinstance(v, int):
            self.errors.append(f"{field} must be an integer")
            return None
        if minimum is not None and v < minimum:
            self.errors.append(f"{field} must be >= {minimum}")
            return None
        if maximum is not None and v > maximum:
            self.errors.append(f"{field} must be <= {maximum}")
            return None
        return v

    def get_num(self, field, required=False):
        if not self.present(field):
            return self._absent(field, required)
        v = self.raw[field]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            self.errors.append(f"{field} must be a number")
            return None
        return v

    def get_enum(self, field, choices, required=False):
        if not self.present(field):
            return self._absent(field, required)
        v = self.raw[field]
        if not isinstance(v, str) or v not in choices:
            self.errors.append(f"{field} must be one of {sorted(choices)}")
            return None
        return v

    def get_dt(self, field, required=False):
        if not self.present(field):
            return self._absent(field, required)
        try:
            return parse_dt(self.raw[field])
        except (ValueError, TypeError):
            self.errors.append(f"{field} must be an ISO 8601 datetime")
            return None

    def get_list_of_str(self, field, required=False):
        if not self.present(field):
            return self._absent(field, required)
        v = self.raw[field]
        if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
            self.errors.append(f"{field} must be an array of strings")
            return None
        return v

    def raise_if_errors(self):
        if self.errors:
            raise_error(ERR_INVALID_REQUEST, "; ".join(self.errors))
