"""Envelope, authentication, pagination and field validation helpers."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import enc, ordered, parse_iso

ROLES = [
    "OpticsEngineer",
    "ProcurementOfficer",
    "ProcessTechnician",
    "MetrologyTechnician",
    "QualityManager",
    "ExportComplianceOfficer",
    "PlantAdmin",
]
ALL_ROLES = list(ROLES)

_ALPHABET = string.ascii_lowercase + string.digits


# --------------------------------------------------------------------- envelope
def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(16))


def _now_iso3():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def base_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _now_iso3()}


def ok(data, code=200):
    return {"meta": base_meta(), "response_type": "object", "data": enc(data)}, code


def ok_list(rows, serializer, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    return {
        "meta": meta,
        "response_type": "array",
        "data": [enc(serializer(r)) for r in window],
    }, 200


def error_body(err):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }, err.http_status


# ----------------------------------------------------------------------- auth
def authenticate(allowed_roles):
    """Priority 1 then priority 2 of the §1.4 adjudication order."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


# ----------------------------------------------------------------------- body
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        raw = request.get_data() or b""
        if raw.strip():
            raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, why))


# ----------------------------------------------------------------- pagination
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("limit", "must be an integer.")
        if limit < 1 or limit > 100:
            bad("limit", "must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("offset", "must be an integer.")
        if offset < 0:
            bad("offset", "must be >= 0.")
    return limit, offset


def filt(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


# ----------------------------------------------------------------- validators
_MISSING = object()


def present(body, name):
    return name in body and body[name] is not None


def v_str(body, name, required=True, default=None, min_len=1, max_len=None):
    if name not in body or body[name] is None:
        if required:
            bad(name, "is required.")
        return default
    value = body[name]
    if not isinstance(value, str):
        bad(name, "must be a string.")
    if min_len is not None and len(value) < min_len:
        bad(name, "must be at least %d characters." % min_len)
    if max_len is not None and len(value) > max_len:
        bad(name, "must be at most %d characters." % max_len)
    return value


def v_enum(body, name, allowed, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            bad(name, "is required.")
        return default
    value = body[name]
    if not isinstance(value, str):
        bad(name, "must be a string.")
    if value not in allowed:
        bad(name, "must be one of %s." % ", ".join(sorted(allowed)))
    return value


def v_num(body, name, required=True, default=None, gt=None, ge=None, le=None, lt=None):
    if name not in body or body[name] is None:
        if required:
            bad(name, "is required.")
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(name, "must be a number.")
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad(name, "must be a number.")
    if not dec.is_finite():
        bad(name, "must be a finite number.")
    _range_check(name, dec, gt, ge, le, lt)
    return dec


def v_int(body, name, required=True, default=None, gt=None, ge=None, le=None, lt=None):
    if name not in body or body[name] is None:
        if required:
            bad(name, "is required.")
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad(name, "must be an integer.")
    _range_check(name, Decimal(value), gt, ge, le, lt)
    return int(value)


def _range_check(name, dec, gt, ge, le, lt):
    if gt is not None and not dec > Decimal(str(gt)):
        bad(name, "must be greater than %s." % gt)
    if ge is not None and not dec >= Decimal(str(ge)):
        bad(name, "must be >= %s." % ge)
    if le is not None and not dec <= Decimal(str(le)):
        bad(name, "must be <= %s." % le)
    if lt is not None and not dec < Decimal(str(lt)):
        bad(name, "must be less than %s." % lt)


def v_ts(body, name, required=True, default=None):
    """Returns (raw_string, datetime) or (default, None)."""
    if name not in body or body[name] is None:
        if required:
            bad(name, "is required.")
        return default, None
    value = body[name]
    if not isinstance(value, str):
        bad(name, "must be an ISO 8601 UTC timestamp string.")
    dt = parse_iso(value)
    if dt is None:
        bad(name, "must be a valid ISO 8601 UTC timestamp.")
    return value, dt


def v_fk(body, name, collection, not_found_error, required=True):
    """Priority 4: body foreign keys resolve, in the endpoint's declared order.

    A field that is absent, null or of the wrong type is not an id at all; it is
    left to the priority-5 field validation below.
    """
    if name not in body or body[name] is None:
        return None
    value = body[name]
    if not isinstance(value, str):
        return None
    row = collection.get(value)
    if row is None:
        raise ApiError(not_found_error)
    return row


def need_fk(body, name, row):
    """Priority 5 companion of v_fk: the field itself must be a non-empty string."""
    if name not in body or body[name] is None:
        bad(name, "is required.")
    if not isinstance(body[name], str) or not body[name]:
        bad(name, "must be a string id.")
    return row


# -------------------------------------------------------------- path lookup
def path_row(collection, row_id, not_found_error):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(not_found_error)
    return row


# ------------------------------------------------------------------------ OCC
def occ(body, field, row, stale_error):
    """Priority 6. The guard field is mandatory; omission is ERR_INVALID_REQUEST."""
    if field not in body or body[field] is None:
        bad(field, "is required.")
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad(field, "must be an integer.")
    if int(value) != int(row["version"]):
        raise ApiError(stale_error)


def rows_of(collection, predicate):
    return ordered([r for r in collection.values() if predicate(r)])
