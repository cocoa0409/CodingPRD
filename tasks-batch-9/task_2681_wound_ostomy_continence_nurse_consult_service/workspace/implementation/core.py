"""Foundation layer: logical clock, response envelope, error catalogue,
auth, in-memory store and the declarative request-schema validator.

Every structural name in this module is taken from PRD.md / SCAFFOLD.yaml:
  auth headers            X-User-ID, X-User-Role
  roles                   WocNurse, UnitCharge, WocProgramDirector,
                          MaterialsCoordinator, SystemOperator
  success envelope        { meta: { api_request_id, api_request_timestamp,
                                    limit, offset, total_count, has_more },
                            response_type: "object"|"array", data: ... }
  error envelope          { meta: {...}, response_type: "error",
                            data: { error_id, message } }
  pagination              limit (default 10, 1..100), offset (default 0, >=0)
  concurrency fields      version (on the parent row), expected_patient_version,
                          expected_unit_version
"""

import os
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLE_WOC_NURSE = "WocNurse"
ROLE_UNIT_CHARGE = "UnitCharge"
ROLE_DIRECTOR = "WocProgramDirector"
ROLE_MATERIALS = "MaterialsCoordinator"
ROLE_SYSOP = "SystemOperator"

ALL_ROLES = (
    ROLE_WOC_NURSE,
    ROLE_UNIT_CHARGE,
    ROLE_DIRECTOR,
    ROLE_MATERIALS,
    ROLE_SYSOP,
)

READ_ROLES = (ROLE_WOC_NURSE, ROLE_UNIT_CHARGE, ROLE_DIRECTOR, ROLE_MATERIALS)

