"""Request-shape validation helpers (all failures are ERR_INVALID_REQUEST, 422)."""
from core import bad, parse_day, parse_instant

MISSING = object()


def body_of(request):
    """Lenient body parse. A non-object body behaves as an empty object so that
    the ladder's FK step (priority 7) can run before shape checks (priority 8)."""
    try:
        parsed = request.get_json(silent=True, force=True)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    return {}


def raw(body, field):
    return body.get(field, MISSING)


def present(body, field):
    return field in body and body[field] is not None


def req_present(body, field):
    if field not in body or body[field] is None:
        bad("ERR_INVALID_REQUEST", "field '%s' is required" % field)
    return body[field]


def as_string(value, field, max_length=None, allow_empty=False):
    if not isinstance(value, str):
        bad("ERR_INVALID_REQUEST", "field '%s' must be a string" % field)
    if not allow_empty and value.strip() == "":
        bad("ERR_INVALID_REQUEST", "field '%s' must be non-empty" % field)
    if max_length is not None and len(value) > max_length:
        bad("ERR_INVALID_REQUEST", "field '%s' exceeds %d characters" % (field, max_length))
    return value


def as_integer(value, field, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("ERR_INVALID_REQUEST", "field '%s' must be an integer" % field)
    if minimum is not None and value < minimum:
        bad("ERR_INVALID_REQUEST", "field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        bad("ERR_INVALID_REQUEST", "field '%s' must be <= %s" % (field, maximum))
    return value


def as_number(value, field, minimum=None, maximum=None, exclusive_min=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("ERR_INVALID_REQUEST", "field '%s' must be a number" % field)
    if exclusive_min is not None and not value > exclusive_min:
        bad("ERR_INVALID_REQUEST", "field '%s' must be > %s" % (field, exclusive_min))
    if minimum is not None and value < minimum:
        bad("ERR_INVALID_REQUEST", "field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        bad("ERR_INVALID_REQUEST", "field '%s' must be <= %s" % (field, maximum))
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        bad("ERR_INVALID_REQUEST", "field '%s' must be a boolean" % field)
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        bad("ERR_INVALID_REQUEST", "field '%s' must be one of %s" % (field, sorted(allowed)))
    return value


def as_instant(value, field):
    try:
        return parse_instant(value)
    except Exception:
        bad("ERR_INVALID_REQUEST", "field '%s' must be an ISO-8601 UTC instant" % field)


def as_day(value, field):
    try:
        return parse_day(value)
    except Exception:
        bad("ERR_INVALID_REQUEST", "field '%s' must be a YYYY-MM-DD date" % field)


# --------------------------------------------------------------- optional readers

def opt_string(body, field, max_length=None, default=None, allow_empty=False):
    if not present(body, field):
        return default
    return as_string(body[field], field, max_length, allow_empty)


def opt_bool(body, field, default):
    if not present(body, field):
        return default
    return as_bool(body[field], field)


def opt_integer(body, field, default, minimum=None, maximum=None):
    if not present(body, field):
        return default
    return as_integer(body[field], field, minimum, maximum)


def opt_number(body, field, default, minimum=None, maximum=None):
    if not present(body, field):
        return default
    return as_number(body[field], field, minimum, maximum)


# --------------------------------------------------------------- pagination

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 200
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


def _page_int(args, name, default):
    if name not in args:
        return default
    text = args.get(name)
    if text is None or str(text).strip() == "":
        bad("ERR_INVALID_PAGINATION", "'%s' must be an integer" % name)
    text = str(text).strip()
    try:
        value = int(text, 10)
    except ValueError:
        bad("ERR_INVALID_PAGINATION", "'%s' must be an integer" % name)
    return value


def pagination(args):
    limit = _page_int(args, "limit", PAGE_LIMIT_DEFAULT)
    offset = _page_int(args, "offset", PAGE_OFFSET_DEFAULT)
    if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        bad("ERR_INVALID_PAGINATION", "'limit' must be between 1 and 200")
    if offset < PAGE_OFFSET_MIN:
        bad("ERR_INVALID_PAGINATION", "'offset' must be >= 0")
    return limit, offset


def bool_filter(args, name):
    if name not in args:
        return None
    text = str(args.get(name)).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    bad("ERR_INVALID_REQUEST", "'%s' must be true or false" % name)


def enum_filter(args, name, allowed):
    if name not in args:
        return None
    text = args.get(name)
    if text not in allowed:
        bad("ERR_INVALID_REQUEST", "'%s' must be one of %s" % (name, sorted(allowed)))
    return text


def str_filter(args, name):
    if name not in args:
        return None
    text = args.get(name)
    if text is None or str(text).strip() == "":
        return None
    return str(text)
