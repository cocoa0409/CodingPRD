"""Parsing, validation, rounding, and pagination helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError

# --- enum vocabularies (SCAFFOLD.yaml entities) ---
SPECIALTIES = ("MANAGEMENT", "MODELING", "DOCUMENTATION", "COMMISSIONING")
RATING_SYSTEMS = ("LEED_BD_C", "LEED_ID_C", "LEED_O_M")
COMPLIANCE_PATHS = ("PRESCRIPTIVE", "PERFORMANCE")
LEVELS = ("CERTIFIED", "SILVER", "GOLD", "PLATINUM")
CREDIT_CATEGORIES = (
    "ENERGY_ATMOSPHERE",
    "MATERIALS",
    "INDOOR_ENVIRONMENT",
    "WATER",
    "SUSTAINABLE_SITES",
    "INTEGRATIVE",
)
PHASE_ELIGIBILITY = ("DESIGN", "CONSTRUCTION", "BOTH")
PHASES = ("DESIGN", "CONSTRUCTION")
MODEL_TYPES = ("BASELINE", "PROPOSED")
MODELING_STANDARDS = ("ASHRAE_90_1_2016", "ASHRAE_90_1_2019")
SEVERITIES = ("CLARIFICATION", "DEFICIENCY")
TASK_TYPES = ("OPR_DOCUMENT", "CX_PLAN", "FUNCTIONAL_TESTING", "SYSTEMS_MANUAL", "CX_REPORT")
INCENTIVE_TYPES = ("TAX_CREDIT", "GRANT", "UTILITY_REBATE")
DECISIONS = ("CERTIFY", "DENY")
CX_OUTCOMES = ("PASSED", "FAILED")
VERIFY_OUTCOMES = ("ACCEPT", "REJECT")
RECERT_OUTCOMES = ("RECERTIFY", "LAPSE")

PROJECT_STATUSES = (
    "REGISTERED", "STRATEGY_LOCKED", "DESIGN_SUBMITTED", "DESIGN_REVIEWED",
    "CONSTRUCTION_SUBMITTED", "CONSTRUCTION_REVIEWED", "CERTIFIED",
    "PERFORMANCE_REPORTING", "RECERTIFICATION_REVIEW", "LAPSED", "DENIED",
)
ATTEMPT_STATUSES = (
    "SELECTED", "DOCUMENTATION_IN_PROGRESS", "READY_FOR_SUBMITTAL", "SUBMITTED",
    "UNDER_REVIEW", "CLARIFICATION_REQUESTED", "RESUBMITTED", "AWARDED",
    "DENIED", "APPEALED", "DROPPED",
)
MODEL_STATUSES = ("DRAFT", "LOCKED", "SUPERSEDED")
COMMENT_STATUSES = ("OPEN", "ADDRESSED", "REOPENED", "ACCEPTED")
TASK_STATUSES = ("SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED")
INCENTIVE_APP_STATUSES = ("APPLIED", "APPROVED", "DISBURSED")
REPORT_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware datetime (UTC assumed)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
        return data
    return {}


def required(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    return data[field]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def as_int(v, field):
    if not _is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an integer")
    return v


def as_str(v, field):
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a string")
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a boolean")
    return v


def as_opt_bool(data, field, default=False):
    if field not in data or data[field] is None:
        return default
    return as_bool(data[field], field)


def as_enum(v, allowed, field):
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            f"Field {field} must be one of {', '.join(allowed)}",
        )
    return v


def as_dt(v, field):
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 datetime")
    try:
        parse_dt(v)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 datetime")
    return v


def as_number(v, field):
    """Accept a JSON number (int/float, not bool) and return an exact Decimal."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a number")
    try:
        return Decimal(str(v))
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a number")


def round_half_up_int(d):
    """Round a Decimal to the nearest integer, halves up."""
    if not isinstance(d, Decimal):
        d = Decimal(str(d))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_round_2dp(numer_cents, denom_cents):
    """(numer/denom)*100 as a 2-decimal half-up float (exact integer-cent inputs)."""
    q = (Decimal(numer_cents) / Decimal(denom_cents) * Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(q)


def num_out(d):
    """Serialize a Decimal as int when integral, else float (JSON-friendly)."""
    if not isinstance(d, Decimal):
        d = Decimal(str(d))
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def pagination_args():
    """limit/offset query params; defaults 10/0; limit clamped to [1, 100]."""
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        limit = 10
    try:
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def bool_filter(value):
    """Parse a boolean query param; None when unparseable (filter ignored)."""
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("true", "1"):
        return True
    if v in ("false", "0"):
        return False
    return None
