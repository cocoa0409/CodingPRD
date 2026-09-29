"""Request-shape validation (ladder precedence 40) and existence resolution
(precedence 30 for path segments, precedence 50 for body foreign keys)."""

from flask import request

from .errors import ApiError, bad_request, fail
from .errors import NOT_FOUND_ERROR
from .store import db
from .util import parse_date, parse_instant


def raw_body():
    """The JSON body as a dict. A non-object or unparseable payload is malformed."""
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad_request("The request body must be a JSON object.")
    return parsed


def no_body():
    """Endpoints that declare no input accept nothing at all."""
    payload = raw_body()
    if payload:
        bad_request("This endpoint accepts no request body fields.")
    return {}


class Body(object):
    """Validates a request body against an explicit allow-list of field names.

    Any field outside the allow-list is rejected, which is what makes unknown
    fields and computed/system fields (including a version field on an endpoint
    that declares none) ERR_INVALID_REQUEST.
    """

    def __init__(self, allowed):
        self.payload = raw_body()
        self.allowed = set(allowed)
        for key in self.payload.keys():
            if key not in self.allowed:
                bad_request("Unknown or non-writable field '%s'." % key)

    # -- helpers ---------------------------------------------------------------
    def has(self, name):
        return name in self.payload

    def raw(self, name, default=None):
        """The literal value the client sent, echoed back unchanged."""
        return self.payload.get(name, default)

    def _present(self, name, required):
        if name not in self.payload:
            if required:
                bad_request("Field '%s' is required." % name)
            return False
        return True

    def string(self, name, required=False, min_len=1, max_len=None,
               nullable=False, default=None, trim_check=True):
        if not self._present(name, required):
            return default
        value = self.payload[name]
        if value is None:
            if nullable:
                return None
            bad_request("Field '%s' must be a string." % name)
        if not isinstance(value, str):
            bad_request("Field '%s' must be a string." % name)
        if trim_check and min_len >= 1 and value.strip() == "":
            bad_request("Field '%s' must not be blank." % name)
        if min_len is not None and len(value) < min_len:
            bad_request("Field '%s' is shorter than %d characters." % (name, min_len))
        if max_len is not None and len(value) > max_len:
            bad_request("Field '%s' exceeds %d characters." % (name, max_len))
        return value

    def enum(self, name, members, required=False, default=None, nullable=False):
        if not self._present(name, required):
            return default
        value = self.payload[name]
        if value is None and nullable:
            return None
        if not isinstance(value, str) or value not in members:
            bad_request("Field '%s' must be one of: %s." % (name, ", ".join(members)))
        return value

    def integer(self, name, required=False, minimum=None, maximum=None,
                default=None, nullable=False):
        if not self._present(name, required):
            return default
        value = self.payload[name]
        if value is None and nullable:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            bad_request("Field '%s' must be an integer." % name)
        if minimum is not None and value < minimum:
            bad_request("Field '%s' must be at least %d." % (name, minimum))
        if maximum is not None and value > maximum:
            bad_request("Field '%s' must be at most %d." % (name, maximum))
        return value

    def boolean(self, name, required=False, default=None):
        if not self._present(name, required):
            return default
        value = self.payload[name]
        if not isinstance(value, bool):
            bad_request("Field '%s' must be a boolean." % name)
        return value

    def date(self, name, required=False, default=None, nullable=False):
        if not self._present(name, required):
            return default
        value = self.payload[name]
        if value is None and nullable:
            return None
        parsed = parse_date(value)
        if parsed is None:
            bad_request("Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)." % name)
        return parsed

    def instant(self, name, required=False, default=None, nullable=False):
        if not self._present(name, required):
            return default
        value = self.payload[name]
        if value is None and nullable:
            return None
        parsed = parse_instant(value)
        if parsed is None:
            bad_request("Field '%s' must be an ISO 8601 UTC instant." % name)
        return parsed

    def id_ref(self, name, required=False, nullable=False, default=None):
        """A foreign-key string; existence itself is checked at precedence 50."""
        if not self._present(name, required):
            return default
        value = self.payload[name]
        if value is None:
            if nullable:
                return None
            bad_request("Field '%s' must be a string identifier." % name)
        if not isinstance(value, str) or value.strip() == "":
            bad_request("Field '%s' must be a string identifier." % name)
        return value


# --- existence ----------------------------------------------------------------

def load_path(collection_name, row_id):
    """Precedence 30: path segments are resolved left to right."""
    row = db.collection(collection_name).get(row_id)
    if row is None:
        fail(NOT_FOUND_ERROR[collection_name],
             "No such %s." % collection_name.rstrip("s").replace("_", " "))
    return row


def load_fk(collection_name, row_id, optional=True):
    """Precedence 50: body foreign keys, resolved in field-declaration order."""
    if row_id is None:
        if optional:
            return None
        fail(NOT_FOUND_ERROR[collection_name], "A referenced record is required.")
    row = db.collection(collection_name).get(row_id)
    if row is None:
        fail(NOT_FOUND_ERROR[collection_name],
             "Referenced %s does not exist." % collection_name.rstrip("s").replace("_", " "))
    return row


def non_empty(value):
    return isinstance(value, str) and value.strip() != ""


def query_filter(name):
    """A raw query string filter value, or None when absent."""
    raw = request.args.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "":
        return None
    return raw


def apply_filters(items, names):
    """Apply the declared equality filters that are present on the query string."""
    for name in names:
        value = query_filter(name)
        if value is None:
            continue
        items = [row for row in items if row.get(name) == value]
    return items
