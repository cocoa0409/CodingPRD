"""Field-level input validation helpers (ERR_INVALID_REQUEST, PRD §3)."""
import errors

TRACKS = {"GENERAL", "ACADEMIC", "BUSINESS", "EXAM_PREP"}
LEVELS = {"A1", "A2", "B1", "B2", "C1", "C2"}
SCHEDULE_BLOCKS = {"MORNING", "AFTERNOON", "EVENING"}
DISCOUNT_TIERS = {"BRONZE", "SILVER", "GOLD"}
ADD_ON_TYPES = {"CONVERSATION_CLUB", "PRIVATE_TUTORING", "IMMERSION_ABROAD"}
ATTENDANCE_STATUSES = {"PRESENT", "ABSENT", "EXCUSED"}
TERMINATION_REASONS = {"VISA_NONCOMPLIANCE", "ATTENDANCE_FAILURE", "CONTRACT_REVOKED"}
VISA_STATUSES = {"NONE", "INITIAL", "ACTIVE", "PROBATION", "TERMINATED"}


def invalid(msg):
    return errors.err(errors.ERR_INVALID_REQUEST, msg)


def body(req):
    """Return the parsed JSON body as a dict, or {} for an empty body."""
    data = req.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid("Request body must be a JSON object")
    return data


def require_str(data, field):
    val = data.get(field)
    if not isinstance(val, str) or val == "":
        raise invalid(f"Field '{field}' is required and must be a non-empty string")
    return val


def optional_str(data, field, default=None):
    if field not in data or data.get(field) is None:
        return default
    val = data.get(field)
    if not isinstance(val, str):
        raise invalid(f"Field '{field}' must be a string")
    return val


def require_int(data, field, minimum=None, maximum=None):
    val = data.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise invalid(f"Field '{field}' is required and must be an integer")
    if minimum is not None and val < minimum:
        raise invalid(f"Field '{field}' must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise invalid(f"Field '{field}' must be <= {maximum}")
    return val


def optional_bool(data, field, default=False):
    if field not in data or data.get(field) is None:
        return default
    val = data.get(field)
    if not isinstance(val, bool):
        raise invalid(f"Field '{field}' must be a boolean")
    return val


def require_enum(data, field, allowed):
    val = data.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise invalid(f"Field '{field}' must be one of {sorted(allowed)}")
    return val


def optional_enum(data, field, allowed, default):
    if field not in data or data.get(field) is None:
        return default
    return require_enum(data, field, allowed)


def require_datetime(data, field):
    """Validate a datetime input field; stored as the original ISO string."""
    from clock import _parse_iso

    val = data.get(field)
    if not isinstance(val, str) or val == "":
        raise invalid(f"Field '{field}' is required and must be an ISO 8601 string")
    try:
        _parse_iso(val)
    except Exception:
        raise invalid(f"Field '{field}' must be a valid ISO 8601 datetime")
    return val
