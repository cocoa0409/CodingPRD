"""Auth header extraction, RBAC, path resolution and body schema helpers."""

from decimal import Decimal, InvalidOperation

from flask import g, request

from db import db, parse_instant
from errors import ApiError, fail

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_AUTHORITY_OFFICER = "AuthorityOfficer"
ROLE_CONCESSIONAIRE = "Concessionaire"
ROLE_LENDER_AGENT = "LenderAgent"
ROLE_INDEPENDENT_CERTIFIER = "IndependentCertifier"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_AUTHORITY_OFFICER,
    ROLE_CONCESSIONAIRE,
    ROLE_LENDER_AGENT,
    ROLE_INDEPENDENT_CERTIFIER,
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def require_auth(*allowed):
    """Authenticate (PRD 2.1) then authorise the presented role."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED")
    if not role or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED")
    g.user_id = str(user_id)
    g.role = role
    if allowed and role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED")
    return g.user_id, g.role


def actor():
    return g.user_id


def role():
    return g.role


def owner_guard(concession):
    """A Concessionaire caller must be the owning sponsor vehicle (PRD 2.1)."""
    if g.role == ROLE_CONCESSIONAIRE and concession.get("concessionaire_id") != g.user_id:
        fail("ERR_NOT_CONCESSION_PARTY")
    return concession


def sod_guard(other_user_id):
    """Segregation of duties (PRD 2.8): the two halves need different users."""
    if other_user_id is not None and other_user_id == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")


# ---------------------------------------------------------------- lookups
def _get(table, row_id, error_id):
    row = db.tables[table].get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id)
    return row


def get_concessionaire(row_id):
    return _get("concessionaires", row_id, "ERR_CONCESSIONAIRE_NOT_FOUND")


def get_concession(row_id):
    return _get("concessions", row_id, "ERR_CONCESSION_NOT_FOUND")


def get_milestone(row_id):
    return _get("milestones", row_id, "ERR_DRAWDOWN_MILESTONE_NOT_FOUND")


def get_period(row_id):
    return _get("periods", row_id, "ERR_SERVICE_PERIOD_NOT_FOUND")


def get_report(row_id):
    return _get("reports", row_id, "ERR_PERFORMANCE_REPORT_NOT_FOUND")


def get_event(row_id):
    return _get("events", row_id, "ERR_DEDUCTION_EVENT_NOT_FOUND")


def get_dispute(row_id):
    return _get("disputes", row_id, "ERR_DEDUCTION_DISPUTE_NOT_FOUND")


def get_claim(row_id):
    return _get("claims", row_id, "ERR_RELIEF_CLAIM_NOT_FOUND")


def get_txn(row_id):
    return _get("reserve_txns", row_id, "ERR_RESERVE_TRANSACTION_NOT_FOUND")


def get_refi(row_id):
    return _get("refis", row_id, "ERR_REFINANCING_EVENT_NOT_FOUND")


def get_action(row_id):
    return _get("enforcements", row_id, "ERR_ENFORCEMENT_ACTION_NOT_FOUND")


def concession_of(row):
    return db.tables["concessions"][row["concession_id"]]


def concession_of_period(period):
    return db.tables["concessions"][period["concession_id"]]


def period_of_report(report):
    return db.tables["periods"][report["service_period_id"]]


def period_of_event(event):
    return db.tables["periods"][event["service_period_id"]]


def event_of_dispute(dispute):
    return db.tables["events"][dispute["deduction_event_id"]]


# ---------------------------------------------------------------- body
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True, force=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _missing(name):
    fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)


def req_str(data, name, max_len=None, required=True, default=None, allow_empty=False):
    if name not in data or data.get(name) is None:
        if required:
            _missing(name)
        return default
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' exceeds %d characters." % (name, max_len))
    return value


def req_int(data, name, minimum=None, maximum=None, required=True, default=None):
    if name not in data or data.get(name) is None:
        if required:
            _missing(name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (name, maximum))
    return value


def req_ratio(data, name, minimum, maximum, max_dp, required=True, default=None,
              exclusive_min=False):
    if name not in data or data.get(name) is None:
        if required:
            _missing(name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    exponent = dec.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -max_dp:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' admits at most %d decimal places." % (name, max_dp))
    if exclusive_min:
        if dec <= Decimal(str(minimum)):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be > %s." % (name, minimum))
    elif dec < Decimal(str(minimum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, minimum))
    if dec > Decimal(str(maximum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (name, maximum))
    return value


def req_enum(data, name, allowed, required=True, default=None):
    if name not in data or data.get(name) is None:
        if required:
            _missing(name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def req_instant(data, name, required=True, default=None):
    """Returns (raw_string, datetime). The raw string is echoed back verbatim."""
    if name not in data or data.get(name) is None:
        if required:
            _missing(name)
        return default, None
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp." % name)
    parsed = parse_instant(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp." % name)
    return value, parsed


def as_instant(value):
    parsed = parse_instant(value) if value is not None else None
    return parsed
