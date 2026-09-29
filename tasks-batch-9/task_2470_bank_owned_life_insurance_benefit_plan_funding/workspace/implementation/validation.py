"""Auth, schema validation, pagination and lookup helpers.

Validation ladder (PRD 2.11): header presence -> role eligibility -> carrier
scoping -> request schema -> path existence -> body foreign keys -> terminal
state -> transition legality -> optimistic concurrency -> four-eyes -> consent
family -> diligence family -> referential family -> temporal family ->
exposure family -> fiscal family.
"""

from decimal import Decimal, InvalidOperation

from flask import g, request

from errors import ApiError
from store import db
from util import parse_datetime, to_decimal

ROLES = (
    "PlatformAdmin",
    "BenefitsAnalyst",
    "RiskOfficer",
    "TreasuryController",
    "ClaimsAdministrator",
    "BoardSecretary",
    "CarrierLiaison",
)


def authorize(allowed_roles):
    """Headers first, then role eligibility (PRD 2.1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def actor():
    return g.user_id


def is_liaison():
    return getattr(g, "role", None) == "CarrierLiaison"


def liaison_carrier_id():
    return g.user_id


def scope_check(carrier_id):
    """CarrierLiaison may only address its own carrier's resources."""
    if is_liaison() and carrier_id is not None and carrier_id != g.user_id:
        raise ApiError("ERR_CARRIER_SCOPE_VIOLATION")


# --------------------------------------------------------------------------
# request body / query schema validation
# --------------------------------------------------------------------------

_MISSING = object()


def json_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def _bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, detail))


def get_string(body, field, required=True, default=None):
    value = body.get(field, _MISSING)
    if value is _MISSING or value is None:
        if required:
            _bad(field, "is required")
        return default
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if value.strip() == "":
        _bad(field, "must not be empty")
    return value


def get_enum(body, field, members, required=True, default=None):
    value = body.get(field, _MISSING)
    if value is _MISSING or value is None:
        if required:
            _bad(field, "is required")
        return default
    if not isinstance(value, str) or value not in members:
        _bad(field, "must be one of %s" % ", ".join(members))
    return value


def get_bool(body, field, required=False, default=None):
    value = body.get(field, _MISSING)
    if value is _MISSING or value is None:
        if required:
            _bad(field, "is required")
        return default
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def get_int(body, field, required=True, default=None, minimum=None, maximum=None,
            exclusive_minimum=None):
    value = body.get(field, _MISSING)
    if value is _MISSING or value is None:
        if required:
            _bad(field, "is required")
        return default
    if isinstance(value, bool):
        _bad(field, "must be an integer")
    if isinstance(value, int):
        ivalue = value
    elif isinstance(value, float) and float(value).is_integer():
        ivalue = int(value)
    else:
        _bad(field, "must be an integer")
    if minimum is not None and ivalue < minimum:
        _bad(field, "must be >= %s" % minimum)
    if exclusive_minimum is not None and ivalue <= exclusive_minimum:
        _bad(field, "must be > %s" % exclusive_minimum)
    if maximum is not None and ivalue > maximum:
        _bad(field, "must be <= %s" % maximum)
    return ivalue


def get_money(body, field, required=True, default=None, allow_negative=False,
              positive_only=False):
    """USD amounts: numeric, at most 2 decimals, non-negative unless allowed."""
    value = body.get(field, _MISSING)
    if value is _MISSING or value is None:
        if required:
            _bad(field, "is required")
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        _bad(field, "must be a number")
    try:
        amount = to_decimal(value)
    except (InvalidOperation, ValueError):
        _bad(field, "must be a number")
    if amount != amount or amount.is_infinite():
        _bad(field, "must be a finite number")
    if amount.as_tuple().exponent < -2:
        _bad(field, "must carry at most 2 decimal places")
    if not allow_negative and amount < 0:
        _bad(field, "must not be negative")
    if positive_only and amount <= 0:
        _bad(field, "must be greater than zero")
    return amount.quantize(Decimal("0.01"))


def get_datetime(body, field, required=True, default=None):
    """Returns (raw_string, datetime) so the input value is echoed verbatim."""
    value = body.get(field, _MISSING)
    if value is _MISSING or value is None:
        if required:
            _bad(field, "is required")
        return default, None
    if not isinstance(value, str):
        _bad(field, "must be an ISO 8601 UTC datetime string")
    parsed = parse_datetime(value)
    if parsed is None:
        _bad(field, "must be a well-formed ISO 8601 UTC datetime")
    return value, parsed


def get_id(body, field, required=True):
    value = body.get(field, _MISSING)
    if value is _MISSING or value is None:
        if required:
            _bad(field, "is required")
        return None
    if not isinstance(value, str) or value.strip() == "":
        _bad(field, "must be a string identifier")
    return value


# --------------------------------------------------------------------------
# pagination / query filters
# --------------------------------------------------------------------------


def pagination():
    args = request.args
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be >= 0")
    return limit, offset


def query_enum(field, members):
    value = request.args.get(field)
    if value is None:
        return None
    if value not in members:
        _bad(field, "must be one of %s" % ", ".join(members))
    return value


def query_bool(field):
    value = request.args.get(field)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    _bad(field, "must be a boolean")


def query_int(field):
    value = request.args.get(field)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        _bad(field, "must be an integer")


def query_str(field):
    return request.args.get(field)


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------


def _find(collection, identifier, error_id):
    if identifier is None:
        raise ApiError(error_id)
    rec = collection.get(identifier)
    if rec is None:
        raise ApiError(error_id)
    return rec


def find_carrier(identifier):
    return _find(db.carriers, identifier, "ERR_CARRIER_NOT_FOUND")


def find_product_type(identifier):
    return _find(db.product_types, identifier, "ERR_PRODUCT_TYPE_NOT_FOUND")


def find_review(identifier):
    return _find(db.diligence_reviews, identifier, "ERR_REVIEW_NOT_FOUND")


def find_employee(identifier):
    return _find(db.employees, identifier, "ERR_EMPLOYEE_NOT_FOUND")


def find_purchase_request(identifier):
    return _find(db.purchase_requests, identifier, "ERR_REQUEST_NOT_FOUND")


def find_policy(identifier):
    return _find(db.policies, identifier, "ERR_POLICY_NOT_FOUND")


def find_claim(identifier):
    return _find(db.death_claims, identifier, "ERR_CLAIM_NOT_FOUND")


def find_plan(identifier):
    return _find(db.nqdc_plans, identifier, "ERR_PLAN_NOT_FOUND")


def find_analysis(identifier):
    return _find(db.exchange_analyses, identifier, "ERR_ANALYSIS_NOT_FOUND")


def find_consent(identifier):
    return _find(db.consent_records, identifier, "ERR_RECORD_NOT_FOUND")


def find_valuation(identifier):
    return _find(db.policy_valuations, identifier, "ERR_RECORD_NOT_FOUND")


def find_allocation(identifier):
    return _find(db.beneficiary_allocations, identifier, "ERR_RECORD_NOT_FOUND")


def find_liability(identifier):
    return _find(db.nqdc_liabilities, identifier, "ERR_RECORD_NOT_FOUND")


def find_capital_position(identifier):
    return _find(db.capital_positions, identifier, "ERR_RECORD_NOT_FOUND")


def find_assessment(identifier):
    return _find(db.risk_assessments, identifier, "ERR_RECORD_NOT_FOUND")


# --------------------------------------------------------------------------
# state guards
# --------------------------------------------------------------------------


def guard_terminal(current, terminal_states):
    if current in terminal_states:
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")


def guard_transition(condition):
    if not condition:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
