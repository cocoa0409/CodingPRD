"""Request-level validation helpers implementing PRD §2.12 (Order of Rejection).

The rejection order is realised by running field checks in phases across the
whole payload: presence/type first (step 4), then enum and ISO-8601 parsing
(step 5), then numeric range (step 6), then window sanity (step 7).  Existence
and business checks are performed by the route handlers afterwards.
"""

from flask import request

from errors import ApiError
from store import parse_date, parse_dt

ALL_ROLES = (
    "CWProjectManager",
    "CWDetailer",
    "DelegatedEngineer",
    "ArchitectOfRecord",
    "GlazingProcurement",
    "StructuralContractor",
    "FieldSuperintendent",
    "QCInspector",
)

# --- enum vocabularies (SCAFFOLD.yaml §1.1) -------------------------------
PACKAGE_STATES = (
    "DESIGN_ASSIST",
    "SYSTEM_SELECTED",
    "MOCKUP_QUALIFIED",
    "IN_FABRICATION",
    "IN_INSTALLATION",
    "WEATHER_TIGHT_ACHIEVED",
    "CLOSED_OUT",
)
SYSTEM_TYPES = ("UNDECIDED", "UNITIZED", "STICK_BUILT")
DECIDED_SYSTEM_TYPES = ("UNITIZED", "STICK_BUILT")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
SUBMITTAL_TYPES = (
    "SHOP_DRAWING",
    "STRUCTURAL_CALCULATION",
    "COATING_SPEC",
    "MOCKUP_TEST_PLAN",
)
SUBMITTAL_STATES = (
    "SUBMITTED",
    "UNDER_REVIEW",
    "REVISION_REQUIRED",
    "APPROVED",
    "APPROVED_AS_NOTED",
    "ESCALATED",
    "VOIDED",
)
REVIEW_DECISIONS = ("APPROVED", "APPROVED_AS_NOTED", "REVISION_REQUIRED", "ESCALATED")
RELEASE_STATES = ("RELEASED", "REVOKED", "CLOSED")
GLASS_ORDER_STATES = ("ORDERED", "IN_PRODUCTION", "RECEIVED", "CLOSED")
RISK_VARIANTS = ("NOMINAL", "EXPEDITE_ADJUSTED")
DRAW_REASONS = (
    "FIELD_BREAKAGE",
    "COATING_DEFECT",
    "HANDLING_DAMAGE",
    "MOCKUP_CONSUMPTION",
)
DRAW_STATUSES = ("DRAWN", "CANCELLED")
LOT_STATUSES = ("BATCHED", "GLAZED", "SHIPPED", "ON_HOLD")
LOT_ADVANCE_TARGETS = ("GLAZED", "SHIPPED")
HOLD_REASONS = ("SUBMITTAL_REVISION", "GLASS_RE_FIRE")
MOCKUP_STATES = ("SCHEDULED", "PASSED", "FAILED")
SURVEY_STATES = ("PENDING_SURVEY", "ACCEPTED", "REJECTED", "POURED")
ELEVATIONS = ("NORTH", "SOUTH", "EAST", "WEST")
ANCHOR_TYPES = ("SLOTTED", "PINNED", "FIXED")
INSTALL_STATUSES = ("PLANNED", "ANCHORS_SET", "PANELS_HUNG")
WEATHER_STATUSES = ("NOT_TIGHT", "WEATHER_TIGHT", "REMEDIATION")
CREW_DAY_STATUSES = ("POSTED", "VOIDED")
RIG_KINDS = ("MAST_CLIMBER", "TOWER_CRANE", "MONORAIL")
RIG_STATUSES = ("ACTIVE", "OUT_OF_SERVICE")
RESERVATION_STATUSES = ("RESERVED", "CONSUMED", "CANCELLED")
FIELD_TEST_KINDS = ("WATER_AAMA_501_2", "AIR_INFILTRATION", "STRUCTURAL_DEFLECTION")
FIELD_TEST_STATES = ("SCHEDULED", "PASSED", "FAILED")
OUTCOME_REASONS = (
    "WITHIN_TOLERANCE",
    "WATER_PENETRATION",
    "AIR_LEAKAGE_EXCEEDED",
    "DEFLECTION_EXCEEDED",
)
DEFECT_ORIGINS = ("MOCKUP_TEST", "FIELD_TEST", "PUNCH_LIST")
DEFECT_SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
DEFECT_STATUSES = ("OPEN", "REMEDIATION_SUBMITTED", "CLOSED", "WAIVED")
REINSPECT_OUTCOMES = ("PASS", "FAIL")


