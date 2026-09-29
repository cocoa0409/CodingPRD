"""Request-shape validation (ladder step 3 -> ERR_INVALID_REQUEST, 400)."""
from datetime import datetime, timezone

from flask import request

from errors import ApiError

GRADE_BANDS = ("K_2", "G3_5", "G6_8", "G9_12")
CATEGORIES = ("WRITING", "PAPER", "BINDER", "HYGIENE", "BACKPACK")
SITE_TYPES = ("RETAIL", "CORPORATE", "SCHOOL", "LIBRARY")
CONDITIONS = ("NEW", "GENTLY_USED", "DAMAGED")
RESTRICTIONS = ("UNRESTRICTED", "ITEM_RESTRICTED", "SCHOOL_RESTRICTED")
VOLUNTEER_TYPES = ("SORTING", "ASSEMBLY")
CADENCES = ("BACK_TO_SCHOOL", "YEAR_ROUND")

SCHOOL_STATUSES = ("PROSPECT", "MOU_PENDING", "ACTIVE", "SUSPENDED", "ARCHIVED")
SPEC_STATUSES = ("DRAFT", "PUBLISHED", "RETIRED")
CYCLE_STATUSES = ("DRAFT", "COLLECTING", "SORTING", "DISTRIBUTION", "RECONCILED", "CLOSED")
SITE_OPERATIONAL_STATUSES = ("PENDING", "ACTIVE", "PAUSED", "CLOSED")
SITE_PLEDGE_STATUSES = ("NONE", "PLEDGED", "PLEDGE_ACTIVE", "FULFILLED", "LAPSED")
BATCH_STATUSES = ("RECEIVED", "INSPECTED", "ACCEPTED", "QUARANTINED", "REMEDIATED", "DISCARDED")
ORDER_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "RECEIVED", "CANCELLED")
VOLUNTEER_STATUSES = ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
EVENT_STATUSES = ("DRAFT", "PUBLISHED", "LOCKED", "CLOSED", "CANCELLED")
REGISTRATION_STATUSES = (
    "PENDING", "VERIFIED", "CONFIRMED", "WAITLISTED",
    "FULFILLED", "NO_SHOW", "REJECTED", "WITHDRAWN",
)
TEACHER_REQUEST_STATUSES = ("SUBMITTED", "APPROVED", "DENIED", "FULFILLED")
DONATION_STATUSES = ("RECEIVED", "PARTIALLY_ALLOCATED", "FULLY_ALLOCATED")


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def _present(data, key):
    return key in data and data[key] is not None


def req_str(data, key, min_len=1, max_len=None, non_blank=True):
    if not _present(data, key):
        bad("Missing required field '%s'." % key)
    value = data[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if non_blank and not value.strip():
        bad("Field '%s' must not be blank." % key)
    if len(value) < min_len:
        bad("Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is too long." % key)
    return value


def opt_str(data, key, default=None, min_len=1, max_len=None):
    if not _present(data, key):
        return default
    return req_str(data, key, min_len=min_len, max_len=max_len, non_blank=False)


def req_id(data, key):
    if not _present(data, key):
        bad("Missing required field '%s'." % key)
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be a non-empty string identifier." % key)
    return value


def opt_id(data, key):
    if not _present(data, key):
        return None
    return req_id(data, key)


def _as_int(value, key):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    return value


def req_int(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        bad("Missing required field '%s'." % key)
    value = _as_int(data[key], key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (key, maximum))
    return value


def opt_int(data, key, default=0, minimum=None, maximum=None):
    if not _present(data, key):
        return default
    return req_int(data, key, minimum=minimum, maximum=maximum)


def req_number(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        bad("Missing required field '%s'." % key)
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % key)
    value = float(value)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (key, maximum))
    return value


def req_bool(data, key):
    if not _present(data, key):
        bad("Missing required field '%s'." % key)
    if not isinstance(data[key], bool):
        bad("Field '%s' must be a boolean." % key)
    return data[key]


def opt_bool(data, key, default=False):
    if not _present(data, key):
        return default
    return req_bool(data, key)


def req_enum(data, key, allowed):
    value = req_str(data, key)
    if value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return req_enum(data, key, allowed)


def parse_dt(value, key):
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be an ISO 8601 datetime string." % key)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        bad("Field '%s' must be a parseable ISO 8601 datetime." % key)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_dt(data, key):
    if not _present(data, key):
        bad("Missing required field '%s'." % key)
    return parse_dt(data[key], key)


def req_window(data):
    start = req_dt(data, "window_start")
    end = req_dt(data, "window_end")
    if not start < end:
        bad("window_start must be strictly earlier than window_end.")
    return start, end


def target_status(data):
    """target_status must be present and a string (step 3); its membership in
    the entity's enumeration is judged at ladder step 9."""
    if not _present(data, "target_status"):
        bad("Missing required field 'target_status'.")
    value = data["target_status"]
    if not isinstance(value, str) or not value.strip():
        bad("Field 'target_status' must be a string.")
    return value


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            bad("limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            bad("limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            bad("offset must be a non-negative integer.")
        if offset < 0:
            bad("offset must be >= 0.")
    return limit, offset


def query_enum(key, allowed):
    value = request.args.get(key)
    if value is None or value == "":
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def query_id(key):
    value = request.args.get(key)
    if value is None or value == "":
        return None
    return value
