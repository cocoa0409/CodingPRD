"""Authentication, authorization, schema validation and pagination helpers.

The rejection ladder of PRD 2.6 is realised by calling these helpers in the
documented order from each route handler:

  1 auth -> 2 role -> 3 schema -> 4 existence -> 5 ownership -> 6 OCC
  -> 7 state guards -> 8 gate/duty -> 9 referential -> 10 temporal
  -> 11 uniqueness/sequence/content -> 12 fiscal ceilings
"""
import re

from flask import g, request

from db import db
from errors import fail
from util import now_ts, parse_date, parse_dt

ROLES = (
    "Applicant",
    "MerchantUser",
    "UnderwritingOfficer",
    "RiskAnalyst",
    "RiskCommitteeApprover",
    "PortfolioController",
)

ALL_ROLES = list(ROLES)


# --------------------------------------------------------------------------
# 1 + 2: authentication and authorization
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def actor():
    return g.get("user_id")


def role():
    return g.get("role")


# --------------------------------------------------------------------------
# version / updated_at bookkeeping (PRD 2.4 + 2.8)
# --------------------------------------------------------------------------
def touch(row):
    """Refresh updated_at and increment version once per request per entity."""
    if row is None or "version" not in row:
        return row
    touched = g.get("_touched")
    if touched is None:
        touched = set()
        g._touched = touched
    if row["id"] in touched:
        row["updated_at"] = now_ts()
        return row
    touched.add(row["id"])
    row["version"] += 1
    row["updated_at"] = now_ts()
    return row


# --------------------------------------------------------------------------
# 3: schema validation
# --------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _present(payload, name):
    return name in payload and payload[name] is not None


def require(payload, name):
    if not _present(payload, name):
        fail("ERR_INVALID_REQUEST", "Missing required field '%s'." % name)
    return payload[name]


def req_str(payload, name, min_len=1, max_len=None, pattern=None):
    value = require(payload, name)
    return _check_str(value, name, min_len, max_len, pattern)


def opt_str(payload, name, default=None, min_len=1, max_len=None, pattern=None):
    if not _present(payload, name):
        return default
    return _check_str(payload[name], name, min_len, max_len, pattern)


def _check_str(value, name, min_len, max_len, pattern):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    stripped = value.strip()
    if min_len and (len(stripped) < min_len or not stripped):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be non-blank." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' exceeds %d characters." % (name, max_len))
    if pattern is not None and not re.match(pattern, value):
        fail("ERR_INVALID_REQUEST", "Field '%s' is malformed." % name)
    return value


def _as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            return int(value)
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    return int(value)


def req_int(payload, name, lo=None, hi=None):
    value = _as_int(require(payload, name), name)
    _range(value, name, lo, hi)
    return value


def opt_int(payload, name, default=None, lo=None, hi=None):
    if not _present(payload, name):
        return default
    value = _as_int(payload[name], name)
    _range(value, name, lo, hi)
    return value


def _range(value, name, lo, hi):
    if lo is not None and value < lo:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, lo))
    if hi is not None and value > hi:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (name, hi))


def req_number(payload, name, lo=None, hi=None):
    value = require(payload, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    value = float(value)
    if lo is not None and value < lo:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, lo))
    if hi is not None and value > hi:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (name, hi))
    return value


def req_bool(payload, name):
    value = require(payload, name)
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def opt_bool(payload, name, default=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def req_enum(payload, name, allowed):
    value = require(payload, name)
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def opt_enum(payload, name, allowed, default=None):
    if not _present(payload, name):
        return default
    return req_enum(payload, name, allowed)


def req_date(payload, name):
    value = require(payload, name)
    try:
        parse_date(value)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a well-formed YYYY-MM-DD date." % name)
    return value


def req_datetime(payload, name):
    value = require(payload, name)
    try:
        return parse_dt(value)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a well-formed ISO 8601 instant." % name)


def req_str_list(payload, name):
    value = require(payload, name)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a list of strings." % name)
    return list(value)


def req_id(payload, name):
    value = require(payload, name)
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % name)
    return value


def opt_id(payload, name, default=None):
    if not _present(payload, name):
        return default
    return req_id(payload, name)


# --------------------------------------------------------------------------
# 3: pagination and collection filters (PRD 2.3)
# --------------------------------------------------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except Exception:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be within 1..100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except Exception:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must not be negative.")
    return limit, offset


def filter_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def filter_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def filter_date(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        parse_date(value)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a well-formed YYYY-MM-DD date." % name)
    return value


def filter_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)


def filter_pattern(name, pattern):
    value = filter_str(name)
    if value is None:
        return None
    if not re.match(pattern, value):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is malformed." % name)
    return value


# --------------------------------------------------------------------------
# 4: existence lookups, in the sub-order of PRD 2.6 step 4
# --------------------------------------------------------------------------
def find_application(app_id):
    row = db.applications.get(app_id)
    if row is None:
        fail("ERR_APPLICATION_NOT_FOUND", "No merchant application with id '%s'." % app_id)
    return row


def find_owner(owner_id):
    row = db.owners.get(owner_id)
    if row is None:
        fail("ERR_OWNER_NOT_FOUND", "No beneficial owner with id '%s'." % owner_id)
    return row


def find_merchant(merchant_id):
    row = db.merchants.get(merchant_id)
    if row is None:
        fail("ERR_MERCHANT_NOT_FOUND", "No merchant with id '%s'." % merchant_id)
    return row


def find_reserve_account(account_id):
    row = db.reserve_accounts.get(account_id)
    if row is None:
        fail("ERR_RESERVE_ACCOUNT_NOT_FOUND", "No reserve account with id '%s'." % account_id)
    return row


def find_batch(batch_id):
    row = db.batches.get(batch_id)
    if row is None:
        fail("ERR_BATCH_NOT_FOUND", "No settlement batch with id '%s'." % batch_id)
    return row


def find_alert(alert_id):
    row = db.alerts.get(alert_id)
    if row is None:
        fail("ERR_ALERT_NOT_FOUND", "No monitoring alert with id '%s'." % alert_id)
    return row


def find_program(program_id):
    row = db.programs.get(program_id)
    if row is None:
        fail("ERR_PROGRAM_NOT_FOUND", "No remediation program with id '%s'." % program_id)
    return row


def find_termination(decision_id):
    row = db.terminations.get(decision_id)
    if row is None:
        fail("ERR_TERMINATION_DECISION_NOT_FOUND", "No termination decision with id '%s'." % decision_id)
    return row


def find_appeal(appeal_id):
    row = db.appeals.get(appeal_id)
    if row is None:
        fail("ERR_APPEAL_NOT_FOUND", "No appeal with id '%s'." % appeal_id)
    return row


def find_forecast(forecast_id):
    row = db.forecasts.get(forecast_id)
    if row is None:
        fail("ERR_FORECAST_NOT_FOUND", "No portfolio forecast with id '%s'." % forecast_id)
    return row


# --------------------------------------------------------------------------
# 5: ownership for the two entity-backed roles (PRD 2.1)
# --------------------------------------------------------------------------
def own_application(app_id):
    if role() == "Applicant" and actor() != app_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting applicant does not own this application.")


def own_merchant(merchant_id):
    if role() == "MerchantUser" and actor() != merchant_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting merchant does not own this resource.")