# ---------------------------------------------------------------------------
# Error catalogue (PRD section 5)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_NURSE_NOT_FOUND": 404,
    "ERR_CONSULT_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_SURVEY_ROUND_NOT_FOUND": 404,
    "ERR_OBSERVATION_NOT_FOUND": 404,
    "ERR_SURFACE_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_PROTOCOL_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_ENTITY_LINK_MISMATCH": 422,
    "ERR_CONSULT_INVALID_STATE": 409,
    "ERR_ASSESSMENT_INVALID_STATE": 409,
    "ERR_CASE_INVALID_STATE": 409,
    "ERR_ORDER_NOT_PENDING": 409,
    "ERR_ORDER_INVALID_BILLING_STATE": 409,
    "ERR_SURVEY_ROUND_NOT_OPEN": 409,
    "ERR_PATIENT_DISCHARGED": 409,
    "ERR_RESOURCE_NOT_ACTIVE": 409,
    "ERR_RCA_NOT_COMPLETE": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_UNIT_POSTURE_RESTRICTED": 409,
    "ERR_SURVEY_UNIT_COVERAGE_INCOMPLETE": 409,
    "ERR_SURVEY_WINDOW_CONFLICT": 409,
    "ERR_SURFACE_UNAVAILABLE": 409,
    "ERR_DUPLICATE_OBSERVATION": 409,
    "ERR_DUPLICATE_NATURAL_KEY": 409,
    "ERR_STALE_PATIENT_VERSION": 412,
    "ERR_STALE_UNIT_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_NURSE_NOT_CERTIFIED": 422,
    "ERR_NURSE_LOAD_EXCEEDED": 422,
    "ERR_CERTIFICATION_NOT_ELIGIBLE": 422,
    "ERR_STAGE_NOT_VALIDATED": 422,
    "ERR_POA_WINDOW_CLOSED": 422,
    "ERR_OBSERVATION_OUTSIDE_WINDOW": 422,
    "ERR_NON_FORMULARY_JUSTIFICATION_REQUIRED": 422,
    "ERR_OSTOMY_PLAN_NOT_ELIGIBLE": 422,
    "ERR_RENTAL_DAYS_EXCEED_AUTHORIZATION": 422,
    "ERR_RENTAL_BUDGET_EXCEEDED": 402,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or unknown authentication headers.",
    "ERR_UNAUTHORIZED": "Caller role may not perform this operation.",
    "ERR_INVALID_REQUEST": "Request payload or query string is invalid.",
    "ERR_UNIT_NOT_FOUND": "Unit does not exist.",
    "ERR_PATIENT_NOT_FOUND": "Patient does not exist.",
    "ERR_NURSE_NOT_FOUND": "WOC nurse does not exist.",
    "ERR_CONSULT_NOT_FOUND": "Consult request does not exist.",
    "ERR_ASSESSMENT_NOT_FOUND": "Skin assessment does not exist.",
    "ERR_CASE_NOT_FOUND": "Pressure injury case does not exist.",
    "ERR_SURVEY_ROUND_NOT_FOUND": "Survey round does not exist.",
    "ERR_OBSERVATION_NOT_FOUND": "Survey observation does not exist.",
    "ERR_SURFACE_NOT_FOUND": "Support surface does not exist.",
    "ERR_ORDER_NOT_FOUND": "Support surface order does not exist.",
    "ERR_PRODUCT_NOT_FOUND": "Formulary product does not exist.",
    "ERR_PROTOCOL_NOT_FOUND": "Dressing protocol does not exist.",
    "ERR_PLAN_NOT_FOUND": "Ostomy education plan does not exist.",
    "ERR_ENTITY_LINK_MISMATCH": "Referenced rows exist but do not belong together.",
    "ERR_CONSULT_INVALID_STATE": "Consult request is not in a state that permits this transition.",
    "ERR_ASSESSMENT_INVALID_STATE": "Skin assessment is not in a state that permits this transition.",
    "ERR_CASE_INVALID_STATE": "Pressure injury case is not in a state that permits this transition.",
    "ERR_ORDER_NOT_PENDING": "Support surface order is not awaiting approval.",
    "ERR_ORDER_INVALID_BILLING_STATE": "Support surface order billing dimension is not in a state that permits this transition.",
    "ERR_SURVEY_ROUND_NOT_OPEN": "Survey round is not open for the requested operation.",
    "ERR_PATIENT_DISCHARGED": "Patient is discharged; inpatient WOC operations are closed.",
    "ERR_RESOURCE_NOT_ACTIVE": "Referenced catalogue row has been retired or archived.",
    "ERR_RCA_NOT_COMPLETE": "Root cause analysis is not finished.",
    "ERR_REVISION_LIMIT_REACHED": "Consult request has already consumed its revision allowance.",
    "ERR_UNIT_POSTURE_RESTRICTED": "Unit survey posture forbids this operation without a director override.",
    "ERR_SURVEY_UNIT_COVERAGE_INCOMPLETE": "Survey round cannot be locked before every participating unit has been observed.",
    "ERR_SURVEY_WINDOW_CONFLICT": "Unit already carries the maximum number of survey rounds overlapping this window.",
    "ERR_SURFACE_UNAVAILABLE": "Support surface is occupied or still within its reclean buffer for the requested interval.",
    "ERR_DUPLICATE_OBSERVATION": "This patient has already been observed in this survey round.",
    "ERR_DUPLICATE_NATURAL_KEY": "Natural key is already taken.",
    "ERR_STALE_PATIENT_VERSION": "Patient has changed since it was read.",
    "ERR_STALE_UNIT_VERSION": "Unit has changed since it was read.",
    "ERR_SEGREGATION_OF_DUTIES": "The same person may not perform both halves of this control.",
    "ERR_NURSE_NOT_CERTIFIED": "Nurse certification status does not permit this action.",
    "ERR_NURSE_LOAD_EXCEEDED": "Nurse is already carrying the maximum consult load for their certification tier.",
    "ERR_CERTIFICATION_NOT_ELIGIBLE": "Nurse does not meet the certification pipeline gate.",
    "ERR_STAGE_NOT_VALIDATED": "Operation requires a validated skin assessment stage.",
    "ERR_POA_WINDOW_CLOSED": "Present-on-admission may no longer be confirmed for this patient.",
    "ERR_OBSERVATION_OUTSIDE_WINDOW": "Observation timestamp falls outside the survey round window.",
    "ERR_NON_FORMULARY_JUSTIFICATION_REQUIRED": "Non-formulary product requires a written justification.",
    "ERR_OSTOMY_PLAN_NOT_ELIGIBLE": "Ostomy education plan is not ready for this step.",
    "ERR_RENTAL_DAYS_EXCEED_AUTHORIZATION": "Billable days exceed the authorized day count.",
    "ERR_RENTAL_BUDGET_EXCEEDED": "Unit rental budget headroom is insufficient.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def bad_request(message=None):
    raise ApiError("ERR_INVALID_REQUEST", message)


