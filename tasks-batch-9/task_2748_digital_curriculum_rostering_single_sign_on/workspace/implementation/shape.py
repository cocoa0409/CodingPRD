"""Request-shape screening (ladder rung 6) and query-parameter handling."""
from flask import request

import store
from errors import ApiError

ROLES = [
    "RosterOperator",
    "DataGovernanceOfficer",
    "VendorIntegrationManager",
    "BuildingLicenseAdmin",
    "IdentityAdmin",
]

GRADE_BANDS = ["ELEMENTARY", "MIDDLE", "HIGH"]
MEETING_DAYS = ["MON", "TUE", "WED", "THU", "FRI"]
SUBJECTS = ["MATH", "ELA", "SCIENCE", "SOCIAL_STUDIES", "ELECTIVE"]
ROSTERING_STANDARDS = ["ONEROSTER_CSV_1P1", "ONEROSTER_REST_1P2", "VENDOR_NATIVE_JSON"]
IDENTIFIER_STRATEGIES = ["SIS_ID", "EMAIL_LOCALPART", "STATE_ID"]
NAME_FORMATS = ["LAST_FIRST", "FIRST_LAST"]
SEAT_MODELS = ["PER_STUDENT", "PER_STUDENT_AND_TEACHER"]
ALLOCATION_POLICIES = ["PROPORTIONAL_HEADCOUNT", "FIXED_BUILDING_BLOCKS"]
OVERAGE_POLICIES = ["BLOCK", "POOL_FALLBACK"]
UNMATCHED_TEACHER_POLICIES = ["HOLD_RUN", "SKIP_SECTION"]
RUN_TYPES = ["FULL", "DELTA", "ROLLOVER"]
SUBJECT_TYPES = ["STUDENT", "TEACHER"]
ENROLLMENT_SOURCES = ["SIS_EXTRACT", "MANUAL"]


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def body():
    """Parsed JSON object body; malformed JSON is a shape failure."""
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def present(data, field):
    return field in data and data[field] is not None


def req_str(data, field, min_len=1, max_len=None):
    if not present(data, field):
        bad("%s is required." % field)
    value = data[field]
    if not isinstance(value, str):
        bad("%s must be a string." % field)
    if len(value) < min_len:
        bad("%s is too short." % field)
    if max_len is not None and len(value) > max_len:
        bad("%s is too long." % field)
    return value


def opt_str(data, field, default=None, min_len=1, max_len=None):
    if not present(data, field):
        return default
    return req_str(data, field, min_len, max_len)


def req_int(data, field, minimum=None, maximum=None):
    if not present(data, field):
        bad("%s is required." % field)
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("%s is below its minimum." % field)
    if maximum is not None and value > maximum:
        bad("%s is above its maximum." % field)
    return value


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if not present(data, field):
        return default
    return req_int(data, field, minimum, maximum)


def req_bool(data, field):
    if not present(data, field):
        bad("%s is required." % field)
    if not isinstance(data[field], bool):
        bad("%s must be a boolean." % field)
    return data[field]


def opt_bool(data, field, default=None):
    if not present(data, field):
        return default
    return req_bool(data, field)


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        bad("%s must be one of %s." % (field, ", ".join(allowed)))
    return value


def opt_enum(data, field, allowed, default=None):
    if not present(data, field):
        return default
    return req_enum(data, field, allowed)


def req_date(data, field):
    value = req_str(data, field)
    parsed = store.parse_date(value)
    if parsed is None:
        bad("%s must be an ISO-8601 calendar date." % field)
    return parsed


def opt_date(data, field, default=None):
    if not present(data, field):
        return default
    return req_date(data, field)


def req_instant(data, field):
    value = req_str(data, field)
    parsed = store.parse_instant(value)
    if parsed is None:
        bad("%s must be an ISO-8601 UTC instant." % field)
    return parsed


def req_enum_array(data, field, allowed):
    if not present(data, field):
        bad("%s is required." % field)
    value = data[field]
    if not isinstance(value, list) or len(value) == 0:
        bad("%s must be a non-empty array." % field)
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad("%s contains an unknown value." % field)
        if item in seen:
            bad("%s contains duplicates." % field)
        seen.add(item)
    return list(value)


def req_id(data, field):
    return req_str(data, field)


def opt_id(data, field, default=None):
    if not present(data, field):
        return default
    return req_str(data, field)


# --------------------------------------------------------------------------
# Pagination and filters
# --------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("limit must be an integer.")
        if limit < 1 or limit > 100:
            bad("limit must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("offset must be an integer.")
        if offset < 0:
            bad("offset may not be negative.")
    return limit, offset


def qstr(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def qint(name):
    value = qstr(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        bad("%s must be an integer." % name)


def qbool(name):
    value = qstr(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    bad("%s must be a boolean." % name)


def paged(records, limit, offset, serializer):
    total = len(records)
    window = records[offset:offset + limit]
    return [serializer(r) for r in window], total
