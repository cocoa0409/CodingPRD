"""Request body / query-string validation (PRD section 2.7, priority 4)."""
import re

from clock import parse_date, parse_datetime
from errors import ApiError

_UPPER2 = re.compile(r"^[A-Z]{2}$")


def bad(message="The request body or query string is invalid."):
    return ApiError("ERR_INVALID_REQUEST", message)


# ---------------------------------------------------------------- checkers

def v_str(max_len=None, allow_empty=False):
    def check(value, name):
        if not isinstance(value, str):
            raise bad("%s must be a string." % name)
        if not allow_empty and value.strip() == "":
            raise bad("%s must not be empty." % name)
        if max_len is not None and len(value) > max_len:
            raise bad("%s must be at most %d characters." % (name, max_len))
        return value
    return check


def v_text():
    """Free text with no declared maximum; empty string tolerated."""
    return v_str(max_len=None, allow_empty=True)


def v_state_code():
    def check(value, name):
        if not isinstance(value, str) or not _UPPER2.match(value):
            raise bad("%s must be exactly two uppercase letters." % name)
        return value
    return check


def v_enum(values):
    def check(value, name):
        if not isinstance(value, str) or value not in values:
            raise bad("%s must be one of %s." % (name, ", ".join(sorted(values))))
        return value
    return check


def v_int(minimum=None, maximum=None):
    def check(value, name):
        if isinstance(value, bool) or not isinstance(value, int):
            raise bad("%s must be an integer." % name)
        if minimum is not None and value < minimum:
            raise bad("%s must be at least %d." % (name, minimum))
        if maximum is not None and value > maximum:
            raise bad("%s must be at most %d." % (name, maximum))
        return value
    return check


def v_bool():
    def check(value, name):
        if not isinstance(value, bool):
            raise bad("%s must be a boolean." % name)
        return value
    return check


def v_date():
    def check(value, name):
        try:
            parse_date(value)
        except ValueError:
            raise bad("%s must be an ISO 8601 calendar date (YYYY-MM-DD)." % name)
        return value
    return check


def v_datetime():
    def check(value, name):
        try:
            parse_datetime(value)
        except ValueError:
            raise bad("%s must be an ISO 8601 UTC timestamp." % name)
        return value
    return check


def v_id():
    return v_str(max_len=200)


# ---------------------------------------------------------------- body

def parse_body(request):
    if not request.data or not request.data.strip():
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise bad("The request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise bad("The request body must be a JSON object.")
    return payload


def validate(payload, required=None, optional=None, ignore=()):
    """Validate a JSON object against a field spec.

    required / optional map a field name to a checker. An explicit null on an
    optional field is treated exactly like an absent field. Any field that is
    neither declared nor listed in `ignore` is an unknown field and rejected.
    """
    required = required or {}
    optional = optional or {}
    known = set(required) | set(optional) | set(ignore)
    for key in payload:
        if key not in known:
            raise bad("Unknown field '%s'." % key)
    out = {}
    for name, check in required.items():
        if name not in payload or payload[name] is None:
            raise bad("%s is required." % name)
        out[name] = check(payload[name], name)
    for name, check in optional.items():
        if name in payload and payload[name] is not None:
            out[name] = check(payload[name], name)
    return out


# ---------------------------------------------------------------- query

def pagination(args):
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if not re.match(r"^-?\d+$", raw or ""):
            raise bad("limit must be an integer.")
        limit = int(raw)
        if limit < 1 or limit > 100:
            raise bad("limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        if not re.match(r"^-?\d+$", raw or ""):
            raise bad("offset must be an integer.")
        offset = int(raw)
        if offset < 0:
            raise bad("offset must be zero or greater.")
    return limit, offset


def apply_filters(records, args, spec):
    """spec maps a query parameter name to the record field it filters on."""
    out = records
    for param, field in spec.items():
        if param in args:
            wanted = args.get(param)
            out = [r for r in out if _as_text(r.get(field)) == wanted]
    return out


def _as_text(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