# ---------------------------------------------------------------------------
# Money / rounding helpers.  Every monetary and score figure in this service
# is computed with Decimal + ROUND_HALF_UP; float is never used.
# ---------------------------------------------------------------------------
CENT = Decimal("0.01")


def D(value):
    """Coerce anything JSON-ish into Decimal without going through float."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Boolean is not a number.")
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places=2):
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def money(value):
    return round_half_up(value, 2)


def money_out(value):
    """Serialize a monetary Decimal as a JSON number with 2 decimals."""
    if value is None:
        return None
    return float(round_half_up(value, 2))


def score_out(value, places=1):
    if value is None:
        return None
    return float(round_half_up(value, places))


# ---------------------------------------------------------------------------
# Canonical datetime handling.
#
# All stored datetimes use the canonical form YYYY-MM-DDTHH:MM:SS.mmmZ so that
# lexicographic ordering equals chronological ordering, and so that a value
# echoed back to the client always looks the same regardless of the exact input
# spelling the client used.
# ---------------------------------------------------------------------------
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(\.\d{1,9})?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(raw):
    """Parse an ISO-8601 datetime into an aware UTC datetime, or None."""
    if raw is None or not isinstance(raw, str):
        return None
    m = _DT_RE.match(raw.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    offset = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro,
                      tzinfo=timezone.utc)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


def iso(dt):
    """Render an aware datetime in the canonical wire form."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def canon_dt(raw):
    """Normalize a client-supplied datetime string to the canonical form."""
    dt = parse_dt(raw)
    return iso(dt) if dt is not None else None


def dt_of(stored):
    """Re-hydrate a stored canonical string into a datetime."""
    return parse_dt(stored)


def add_hours(stored_or_dt, hours):
    dt = stored_or_dt if isinstance(stored_or_dt, datetime) else dt_of(stored_or_dt)
    if dt is None:
        return None
    return iso(dt + timedelta(hours=hours))


