"""Request-schema validation (ladder rung 3 -> ERR_INVALID_REQUEST, 400)
plus existence resolution helpers (rung 4 -> the 404 family)."""

import re
from decimal import Decimal

import clock
from errors import ApiError
from store import db

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
SOURCE_TYPES = ("PEP", "NWS", "LP1", "LP2", "SATELLITE", "IPAWS")
SERVICE_TYPES = ("TV", "FM", "AM", "CABLE")
DEVICE_ROLES = ("DECODER", "ENCODER", "MONITOR")
RELAY_CLASSES = ("MANDATORY", "OPTIONAL")
ENTRY_KINDS = ("TRANSMISSION", "RECEIPT")
TEST_TYPES = ("WEEKLY", "MONTHLY", "NATIONAL")
CAPTION_INTERACTIONS = ("NONE", "CAPTION_SUPPRESSED", "CRAWL_OVERLAP")
DOCUMENT_KINDS = (
    "STATION_LOG",
    "TEST_LOGS",
    "PLAN_COPY",
    "OUTAGE_LOG",
    "ACCESSIBILITY_ATTESTATION",
)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
CALL_SIGN_RE = re.compile(r"^[A-Z0-9]{3,8}$")
EVENT_CODE_RE = re.compile(r"^[A-Z0-9]{1,6}$")
FIPS_RE = re.compile(r"^\d{5}$")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def json_body(request):
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        bad("Request body must be a JSON object.")
    if not isinstance(body, dict):
        bad("Request body must be a JSON object.")
    return body


def present(body, field):
    return field in body and body[field] is not None


def req_string(body, field, pattern=None, allow_empty=False):
    if not present(body, field):
        bad("Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    if not allow_empty and value == "":
        bad("Field '%s' must not be empty." % field)
    if pattern is not None and not pattern.match(value):
        bad("Field '%s' has an invalid format." % field)
    return value


def opt_string(body, field, pattern=None, default=None, allow_empty=False):
    if not present(body, field):
        return default
    return req_string(body, field, pattern=pattern, allow_empty=allow_empty)


def req_enum(body, field, allowed):
    if not present(body, field):
        bad("Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def req_int(body, field, minimum=None, maximum=None):
    if not present(body, field):
        bad("Field '%s' is required." % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (field, maximum))
    return value


def opt_int(body, field, minimum=None, maximum=None, default=None):
    if not present(body, field):
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


def req_number(body, field, minimum=None, maximum=None):
    if not present(body, field):
        bad("Field '%s' is required." % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % field)
    dec = Decimal(str(value))
    if minimum is not None and dec < Decimal(str(minimum)):
        bad("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        bad("Field '%s' must be <= %s." % (field, maximum))
    return dec


def req_bool(body, field):
    if not present(body, field):
        bad("Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def req_datetime(body, field):
    if not present(body, field):
        bad("Field '%s' is required." % field)
    parsed = clock.parse_iso(body[field])
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 UTC instant." % field)
    return parsed


def req_array(body, field, non_empty=True, distinct=False, member_enum=None,
              member_pattern=None, member_type=str):
    if not present(body, field):
        bad("Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % field)
    if non_empty and len(value) == 0:
        bad("Field '%s' must not be empty." % field)
    for item in value:
        if member_type is str and (not isinstance(item, str) or isinstance(item, bool)):
            bad("Field '%s' must contain strings." % field)
        if member_enum is not None and item not in member_enum:
            bad("Field '%s' contains an undeclared value." % field)
        if member_pattern is not None and not member_pattern.match(item):
            bad("Field '%s' contains a malformed value." % field)
    if distinct and len(set(value)) != len(value):
        bad("Field '%s' must contain distinct values." % field)
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

def pagination(request):
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)


# ---------------------------------------------------------------------------
# Existence resolution (rung 4)
# ---------------------------------------------------------------------------

def _fetch(collection, row_id, error_id):
    if not isinstance(row_id, str) or row_id not in collection:
        raise ApiError(error_id)
    return collection[row_id]


def get_state_plan(row_id):
    return _fetch(db.state_plans, row_id, "ERR_STATE_PLAN_NOT_FOUND")


def get_station(row_id):
    return _fetch(db.stations, row_id, "ERR_STATION_NOT_FOUND")


def get_relay_rule(row_id):
    return _fetch(db.relay_rules, row_id, "ERR_RELAY_RULE_NOT_FOUND")


def get_device(row_id):
    return _fetch(db.devices, row_id, "ERR_DEVICE_NOT_FOUND")


def get_assignment(row_id):
    return _fetch(db.assignments, row_id, "ERR_ASSIGNMENT_NOT_FOUND")


def get_outage(row_id):
    return _fetch(db.outages, row_id, "ERR_OUTAGE_NOT_FOUND")


def get_alert(row_id):
    return _fetch(db.alerts, row_id, "ERR_ALERT_EVENT_NOT_FOUND")


def get_wea_notice(row_id):
    return _fetch(db.wea_notices, row_id, "ERR_WEA_NOTICE_NOT_FOUND")


def get_test_event(row_id):
    return _fetch(db.test_events, row_id, "ERR_TEST_EVENT_NOT_FOUND")


def get_log_entry(row_id):
    return _fetch(db.log_entries, row_id, "ERR_LOG_ENTRY_NOT_FOUND")


def get_filing(row_id):
    return _fetch(db.filings, row_id, "ERR_FILING_NOT_FOUND")


def get_inspection(row_id):
    return _fetch(db.inspections, row_id, "ERR_INSPECTION_NOT_FOUND")
