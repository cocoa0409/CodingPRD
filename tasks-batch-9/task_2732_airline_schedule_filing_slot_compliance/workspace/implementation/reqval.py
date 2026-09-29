"""Band 3 request-shape validation helpers. Every failure is ERR_INVALID_REQUEST."""
import re

from flask import request

from errors import ApiError
from util import fmt_dt, parse_dt

MISSING = object()

ENUMS = {
    "carrier_status": ("ACTIVE", "SUSPENDED"),
    "coordination_level": ("LEVEL_1_NON_COORDINATED", "LEVEL_2_FACILITATED", "LEVEL_3_COORDINATED"),
    "season_status": ("DRAFT", "OPEN", "CLOSED", "ARCHIVED"),
    "aircraft_status": ("IN_SERVICE", "MAINTENANCE_GROUNDED", "RETIRED"),
    "rotation_feasibility_status": (
        "UNCHECKED", "FEASIBLE", "INFEASIBLE_CONTINUITY", "INFEASIBLE_TURN", "INFEASIBLE_BLOCK_CAP",
    ),
    "filing_status": ("DRAFT", "VALIDATED", "FILED", "SUPERSEDED", "WITHDRAWN"),
    "compliance_state": ("CLEAN", "WARNED", "BLOCKED"),
    "leg_status": ("DRAFT", "ASSIGNED", "SLOT_BACKED", "FILED", "REFILE_REQUIRED", "CANCELLED"),
    "movement_type": ("ARRIVAL", "DEPARTURE"),
    "holding_status": ("HELD", "RETURNED", "TRANSFERRED_OUT", "LOST", "EXPIRED"),
    "outcome": ("OPERATED", "CANCELLED_CARRIER", "CANCELLED_ATC", "NOT_OPERATED", "RETURNED_IN_TIME"),
    "transaction_kind": ("EXCHANGE", "TRANSFER"),
    "transaction_status": (
        "PROPOSED", "COUNTERPARTY_ACCEPTED", "COUNTERPARTY_REJECTED",
        "COORDINATOR_DENIED", "EXECUTED", "WITHDRAWN",
    ),
    "distribution_system": ("IATA_SSIM", "OAG", "GDS_ATPCO"),
    "change_window": ("STANDARD", "EXPEDITED", "EMERGENCY"),
    "submission_status": ("QUEUED", "TRANSMITTED", "ACKNOWLEDGED", "REJECTED"),
    "codeshare_sync_status": ("NOT_REQUIRED", "PENDING_ACK", "SYNCHRONIZED"),
    "freedom_type": ("THIRD_FOURTH", "FIFTH", "SEVENTH"),
    "authority_status": ("ACTIVE", "SUSPENDED", "EXPIRED"),
    "trigger_kind": ("RETIME", "CANCELLATION", "SLOT_LOSS"),
    "obligation_tier": ("ADVISORY", "MANDATORY_REACCOMMODATION"),
    "obligation_status": ("PENDING", "DISPATCHED", "WAIVED"),
    "channel": ("EMAIL", "SMS", "AGENCY_QUEUE"),
}


def bad(message="The request payload is malformed or violates a field constraint."):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The JSON object of the request, or an empty dict when no body was sent."""
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


def present(payload, name):
    return name in payload


def req_str(payload, name, min_len=None, max_len=None, pattern=None):
    value = payload.get(name, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % name)
    return _check_str(name, value, min_len, max_len, pattern)


def opt_str(payload, name, min_len=None, max_len=None, pattern=None, default=None):
    value = payload.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    return _check_str(name, value, min_len, max_len, pattern)


def _check_str(name, value, min_len, max_len, pattern):
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' is shorter than %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is longer than %d characters." % (name, max_len))
    if pattern is not None and not re.match(pattern + r"\Z", value):
        bad("Field '%s' does not match its required format." % name)
    return value


def req_enum(payload, name, enum_key):
    value = req_str(payload, name)
    if value not in ENUMS[enum_key]:
        bad("Field '%s' is not a declared enumeration member." % name)
    return value


def opt_enum(payload, name, enum_key, default=None):
    value = payload.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, str) or value not in ENUMS[enum_key]:
        bad("Field '%s' is not a declared enumeration member." % name)
    return value


def req_int(payload, name, minimum=None, maximum=None):
    value = payload.get(name, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % name)
    return _check_int(name, value, minimum, maximum)


def opt_int(payload, name, minimum=None, maximum=None, default=None):
    value = payload.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    return _check_int(name, value, minimum, maximum)


def _check_int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' is below its minimum of %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' is above its maximum of %s." % (name, maximum))
    return value


def req_dt(payload, name):
    value = payload.get(name, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % name)
    return _check_dt(name, value)


def opt_dt(payload, name, default=None):
    value = payload.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    return _check_dt(name, value)


def _check_dt(name, value):
    parsed = parse_dt(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 UTC timestamp ending in Z." % name)
    return fmt_dt(parsed)


def req_bool(payload, name):
    value = payload.get(name, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % name)
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def opt_bool(payload, name, default=False):
    value = payload.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def opt_str_list(payload, name, max_items=None, default=None):
    value = payload.get(name, MISSING)
    if value is MISSING or value is None:
        return list(default) if default else []
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str) or not item:
            bad("Field '%s' must contain non-empty strings." % name)
    if max_items is not None and len(value) > max_items:
        bad("Field '%s' holds more than %d elements." % (name, max_items))
    if len(set(value)) != len(value):
        bad("Field '%s' may not contain duplicates." % name)
    return list(value)


DAYS = "1234567"


def req_days_of_week(payload, name):
    value = req_str(payload, name, 1, 7)
    for ch in value:
        if ch not in DAYS:
            bad("Field '%s' may only contain the digits 1 through 7." % name)
    if len(set(value)) != len(value):
        bad("Field '%s' may not repeat a day." % name)
    if list(value) != sorted(value):
        bad("Field '%s' must be in strictly ascending order." % name)
    return value


def pagination():
    """limit/offset per PRD 2.3, rejected rather than clamped when out of band."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        text = args.get("limit")
        try:
            limit = int(str(text).strip())
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        text = args.get("offset")
        try:
            offset = int(str(text).strip())
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must not be negative.")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def q_enum(name, enum_key):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in ENUMS[enum_key]:
        bad("Query parameter '%s' is not a declared enumeration member." % name)
    return value


def q_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter '%s' must be a boolean." % name)


def q_int(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)
