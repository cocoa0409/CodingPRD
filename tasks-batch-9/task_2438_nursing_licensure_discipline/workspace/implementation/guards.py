"""Rejection-ladder guards: auth, RBAC, path/body resolution, pagination, body validation."""
from decimal import Decimal, InvalidOperation

from flask import request

import store
from errors import ApiError, fail
from timeutil import parse_dt

ROLES = (
    "SystemAdmin",
    "LicensureAnalyst",
    "Investigator",
    "BoardMember",
    "MonitoringCoordinator",
    "Applicant",
)

ALL_STAFF = (
    "SystemAdmin",
    "LicensureAnalyst",
    "Investigator",
    "BoardMember",
    "MonitoringCoordinator",
)


# --------------------------------------------------------------------------
# ladder steps 1 and 2
# --------------------------------------------------------------------------
def auth(*allowed_roles):
    """Validate the two headers, then the role authorisation. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail("ERR_UNAUTHENTICATED")
    if not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE")
    return str(user_id), role


# --------------------------------------------------------------------------
# ladder steps 3 and 4 -- identifier resolution
# --------------------------------------------------------------------------
_COLLECTIONS = {
    "board": ("boards", "ERR_BOARD_CONFIG_NOT_FOUND"),
    "program": ("programs", "ERR_PROGRAM_NOT_FOUND"),
    "nurse": ("nurses", "ERR_NURSE_NOT_FOUND"),
    "application": ("applications", "ERR_APPLICATION_NOT_FOUND"),
    "license": ("licenses", "ERR_LICENSE_NOT_FOUND"),
    "renewal": ("renewals", "ERR_RENEWAL_NOT_FOUND"),
    "ce_record": ("ce_records", "ERR_CE_RECORD_NOT_FOUND"),
    "complaint": ("complaints", "ERR_COMPLAINT_NOT_FOUND"),
    "evidence_request": ("evidence_requests", "ERR_EVIDENCE_REQUEST_NOT_FOUND"),
    "agreement": ("agreements", "ERR_MONITORING_AGREEMENT_NOT_FOUND"),
    "proceeding": ("proceedings", "ERR_PROCEEDING_NOT_FOUND"),
    "report": ("reports", "ERR_NOTIFICATION_REPORT_NOT_FOUND"),
}


def find(kind, ident):
    attr, err = _COLLECTIONS[kind]
    table = getattr(store.STORE, attr)
    if not isinstance(ident, str):
        fail(err)
    rec = table.get(ident)
    if rec is None:
        fail(err)
    return rec


def find_opt(kind, ident):
    """Resolve a body-supplied parent id only when it is actually supplied."""
    if ident is None:
        return None
    return find(kind, ident)


# --------------------------------------------------------------------------
# ladder step 5 -- ownership
# --------------------------------------------------------------------------
def own_nurse(role, user_id, nurse_id):
    if role != "Applicant":
        return
    if nurse_id is None or str(user_id) != str(nurse_id):
        fail("ERR_NOT_RESOURCE_OWNER")


def nurse_of_renewal(renewal):
    lic = store.STORE.licenses.get(renewal.get("license_id"))
    if lic is None:
        return None
    return lic.get("nurse_id")


def nurse_of_ce_record(ce):
    ren = store.STORE.renewals.get(ce.get("renewal_application_id"))
    if ren is None:
        return None
    return nurse_of_renewal(ren)


# --------------------------------------------------------------------------
# ladder step 6 -- body well-formedness
# --------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST")
    return parsed


def present(b, name):
    return name in b and b[name] is not None


def req_field(b, name):
    if not present(b, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return b[name]


def req_string(b, name):
    v = req_field(b, name)
    if not isinstance(v, str) or not v.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % name)
    return v


def opt_string(b, name, default=None):
    if not present(b, name):
        return default
    v = b[name]
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    return v


def req_enum(b, name, allowed):
    v = req_field(b, name)
    if not isinstance(v, str) or v not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return v


def opt_enum(b, name, allowed, default=None):
    if not present(b, name):
        return default
    return req_enum(b, name, allowed)


def _as_int(value, name):
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)


def req_int(b, name, minimum=None, maximum=None):
    v = _as_int(req_field(b, name), name)
    _range(v, name, minimum, maximum)
    return v


def opt_int(b, name, default=None, minimum=None, maximum=None):
    if not present(b, name):
        return default
    v = _as_int(b[name], name)
    _range(v, name, minimum, maximum)
    return v


def _range(v, name, minimum, maximum):
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % name)
    if maximum is not None and v > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % name)


def _as_dec(value, name):
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)


def req_number(b, name, minimum=None):
    v = _as_dec(req_field(b, name), name)
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % name)
    return v


def opt_number(b, name, default=None, minimum=None, exclusive_minimum=None):
    if not present(b, name):
        return default
    v = _as_dec(b[name], name)
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % name)
    if exclusive_minimum is not None and v <= exclusive_minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be greater than %s." % (name, exclusive_minimum))
    return v


def req_bool(b, name):
    v = req_field(b, name)
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return v


def opt_bool(b, name, default=None):
    if not present(b, name):
        return default
    v = b[name]
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return v


def req_datetime(b, name):
    v = req_field(b, name)
    try:
        return parse_dt(v)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)


def opt_datetime(b, name, default=None):
    if not present(b, name):
        return default
    return req_datetime(b, name)


def req_str_array(b, name):
    v = req_field(b, name)
    return _str_array(v, name)


def opt_str_array(b, name, default=None):
    if not present(b, name):
        return list(default) if default is not None else None
    return _str_array(b[name], name)


def _str_array(v, name):
    if not isinstance(v, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % name)
    out = []
    for item in v:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an array of strings." % name)
        out.append(item)
    return out


def req_obj_array(b, name):
    v = req_field(b, name)
    if not isinstance(v, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % name)
    for item in v:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an array of objects." % name)
    return v


def opt_obj_array(b, name, default=None):
    if not present(b, name):
        return list(default) if default is not None else None
    return req_obj_array(b, name)


def state_code(value, name):
    if not isinstance(value, str) or len(value) != 2 or not value.isalpha() or not value.isupper():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be exactly two uppercase letters." % name)
    return value


# --------------------------------------------------------------------------
# ladder step 7 -- pagination
# --------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except Exception:
            fail("ERR_INVALID_PAGINATION")
        if str(raw).strip() != str(limit):
            fail("ERR_INVALID_PAGINATION")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except Exception:
            fail("ERR_INVALID_PAGINATION")
        if str(raw).strip() != str(offset):
            fail("ERR_INVALID_PAGINATION")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(rows, limit, offset):
    ordered = sorted(rows, key=lambda r: r["created_at"])
    total = len(ordered)
    return ordered[offset:offset + limit], total


def filter_rows(rows, spec):
    """spec: {query_param: record_field}."""
    out = list(rows)
    for param, field in spec.items():
        value = request.args.get(param)
        if value is None:
            continue
        out = [r for r in out if r.get(field) == value]
    return out