# --------------------------------------------------------------------------
# headers
# --------------------------------------------------------------------------
def auth(*allowed):
    """PRD §2.12 steps 1-2."""
    role = request.headers.get("X-User-Role")
    if role is None:
        role = request.headers.get("X-Role")
    if role is None or not role.strip():
        raise ApiError("ERR_MISSING_ROLE")
    role = role.strip()
    permitted = allowed if allowed else ALL_ROLES
    if role not in permitted:
        raise ApiError("ERR_UNAUTHORIZED")
    return role


def user_id():
    value = request.headers.get("X-User-ID")
    if value is None or not value.strip():
        return None
    return value.strip()


def require_user():
    """PRD §2.12 step 3."""
    value = user_id()
    if value is None:
        raise ApiError("ERR_MISSING_USER")
    return value


# --------------------------------------------------------------------------
# body
# --------------------------------------------------------------------------
def body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    parsed = request.get_json(silent=True)
    if not isinstance(parsed, dict):
        return {}
    return parsed


TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "num": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "enum": lambda v: isinstance(v, str),
    "datetime": lambda v: isinstance(v, str),
    "date": lambda v: isinstance(v, str),
}


class F:
    """A single payload field specification."""

    __slots__ = ("name", "kind", "required", "enum", "rng", "default")

    def __init__(self, name, kind, required=True, enum=None, rng=None, default=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = enum
        self.rng = rng
        self.default = default


def check_type(spec, value):
    if not TYPE_CHECKS[spec.kind](value):
        raise ApiError(
            "ERR_INVALID_REQUEST", "field '%s' has the wrong type" % spec.name
        )


def read_fields(payload, specs):
    """Run the four field phases in PRD §2.12 order and return a value dict."""
    values = {}
    present = []

    # step 4 - presence and JSON type
    for spec in specs:
        raw = payload.get(spec.name, None)
        if raw is None:
            if spec.required:
                raise ApiError(
                    "ERR_INVALID_REQUEST", "field '%s' is required" % spec.name
                )
            values[spec.name] = spec.default
            continue
        check_type(spec, raw)
        values[spec.name] = raw
        present.append(spec)

    # step 5 - enum membership and ISO 8601 parsing
    for spec in present:
        raw = values[spec.name]
        if spec.kind == "enum":
            if raw not in spec.enum:
                raise ApiError(
                    "ERR_INVALID_ENUM",
                    "field '%s' value '%s' is outside the permitted set"
                    % (spec.name, raw),
                )
        elif spec.kind == "datetime":
            parsed = parse_dt(raw)
            if parsed is None:
                raise ApiError(
                    "ERR_INVALID_ENUM",
                    "field '%s' is not a valid ISO 8601 timestamp" % spec.name,
                )
            values[spec.name] = parsed
        elif spec.kind == "date":
            parsed = parse_date(raw)
            if parsed is None:
                raise ApiError(
                    "ERR_INVALID_ENUM",
                    "field '%s' is not a valid ISO 8601 date" % spec.name,
                )

    # step 6 - numeric range
    for spec in present:
        if spec.rng is not None and not spec.rng(values[spec.name]):
            raise ApiError(
                "ERR_VALUE_OUT_OF_RANGE",
                "field '%s' is outside its permitted range" % spec.name,
            )
    return values


def check_window(start, end):
    """PRD §2.12 step 7."""
    if end is None or start is None or end <= start:
        raise ApiError("ERR_INVALID_WINDOW")


def require_string(payload, name, error_id="ERR_INVALID_REQUEST"):
    value = payload.get(name)
    if value is None or not isinstance(value, str) or not value.strip():
        raise ApiError(error_id, "field '%s' is required" % name)
    return value


# --------------------------------------------------------------------------
# query parameters
# --------------------------------------------------------------------------
def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise ApiError(
            "ERR_INVALID_ENUM",
            "query parameter '%s' value '%s' is outside the permitted set"
            % (name, value),
        )
    return value


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise ApiError(
        "ERR_INVALID_ENUM",
        "query parameter '%s' must be a boolean" % name,
    )


def q_int(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return -(10**9)


def paginate(rows):
    """PRD §2.3 - limit defaults to 10, floors at 1 and caps at 100."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(rows)
    page = rows[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
