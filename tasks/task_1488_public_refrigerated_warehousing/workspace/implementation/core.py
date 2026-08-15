"""Core plumbing: logical clock, error type, response envelope, validation,
authentication, and the in-memory store.

Storage is in-memory only (module-level dicts). The store starts empty on every
process boot; nothing is seeded. The logical clock starts at exactly
2026-08-01T00:00:00Z and advances only via POST /api/_clock/set_current_utc.
"""

import random
import re
import string
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

# ----------------------------------------------------------------------------
# Logical clock
# ----------------------------------------------------------------------------

CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return CLOCK["now"]


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_dt(dt):
    return None if dt is None else fmt_ts(dt)


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_datetime(value, field="datetime"):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 400, "field %s must be an ISO 8601 datetime string" % field)
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "field %s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field="date"):
    if not isinstance(value, str) or not _ISO_DATE_RE.match(value):
        raise ApiError("ERR_VALIDATION", 400, "field %s must be an ISO date (YYYY-MM-DD)" % field)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "field %s is not a valid calendar date" % field)
    return value


# ----------------------------------------------------------------------------
# Errors and response envelope
# ----------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def _meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": fmt_ts(clock_now())}


def ok_object(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_body(error_id, message):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    })


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        body = error_body(err.error_id, err.message)
        return body, err.status

    @app.errorhandler(404)
    def _handle_404(err):
        return error_body("ERR_NOT_FOUND", "resource not found"), 404

    @app.errorhandler(405)
    def _handle_405(err):
        return error_body("ERR_NOT_FOUND", "method not allowed"), 405

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return error_body("ERR_VALIDATION", "unhandled server error: %s" % err), 500


# ----------------------------------------------------------------------------
# Request body / field validation
# ----------------------------------------------------------------------------

def get_body():
    """Return the JSON object body, or {} when no body was sent."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "request body must be a JSON object")
    return data


def req_present(data, name):
    if name not in data or data[name] is None:
        raise ApiError("ERR_VALIDATION", 400, "missing required field: %s" % name)
    return data[name]


def as_str(value, name):
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_VALIDATION", 400, "field %s must be a non-empty string" % name)
    return value


def as_int(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", 400, "field %s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", 400, "field %s must be >= %d" % (name, minimum))
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise ApiError("ERR_VALIDATION", 400, "field %s must be a boolean" % name)
    return value


def as_enum(value, name, choices):
    if not isinstance(value, str) or value not in choices:
        raise ApiError("ERR_VALIDATION", 400, "field %s must be one of %s" % (name, "/".join(choices)))
    return value


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, "field %s must be a number" % name)
    return value


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def list_response(records, view_fn):
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([view_fn(r) for r in page], limit, offset, total)


# ----------------------------------------------------------------------------
# Authentication / authorization
# ----------------------------------------------------------------------------

ALL_ROLES = ("CustomerAdmin", "WarehouseOperator", "QualityManager", "ClaimsAdjuster", "BillingAdmin")


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or unrecognized authentication headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "role %s may not perform this operation" % role)


def check_ownership(role, uid, customer_id):
    if role == "CustomerAdmin" and customer_id != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "resource belongs to a different customer")


# ----------------------------------------------------------------------------
# In-memory store
# ----------------------------------------------------------------------------

DB = {
    "customers": {},
    "rate_cards": {},
    "zones": {},
    "receipts": {},
    "lots": {},
    "pallets": {},
    "orders": {},
    "allocations": {},
    "cells": {},
    "bookings": {},
    "excursions": {},
    "recalls": {},
    "claims": {},
    "invoices": {},
}

_SEQ = {"value": 0}


def new_record(fields):
    _SEQ["value"] += 1
    ts = fmt_ts(clock_now())
    record = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": _SEQ["value"],
    }
    record.update(fields)
    return record


def touch(record):
    record["updated_at"] = fmt_ts(clock_now())
    record["version"] += 1


def get_or_404(collection, rid, label=None):
    rec = DB[collection].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "%s not found" % (label or collection))
    return rec