def whole_hours_between(start, end):
    """Completed whole hours from start to end (floor, never negative-rounded)."""
    a = start if isinstance(start, datetime) else dt_of(start)
    b = end if isinstance(end, datetime) else dt_of(end)
    if a is None or b is None:
        return 0
    seconds = (b - a).total_seconds()
    return int(seconds // 3600)


# ---------------------------------------------------------------------------
# Global constants (SCAFFOLD global_constants)
# ---------------------------------------------------------------------------
POA_WINDOW_HOURS = 24
RCA_DUE_HOURS = 72
MAX_REVISIONS = 2
RECLEAN_BUFFER_HOURS = 12
BILLABLE_DAY_HOURS = 24
HOURS_PER_WEEK = 168
MAX_CONCURRENT_INCIDENCE_ROUNDS = 2
TEACH_BACK_PASS_SCORE = 80
ELIGIBILITY_SCORE_FLOOR = Decimal("55.00")
CE_CREDIT_FLOOR = 30
SIGNOFF_FLOOR = 2
MAX_LOAD_BY_CERT = {"TRAINEE": 0, "CANDIDATE": 3, "CERTIFIED": 8, "LAPSED": 0}
SLA_HOURS_BY_BAND = {"P1": 4, "P2": 24, "P3": 72}
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Logical clock.  Reads exactly DEFAULT_LOGICAL_CLOCK until
# POST /_clock/set_current_utc repositions it.  Never falls back to wall time.
# ---------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.current = iso(parse_dt(DEFAULT_LOGICAL_CLOCK))

    def set(self, raw):
        dt = parse_dt(raw)
        if dt is None:
            bad_request("to_iso8601 must be an ISO 8601 datetime.")
        self.current = iso(dt)
        return self.current

    def now(self):
        return self.current

    def now_dt(self):
        return dt_of(self.current)

    def reset(self):
        self.current = iso(parse_dt(DEFAULT_LOGICAL_CLOCK))


CLOCK = Clock()


def now():
    return CLOCK.now()


def now_dt():
    return CLOCK.now_dt()


# ---------------------------------------------------------------------------
# In-memory store.  Plain dicts keyed by id; nothing is ever seeded.
# ---------------------------------------------------------------------------
STORE_NAMES = (
    "units",
    "patients",
    "woc_nurses",
    "consult_requests",
    "skin_assessments",
    "pressure_injury_cases",
    "survey_rounds",
    "survey_observations",
    "support_surfaces",
    "support_surface_orders",
    "formulary_products",
    "dressing_protocols",
    "ostomy_education_plans",
)


class Database:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in STORE_NAMES:
            setattr(self, name, {})
        # Auxiliary append-only child lists (not addressable entities).
        self.competency_signoffs = []
        self.education_sessions = []
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Database()


def new_id(prefix):
    # PRD §2.4: "Every resource carries an `id` that is a server-minted UUID
    # string with no type prefix of any kind".
    return str(uuid.uuid4())


def bump(row):
    """Optimistic-concurrency version bump plus updated_at refresh."""
    if row is None:
        return None
    row["version"] = int(row.get("version", 1)) + 1
    row["updated_at"] = now()
    return row


def new_row(prefix, **fields):
    stamp = now()
    row = {
        "id": new_id(prefix),
        "version": 1,
        "created_at": stamp,
        "updated_at": stamp,
        "_seq": DB.next_seq(),
    }
    row.update(fields)
    return row


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_lowercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _wire_timestamp():
    """Envelope timestamp is a transport artefact and uses real time."""
    return iso(datetime.now(timezone.utc))


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wire_timestamp(),
    }


def ok(data, status=200):
    return {
        "meta": base_meta(),
        "response_type": "object",
        "data": data,
    }, status


