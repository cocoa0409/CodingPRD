"""Shared validation, pagination, and recompute helpers."""
from flask import request

import errors
from errors import ApiError
from db import db, now_iso

# Pagination defaults
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def get_json_body():
    if request.data:
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
    else:
        body = {}
    if body is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Malformed JSON body.")
    if not isinstance(body, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Body must be a JSON object.")
    return body


def parse_pagination():
    """Parse limit/offset query params. Invalid -> ERR_INVALID_REQUEST."""
    args = request.args
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "limit out of range.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "offset must be an integer.")
        if offset < 0:
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "offset must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    return items[offset:offset + limit]


def touch(entity):
    """Refresh updated_at and bump version on a versioned entity."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


# --- typed field readers (raise ERR_INVALID_REQUEST on violation) ---

def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"{field} must be a non-empty string.")
    return val


def opt_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"{field} must be a boolean.")
    return val


def require_number_positive(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"{field} must be a number.")
    if val <= 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"{field} must be > 0.")
    return val


def require_int_min(body, field, minimum):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"{field} must be an integer.")
    if val < minimum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"{field} must be >= {minimum}.")
    return val


def require_int_range(body, field, lo, hi):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"{field} must be an integer.")
    if val < lo or val > hi:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"{field} out of range.")
    return val


def opt_enum(body, field, members, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if val not in members:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"{field} invalid enum member.")
    return val


def require_enum(body, field, members):
    val = body.get(field)
    if val not in members:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"{field} invalid enum member.")
    return val


# --- existence lookups ---

def get_center_or_404(center_id):
    c = db.transit_centers.get(center_id)
    if c is None:
        raise ApiError(errors.ERR_CENTER_NOT_FOUND, 404, "Transit center not found.")
    return c


def get_driver_or_404(driver_id):
    d = db.drivers.get(driver_id)
    if d is None:
        raise ApiError(errors.ERR_DRIVER_NOT_FOUND, 404, "Driver not found.")
    return d


def get_parcel_or_404(parcel_id):
    p = db.parcels.get(parcel_id)
    if p is None:
        raise ApiError(errors.ERR_PARCEL_NOT_FOUND, 404, "Parcel not found.")
    return p


def get_route_or_404(route_id):
    r = db.routes.get(route_id)
    if r is None:
        raise ApiError(errors.ERR_ROUTE_NOT_FOUND, 404, "Route not found.")
    return r


def get_stop_or_404(stop_id):
    s = db.stops.get(stop_id)
    if s is None:
        raise ApiError(errors.ERR_STOP_NOT_FOUND, 404, "Stop not found.")
    return s


def get_appointment_or_404(appt_id):
    a = db.appointments.get(appt_id)
    if a is None:
        raise ApiError(errors.ERR_APPOINTMENT_NOT_FOUND, 404, "Appointment not found.")
    return a
