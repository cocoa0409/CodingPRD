"""PRD 2.5 stage 9 — request shape validation helpers."""

from flask import request

from errors import ApiError
from store import parse_date, parse_instant

ROLES = (
    "Applicant",
    "IntakeClerk",
    "Evaluator",
    "EligibilitySpecialist",
    "IndependentReviewer",
    "ConductOfficer",
    "TravelTrainer",
    "AccessibilityOfficeAdmin",
)

RESIDENCE_ZONES = ("IN_SERVICE_AREA", "OUT_OF_SERVICE_AREA")
MOBILITY_AIDS = ("NONE", "CANE", "WALKER", "MANUAL_WHEELCHAIR", "POWER_WHEELCHAIR", "SCOOTER")
APPLICATION_TYPES = ("NEW", "RECERTIFICATION")
PROVIDER_TYPES = (
    "PHYSICIAN",
    "PHYSICAL_THERAPIST",
    "OCCUPATIONAL_THERAPIST",
    "PSYCHOLOGIST",
    "SOCIAL_WORKER",
    "OTHER",
)
VERIFICATION_OUTCOMES = ("ACCEPTED", "INSUFFICIENT")
VEHICLE_STATUSES = ("IN_SERVICE", "OUT_OF_SERVICE")
ATTENDANCE_BRANCHES = ("ATTENDED", "NO_SHOW", "CANCELLED_BY_AGENCY")
CATEGORIES = ("UNCONDITIONAL", "CONDITIONAL", "TEMPORARY", "INELIGIBLE")
CONDITION_TYPES = (
    "HEAT_INDEX_ABOVE",
    "COLD_BELOW",
    "PRECIPITATION",
    "PATH_OF_TRAVEL_BARRIER",
    "DISTANCE_OVER_METERS",
    "COGNITIVE_UNFAMILIAR_ROUTE",
    "NIGHT_TRAVEL",
)
COMPARATORS = ("GTE", "GT", "LTE", "LT", "IS_TRUE")
ROUTE_FAMILIARITY = ("FAMILIAR", "UNFAMILIAR")
APPEAL_OUTCOMES = ("UPHELD", "OVERTURNED", "MODIFIED")
GRANTED_CATEGORIES = ("UNCONDITIONAL", "CONDITIONAL", "TEMPORARY")
TRIP_EVENT_TYPES = ("COMPLETED", "NO_SHOW", "LATE_CANCEL", "CANCEL_IN_ADVANCE", "AGENCY_FAULT_NO_SHOW")
SUSPENSION_DECISIONS = ("UPHELD", "RESCINDED")
REFERRAL_REASONS = ("CONDITIONAL_ELIGIBILITY_AUTO", "STAFF_REFERRAL", "RIDER_REQUEST")
REFERRAL_DECISIONS = ("ENROLLED", "DECLINED")

FUNCTIONAL_ANSWER_KEYS = (
    "can_board_bus_steps",
    "can_navigate_unfamiliar_route",
    "max_walk_distance_meters",
    "uses_mobility_aid_outdoors",
    "has_cognitive_impairment",
)


def bad(message="The request payload is invalid."):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Return the JSON request body as a dict.  Malformed payloads are 400."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(force=True, silent=True)
    if parsed is None:
        bad("Request body must be a JSON object.")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def req_str(payload, field):
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' is required and must be a non-empty string." % field)
    return value


def opt_str(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    return value


def req_enum(payload, field, allowed):
    value = payload.get(field)
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def opt_enum(payload, field, allowed, default=None):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def req_bool(payload, field):
    value = payload.get(field)
    if not isinstance(value, bool):
        bad("Field '%s' is required and must be a boolean." % field)
    return value


def opt_bool(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(payload, field, minimum=None, maximum=None):
    value = payload.get(field)
    if not _is_int(value):
        bad("Field '%s' is required and must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (field, maximum))
    return value


def opt_int(payload, field, default=None, minimum=None, maximum=None):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if not _is_int(value):
        bad("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (field, maximum))
    return value


def opt_number(payload, field, default=None, minimum=None):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % field)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (field, minimum))
    return value


def req_instant(payload, field):
    value = payload.get(field)
    parsed = parse_instant(value)
    if parsed is None:
        bad("Field '%s' is required and must be a well-formed ISO 8601 UTC instant." % field)
    return parsed


def opt_instant(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    parsed = parse_instant(payload[field])
    if parsed is None:
        bad("Field '%s' must be a well-formed ISO 8601 UTC instant." % field)
    return parsed


def req_iso_date(payload, field):
    value = payload.get(field)
    parsed = parse_date(value)
    if parsed is None:
        bad("Field '%s' is required and must be an ISO 8601 calendar date (YYYY-MM-DD)." % field)
    return parsed


def opt_iso_date(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    parsed = parse_date(payload[field])
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)." % field)
    return parsed


def req_string_array(payload, field):
    value = payload.get(field)
    if not isinstance(value, list) or len(value) == 0:
        bad("Field '%s' must be a non-empty array." % field)
    return value


def opt_array(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % field)
    return value


def questionnaire_object(payload, field, required=True):
    """functional_answers must be an object; completeness bites at submission."""
    if field not in payload or payload[field] is None:
        if required:
            bad("Field '%s' is required." % field)
        return None
    value = payload[field]
    if not isinstance(value, dict):
        bad("Field '%s' must be an object." % field)
    return value


def questionnaire_complete(answers):
    """PRD 3.1: complete only when all five keys are present and non-null."""
    if not isinstance(answers, dict):
        return False
    for key in FUNCTIONAL_ANSWER_KEYS:
        if key not in answers or answers[key] is None:
            return False
    for key in (
        "can_board_bus_steps",
        "can_navigate_unfamiliar_route",
        "uses_mobility_aid_outdoors",
        "has_cognitive_impairment",
    ):
        if not isinstance(answers[key], bool):
            return False
    walk = answers["max_walk_distance_meters"]
    if not _is_int(walk) or walk < 0:
        return False
    return True
