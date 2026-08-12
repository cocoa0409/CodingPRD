"""Auth header extraction, role checking, and request-body field validators."""
import re

from flask import request

import db
import errors
from util import parse_dt, parse_date

ROLES = {"PlatformAdmin", "MonitoringAgent", "Caregiver", "Senior", "Installer", "DeviceHub"}

TIERS = {"ESSENTIAL", "PLUS", "PREMIUM"}
CADENCES = {"NONE", "MONTHLY", "WEEKLY"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
EVENT_TYPES = {"HEARTBEAT", "MOTION", "DOOR_OPEN", "DOOR_CLOSE", "FALL_DETECTED", "PILL_DISPENSED"}
APPT_STATUSES = {"SCHEDULED", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW"}
ALERT_STATUSES = {"RAISED", "NOTIFYING", "ESCALATED", "ACKNOWLEDGED", "RESOLVED", "FALSE_ALARM"}
ALERT_TYPES = {"FALL", "INACTIVITY", "MISSED_MEDICATION", "MISSED_CHECKIN",
               "DEVICE_OFFLINE", "LOW_BATTERY", "MANUAL"}
NOTIF_STATUSES = {"SENT", "ACKED", "TIMED_OUT", "SUPERSEDED"}
DEVICE_STATUSES = {"PROVISIONED", "INSTALLED", "ONLINE", "OFFLINE", "DECOMMISSIONED"}
SCHED_STATUSES = {"ACTIVE", "ENDED"}
DOSE_STATUSES = {"PENDING", "TAKEN", "MISSED", "SKIPPED"}
CRITICALITIES = {"ROUTINE", "CRITICAL"}
CHECKIN_KINDS = {"SELF_CONFIRM", "APP_CONFIRM", "CALL", "VISIT"}
REPORT_MODES = {"PROVISIONAL", "FINAL"}
PAYMENT_OUTCOMES = {"SUCCEEDED", "FAILED"}
PRORATION_MODES = {"DAILY_PRORATE", "FULL_CYCLE_SWAP"}

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise errors.unauthenticated()
    return role, uid


def require_roles(allowed):
    role, uid = authenticate()
    if role not in allowed:
        raise errors.forbidden_role()
    return role, uid


def caller_senior_scope(role, uid):
    """For entity-backed senior-anchored roles, return the senior_id the caller
    may act on. Returns None for opaque roles (no scoping)."""
    if role == "Caregiver":
        c = db.caregivers.get(uid)
        if c is None:
            raise errors.ownership("Caregiver identity does not resolve")
        return c["senior_id"]
    if role == "Senior":
        return uid
    return None


def check_senior_scope(role, uid, senior_id):
    scope = caller_senior_scope(role, uid)
    if scope is not None and scope != senior_id:
        raise errors.ownership()


def scoped_list(role, uid, records, senior_id_param):
    """Apply caregiver/senior scoping plus optional senior_id filter to a list."""
    if role in ("Caregiver", "Senior"):
        scope = caller_senior_scope(role, uid)
        if senior_id_param is not None and senior_id_param != scope:
            raise errors.ownership()
        return [r for r in records if r.get("senior_id") == scope]
    if senior_id_param is not None:
        return [r for r in records if r.get("senior_id") == senior_id_param]
    return records


def get_body(required=True):
    raw = request.get_data()
    if not raw:
        if required:
            raise errors.invalid_request("Request body is required")
        return {}
    b = request.get_json(force=True, silent=True)
    if not isinstance(b, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return b


def _missing(k):
    return errors.invalid_request(f"Field '{k}' is required")


def req_str(b, k):
    v = b.get(k)
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field '{k}' is required and must be a string")
    return v


def opt_str(b, k, default=None):
    if k not in b or b[k] is None:
        return default
    if not isinstance(b[k], str):
        raise errors.invalid_request(f"Field '{k}' must be a string")
    return b[k]


def req_int(b, k, lo=None, hi=None):
    v = b.get(k)
    if not isinstance(v, int) or isinstance(v, bool):
        raise errors.invalid_request(f"Field '{k}' is required and must be an integer")
    if lo is not None and v < lo or hi is not None and v > hi:
        raise errors.invalid_request(f"Field '{k}' is out of range")
    return v


def opt_int(b, k, default=None, lo=None, hi=None):
    if k not in b or b[k] is None:
        return default
    v = b[k]
    if not isinstance(v, int) or isinstance(v, bool):
        raise errors.invalid_request(f"Field '{k}' must be an integer")
    if lo is not None and v < lo or hi is not None and v > hi:
        raise errors.invalid_request(f"Field '{k}' is out of range")
    return v


def req_bool(b, k):
    v = b.get(k)
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field '{k}' is required and must be a boolean")
    return v


def req_enum(b, k, members):
    if k not in b or not isinstance(b[k], str):
        raise errors.invalid_request(f"Field '{k}' is required and must be a string")
    if b[k] not in members:
        raise errors.invalid_enum(f"Field '{k}' carries an undeclared member")
    return b[k]


def opt_enum(b, k, members, default=None):
    if k not in b or b[k] is None:
        return default
    if not isinstance(b[k], str):
        raise errors.invalid_request(f"Field '{k}' must be a string")
    if b[k] not in members:
        raise errors.invalid_enum(f"Field '{k}' carries an undeclared member")
    return b[k]


def req_dt(b, k):
    v = b.get(k)
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field '{k}' is required and must be an ISO 8601 datetime")
    d = parse_dt(v)
    if d is None:
        raise errors.invalid_request(f"Field '{k}' is not a valid ISO 8601 datetime")
    return d


def req_date(b, k):
    v = b.get(k)
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field '{k}' is required and must be an ISO date")
    d = parse_date(v)
    if d is None:
        raise errors.invalid_request(f"Field '{k}' is not a valid ISO date")
    return d


def req_times_of_day(b, k):
    v = b.get(k)
    if not isinstance(v, list) or not (1 <= len(v) <= 4):
        raise errors.invalid_request(f"Field '{k}' must be an array of 1..4 'HH:MM' entries")
    out = []
    for t in v:
        if not isinstance(t, str) or not _HHMM.match(t):
            raise errors.invalid_request(f"Field '{k}' entries must be 'HH:MM' UTC times")
        out.append(t)
    for i in range(len(out) - 1):
        if out[i] >= out[i + 1]:
            raise errors.invalid_request(f"Field '{k}' entries must be ascending")
    return out


def query_enum(name, members):
    v = request.args.get(name)
    if v is None:
        return None
    if v not in members:
        raise errors.invalid_enum(f"Query parameter '{name}' carries an undeclared member")
    return v
