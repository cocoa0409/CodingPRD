"""Ladder rungs 1-3: authentication, role admissibility and request well-formedness."""
import functools
import re

from flask import g, request

from core import ApiError, db, parse_date, parse_instant

ROLES = (
    "RestructuringLead",
    "EmploymentCounsel",
    "BenefitsAdministrator",
    "SeparatingEmployee",
    "SystemAdmin",
)

READER_ROLES = [
    "RestructuringLead",
    "EmploymentCounsel",
    "BenefitsAdministrator",
    "SystemAdmin",
]

_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


def bad(msg=None):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def endpoint(roles):
    """Rung 1 (401) then rung 2 (403) before the handler body runs."""
    allowed = list(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not str(user_id).strip():
                raise ApiError("ERR_UNAUTHENTICATED", 401)
            if not role or not str(role).strip():
                raise ApiError("ERR_UNAUTHENTICATED", 401)
            if role not in ROLES or role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED", 403)
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def body():
    """Parsed JSON object body; an absent body is an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    payload = request.get_json(silent=True, force=True)
    if payload is None:
        raise bad("Request body is not valid JSON.")
    if not isinstance(payload, dict):
        raise bad("Request body must be a JSON object.")
    return payload


# ---------------------------------------------------------------------------
# Scalar field helpers (all raise ERR_INVALID_REQUEST / 400)
# ---------------------------------------------------------------------------
def _present(payload, key):
    return key in payload and payload[key] is not None


def req_str(payload, key, allow_empty=False):
    if not _present(payload, key):
        raise bad("Field '%s' is required." % key)
    value = payload[key]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        raise bad("Field '%s' must be non-empty." % key)
    return value


def opt_str(payload, key, default=None, allow_empty=True):
    if not _present(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        raise bad("Field '%s' must be non-empty." % key)
    return value


def req_int(payload, key, minimum=None, maximum=None):
    if not _present(payload, key):
        raise bad("Field '%s' is required." % key)
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be <= %s." % (key, maximum))
    return value


def opt_int(payload, key, default=None, minimum=None, maximum=None):
    if not _present(payload, key):
        return default
    return req_int(payload, key, minimum, maximum)


def req_num(payload, key, minimum=None, maximum=None):
    if not _present(payload, key):
        raise bad("Field '%s' is required." % key)
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % key)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be <= %s." % (key, maximum))
    return value


def req_bool(payload, key):
    if not _present(payload, key):
        raise bad("Field '%s' is required." % key)
    value = payload[key]
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % key)
    return value


def opt_bool(payload, key, default=None):
    if not _present(payload, key):
        return default
    return req_bool(payload, key)


def req_enum(payload, key, allowed):
    value = req_str(payload, key)
    if value not in allowed:
        raise bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(payload, key, allowed, default=None):
    if not _present(payload, key):
        return default
    return req_enum(payload, key, allowed)


def req_date(payload, key):
    value = req_str(payload, key)
    parsed = parse_date(value)
    if parsed is None:
        raise bad("Field '%s' must be a YYYY-MM-DD date." % key)
    return parsed


def req_state_code(payload, key):
    value = req_str(payload, key)
    if not _STATE_CODE_RE.match(value):
        raise bad("Field '%s' must be exactly two uppercase letters." % key)
    return value


def req_str_list(payload, key, allow_empty_list=True):
    if not _present(payload, key):
        raise bad("Field '%s' is required." % key)
    value = payload[key]
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array." % key)
    if not allow_empty_list and len(value) == 0:
        raise bad("Field '%s' must be a non-empty array." % key)
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            raise bad("Field '%s' must contain non-empty strings." % key)
    return value


def req_instant(payload, key):
    value = req_str(payload, key)
    parsed = parse_instant(value)
    if parsed is None:
        raise bad("Field '%s' must be an ISO-8601 instant." % key)
    return parsed


# ---------------------------------------------------------------------------
# Composite payload shapes
# ---------------------------------------------------------------------------
def parse_selection_criteria(payload):
    if "selection_criteria" not in payload or payload["selection_criteria"] is None:
        raise bad("Field 'selection_criteria' is required.")
    raw = payload["selection_criteria"]
    if not isinstance(raw, list):
        raise bad("Field 'selection_criteria' must be an array.")
    if len(raw) < 1 or len(raw) > 6:
        raise bad("Field 'selection_criteria' must hold between 1 and 6 entries.")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise bad("Each selection_criteria entry must be an object.")
        code = req_str(entry, "criterion_code")
        weight = req_int(entry, "weight_pct")
        description = opt_str(entry, "description", "")
        out.append({
            "criterion_code": code,
            "weight_pct": weight,
            "description": description,
        })
    return out


def parse_criterion_scores(payload):
    if "criterion_scores" not in payload or payload["criterion_scores"] is None:
        raise bad("Field 'criterion_scores' is required.")
    raw = payload["criterion_scores"]
    if not isinstance(raw, list):
        raise bad("Field 'criterion_scores' must be an array.")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise bad("Each criterion_scores entry must be an object.")
        code = req_str(entry, "criterion_code")
        score = req_int(entry, "score", 0, 100)
        out.append({"criterion_code": code, "score": score})
    return out


DEMOGRAPHIC_CODES = ("CLASS_A", "CLASS_B", "CLASS_C")


def parse_employee_attributes(payload):
    """Shared shape for POST /employees and each roster-import entry."""
    return {
        "full_name": req_str(payload, "full_name"),
        "job_title": req_str(payload, "job_title"),
        "birth_date": req_date(payload, "birth_date"),
        "hire_date": req_date(payload, "hire_date"),
        "annual_base_cents": req_int(payload, "annual_base_cents", 1),
        "weekly_hours": req_num(payload, "weekly_hours", 0),
        "demographic_code": req_enum(payload, "demographic_code", DEMOGRAPHIC_CODES),
        "monthly_premium_cents": opt_int(payload, "monthly_premium_cents", 90000, 0),
    }


# ---------------------------------------------------------------------------
# Query string
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise bad("Query parameter 'limit' must be an integer.")
        if str(raw).strip() != str(limit):
            raise bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise bad("Query parameter 'offset' must be an integer.")
        if str(raw).strip() != str(offset):
            raise bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad("Query parameter 'offset' must not be negative.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Ladder rungs 4-5: existence
# ---------------------------------------------------------------------------
_NOT_FOUND = {
    "plans": "ERR_PLAN_NOT_FOUND",
    "sites": "ERR_SITE_NOT_FOUND",
    "employees": "ERR_EMPLOYEE_NOT_FOUND",
    "selections": "ERR_SELECTION_NOT_FOUND",
    "analyses": "ERR_ANALYSIS_NOT_FOUND",
    "disclosures": "ERR_DISCLOSURE_NOT_FOUND",
    "notices": "ERR_NOTICE_NOT_FOUND",
    "offers": "ERR_OFFER_NOT_FOUND",
    "restrictions": "ERR_RESTRICTION_NOT_FOUND",
    "warn_rules": "ERR_WARN_RULE_NOT_FOUND",
}


def must_exist(collection, record_id):
    table = getattr(db, collection)
    record = table.get(record_id) if isinstance(record_id, str) else None
    if record is None:
        raise ApiError(_NOT_FOUND[collection], 404)
    return record