def ok_list(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }, 200


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Auth (ladder rungs 1 and 2)
# ---------------------------------------------------------------------------
def caller():
    """Rung 1 — both headers present and the role is one of the declared five."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED")
    if not role or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED")
    return str(user_id).strip(), role


def authorize(*allowed_roles):
    """Rungs 1 and 2 together.  Returns (user_id, role)."""
    user_id, role = caller()
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    return user_id, role


# ---------------------------------------------------------------------------
# Body / query parsing and the declarative schema validator (rung 3)
# ---------------------------------------------------------------------------
def raw_body():
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad_request("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad_request("Request body must be a JSON object.")
    return parsed


class F:
    """One field rule in an endpoint input schema."""

    def __init__(self, name, kind, required=False, enum=None, minimum=None,
                 maximum=None, exclusive_min=None, min_len=None, max_len=None,
                 nullable=False, item_kind=None, min_items=None, integral=False):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.exclusive_min = exclusive_min
        self.min_len = min_len
        self.max_len = max_len
        self.nullable = nullable
        self.item_kind = item_kind
        self.min_items = min_items
        self.integral = integral


def _check_string(rule, value):
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % rule.name)
    if rule.min_len is not None and len(value.strip()) < rule.min_len:
        bad_request("Field '%s' must be at least %d characters."
                    % (rule.name, rule.min_len))
    if rule.max_len is not None and len(value) > rule.max_len:
        bad_request("Field '%s' must be at most %d characters."
                    % (rule.name, rule.max_len))
    return value


def _check_number(rule, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) and not (
            isinstance(value, str) and rule.kind == "decimal_str"):
        bad_request("Field '%s' must be a number." % rule.name)
    try:
        dec = D(value)
    except Exception:
        bad_request("Field '%s' must be a number." % rule.name)
    if rule.integral and dec != dec.to_integral_value():
        bad_request("Field '%s' must be an integer." % rule.name)
    if rule.minimum is not None and dec < D(rule.minimum):
        bad_request("Field '%s' must be >= %s." % (rule.name, rule.minimum))
    if rule.exclusive_min is not None and dec <= D(rule.exclusive_min):
        bad_request("Field '%s' must be > %s." % (rule.name, rule.exclusive_min))
    if rule.maximum is not None and dec > D(rule.maximum):
        bad_request("Field '%s' must be <= %s." % (rule.name, rule.maximum))
    return dec


def validate_field(rule, value):
    kind = rule.kind
    if value is None:
        if rule.nullable:
            return None
        bad_request("Field '%s' may not be null." % rule.name)
    if kind == "string":
        return _check_string(rule, value)
    if kind == "enum":
        if not isinstance(value, str):
            bad_request("Field '%s' must be a string enum member." % rule.name)
        if rule.enum and value not in rule.enum:
            bad_request("Field '%s' must be one of %s."
                        % (rule.name, ", ".join(rule.enum)))
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            bad_request("Field '%s' must be a boolean." % rule.name)
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            if isinstance(value, float) and float(value).is_integer():
                value = int(value)
            else:
                bad_request("Field '%s' must be an integer." % rule.name)
        if rule.minimum is not None and value < rule.minimum:
            bad_request("Field '%s' must be >= %s." % (rule.name, rule.minimum))
        if rule.maximum is not None and value > rule.maximum:
            bad_request("Field '%s' must be <= %s." % (rule.name, rule.maximum))
        if rule.exclusive_min is not None and value <= rule.exclusive_min:
            bad_request("Field '%s' must be > %s." % (rule.name, rule.exclusive_min))
        return value
    if kind in ("number", "decimal_str"):
        return _check_number(rule, value)
    if kind == "datetime":
        if not isinstance(value, str):
            bad_request("Field '%s' must be an ISO 8601 datetime string." % rule.name)
        canon = canon_dt(value)
        if canon is None:
            bad_request("Field '%s' must be an ISO 8601 datetime string." % rule.name)
        return canon
    if kind == "id":
        if not isinstance(value, str) or not value.strip():
            bad_request("Field '%s' must be a non-empty id string." % rule.name)
        return value
    if kind == "id_list":
        if not isinstance(value, list):
            bad_request("Field '%s' must be an array." % rule.name)
        if rule.min_items is not None and len(value) < rule.min_items:
            bad_request("Field '%s' must contain at least %d element(s)."
                        % (rule.name, rule.min_items))
        for element in value:
            if not isinstance(element, str) or not element.strip():
                bad_request("Field '%s' must contain non-empty id strings."
                            % rule.name)
        return list(value)
    if kind == "str_list":
        if not isinstance(value, list):
            bad_request("Field '%s' must be an array." % rule.name)
        if rule.min_items is not None and len(value) < rule.min_items:
            bad_request("Field '%s' must contain at least %d element(s)."
                        % (rule.name, rule.min_items))
        for element in value:
            if not isinstance(element, str) or not element.strip():
                bad_request("Field '%s' must contain non-empty strings." % rule.name)
            if rule.max_len is not None and len(element) > rule.max_len:
                bad_request("Field '%s' elements must be at most %d characters."
                            % (rule.name, rule.max_len))
        return list(value)
    bad_request("Field '%s' has an unsupported type." % rule.name)


def parse_input(rules, body=None, allow_unknown=True):
    """Validate a request body against a list of F rules (ladder rung 3)."""
    body = raw_body() if body is None else body
    out = {}
    for rule in rules:
        if rule.name not in body:
            if rule.required:
                bad_request("Field '%s' is required." % rule.name)
            continue
        out[rule.name] = validate_field(rule, body[rule.name])
    if not allow_unknown:
        for key in body:
            if all(rule.name != key for rule in rules):
                bad_request("Unknown field '%s'." % key)
    return out


# ---------------------------------------------------------------------------
# Pagination and list filtering (rung 3 for limit/offset)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


def pagination():
    args = request.args
    limit = DEFAULT_LIMIT
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not re.fullmatch(r"-?\d+", raw.strip() or ""):
            bad_request("Query parameter 'limit' must be an integer.")
        limit = int(raw.strip())
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            bad_request("Query parameter 'limit' must be between %d and %d."
                        % (MIN_LIMIT, MAX_LIMIT))
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not re.fullmatch(r"-?\d+", raw.strip() or ""):
            bad_request("Query parameter 'offset' must be an integer.")
        offset = int(raw.strip())
        if offset < 0:
            bad_request("Query parameter 'offset' must be >= 0.")
    return limit, offset


def filters(spec):
    """spec maps query-parameter name -> None (free id) or a tuple of legal enum
    members.  Unknown enum members are a rung-3 400, per validations[3]."""
    out = {}
    for name, allowed in spec.items():
        if name not in request.args:
            continue
        raw = request.args.get(name)
        if raw is None or raw == "":
            bad_request("Query parameter '%s' may not be empty." % name)
        if allowed is not None and raw not in allowed:
            bad_request("Query parameter '%s' must be one of %s."
                        % (name, ", ".join(allowed)))
        out[name] = raw
    return out


def apply_filters(rows, active):
    result = []
    for row in rows:
        keep = True
        for key, wanted in active.items():
            if row.get(key) != wanted:
                keep = False
                break
        if keep:
            result.append(row)
    return result


def chrono(rows):
    """Deterministic chronological ordering.  The logical clock does not move on
    its own, so created_at ties are broken by the internal insertion sequence."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def public(row):
    """Strip internal bookkeeping keys before serialization."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]


# ---------------------------------------------------------------------------
# Lookup helpers (ladder rungs 4 and 5 share these)
# ---------------------------------------------------------------------------
NOT_FOUND_FOR = {
    "units": "ERR_UNIT_NOT_FOUND",
    "patients": "ERR_PATIENT_NOT_FOUND",
    "woc_nurses": "ERR_NURSE_NOT_FOUND",
    "consult_requests": "ERR_CONSULT_NOT_FOUND",
    "skin_assessments": "ERR_ASSESSMENT_NOT_FOUND",
    "pressure_injury_cases": "ERR_CASE_NOT_FOUND",
    "survey_rounds": "ERR_SURVEY_ROUND_NOT_FOUND",
    "survey_observations": "ERR_OBSERVATION_NOT_FOUND",
    "support_surfaces": "ERR_SURFACE_NOT_FOUND",
    "support_surface_orders": "ERR_ORDER_NOT_FOUND",
    "formulary_products": "ERR_PRODUCT_NOT_FOUND",
    "dressing_protocols": "ERR_PROTOCOL_NOT_FOUND",
    "ostomy_education_plans": "ERR_PLAN_NOT_FOUND",
}


def store(name):
    return getattr(DB, name)


def find(name, row_id):
    return store(name).get(row_id)


def must(name, row_id):
    row = store(name).get(row_id)
    if row is None:
        fail(NOT_FOUND_FOR[name])
    return row


def insert(name, row):
    store(name)[row["id"]] = row
    return row


def rows_of(name):
    return list(store(name).values())


# ---------------------------------------------------------------------------
# Optimistic concurrency (rung 20)
# ---------------------------------------------------------------------------
def check_patient_version(patient, expected):
    if expected is None:
        return
    if int(patient.get("version", 1)) != int(expected):
        fail("ERR_STALE_PATIENT_VERSION")


def check_unit_version(unit, expected):
    if expected is None:
        return
    if int(unit.get("version", 1)) != int(expected):
        fail("ERR_STALE_UNIT_VERSION")
