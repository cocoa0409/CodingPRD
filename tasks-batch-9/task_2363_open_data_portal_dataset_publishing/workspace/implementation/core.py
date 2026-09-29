"""Foundation layer: in-memory store, logical clock, error catalogue,
response envelope, authentication and request-shape validation.

Every structural name in this module is taken verbatim from PRD.md
(§2.1 headers, §2.2 envelope, §2.3 pagination, §2.4 common fields,
§2.7 validation precedence) and the SCAFFOLD error catalogue.
"""

import itertools
import random
import string
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import g, jsonify, request

# --------------------------------------------------------------------------
# Logical clock (PRD §1: starts at 2026-08-01T00:00:00Z)
# --------------------------------------------------------------------------
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    """Pure in-memory storage.  Starts completely empty on every boot."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.departments = {}
        self.licenses = {}
        self.runners = {}
        self.datasets = {}
        self.metadata_records = {}
        self.assessments = {}
        self.pipelines = {}
        self.runs = {}
        self.versions = {}
        self.members = {}
        self.issues = {}
        self.requests = {}
        self.logical_now = CLOCK_START
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()
store_lock = threading.RLock()


def now():
    return db.logical_now


# --------------------------------------------------------------------------
# Timestamps — ISO 8601 UTC with exactly three fractional digits (PRD §2.4)
# --------------------------------------------------------------------------
def fmt_ts(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Error catalogue (PRD §5)
# --------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_DEPARTMENT_SCOPE_VIOLATION": 403,
    "ERR_MEMBER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_DEPARTMENT_SUSPENDED": 403,
    "ERR_RESTRICTED_POSTURE_TIER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DEPARTMENT_NOT_FOUND": 404,
    "ERR_LICENSE_NOT_FOUND": 404,
    "ERR_RUNNER_NOT_FOUND": 404,
    "ERR_DATASET_NOT_FOUND": 404,
    "ERR_METADATA_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_PIPELINE_NOT_FOUND": 404,
    "ERR_RUN_NOT_FOUND": 404,
    "ERR_VERSION_NOT_FOUND": 404,
    "ERR_ISSUE_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_REQUEST_NOT_FOUND": 404,
    "ERR_SHOWCASE_NOT_FOUND": 404,
    "ERR_DUPLICATE_DEPARTMENT_CODE": 409,
    "ERR_DUPLICATE_LICENSE_CODE": 409,
    "ERR_DUPLICATE_DATASET_SLUG": 409,
    "ERR_DUPLICATE_MEMBER_EMAIL": 409,
    "ERR_METADATA_RECORD_EXISTS": 409,
    "ERR_ASSESSMENT_EXISTS": 409,
    "ERR_DUPLICATE_USAGE_EPOCH": 409,
    "ERR_DUPLICATE_SHOWCASE_LABEL": 409,
    "ERR_DUPLICATE_VOTE": 409,
    "ERR_STALE_DATASET_VERSION": 412,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_DATASET_NOT_PUBLISHED": 409,
    "ERR_PIPELINE_NOT_ARMED": 409,
    "ERR_VERSION_NOT_LIVE": 409,
    "ERR_METADATA_NOT_ACCEPTED": 409,
    "ERR_PRIVACY_CLEARANCE_REQUIRED": 409,
    "ERR_AGGREGATION_UNMET": 422,
    "ERR_REIDENTIFICATION_RISK_TOO_HIGH": 422,
    "ERR_VERIFIED_CELL_SIZE_MISSING": 422,
    "ERR_LICENSE_RETIRED": 409,
    "ERR_EMBARGO_ACTIVE": 409,
    "ERR_RUN_SCHEDULE_INVALID": 422,
    "ERR_RUN_OUTSIDE_WINDOW": 422,
    "ERR_WINDOW_WRAPS_MIDNIGHT": 422,
    "ERR_RUNNER_WINDOW_CONFLICT": 409,
    "ERR_DEPARTMENT_WINDOW_CAPACITY": 409,
    "ERR_RUNNER_NOT_ACTIVE": 409,
    "ERR_METADATA_INCOMPLETE": 422,
    "ERR_ATTRIBUTION_MISSING": 422,
    "ERR_INSUFFICIENT_DEMAND": 422,
    "ERR_MEMBER_THROTTLED": 422,
    "ERR_NOT_HIGH_VALUE_ELIGIBLE": 422,
    "ERR_NO_PREDECESSOR_VERSION": 409,
    "ERR_OPEN_ISSUES_BLOCK_RETIRE": 409,
    "ERR_INSUFFICIENT_CREDITS": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def err(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Common system-managed fields (PRD §2.4)
# --------------------------------------------------------------------------
def new_row():
    stamp = now()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }
    # A row created inside this request starts at version 1; recomputes performed
    # during the same request must not push it to 2.
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    touched.add(row["id"])
    return row


def touch(row):
    """Mark a row mutated: refresh updated_at and increment version once per
    mutated row per request (PRD §2.4 / §2.11)."""
    if row is None:
        return
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    row["updated_at"] = now()
    if row["id"] in touched:
        return
    touched.add(row["id"])
    row["version"] = row["version"] + 1


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_list(rows, total, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error_body(error_id, message, http_status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        http_status,
    )


# --------------------------------------------------------------------------
# Authentication / authorisation (PRD §2.1, precedence 1 and 2)
# --------------------------------------------------------------------------
ROLES = (
    "PortalAdmin",
    "DataCoordinator",
    "PrivacyReviewer",
    "CommunityMember",
    "Anonymous",
)
ANY_ROLE = ROLES


def caller(*allowed):
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        err("ERR_UNAUTHENTICATED", "X-User-Role header is missing or unknown.")
    user_id = request.headers.get("X-User-ID")
    if user_id is not None and user_id.strip() == "":
        user_id = None
    if role != "Anonymous" and not user_id:
        err("ERR_UNAUTHENTICATED", "X-User-ID header is required for role %s." % role)
    if allowed and role not in allowed:
        err("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this endpoint." % role)
    return role, user_id


# --------------------------------------------------------------------------
# Request body / query-shape validation (PRD §2.7 priority 4)
# --------------------------------------------------------------------------
def body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None or not isinstance(parsed, dict):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _present(data, field):
    return field in data and data[field] is not None


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def req_str(data, field):
    if not _present(data, field):
        err("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, str) or value.strip() == "":
        err("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % field)
    return value


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    return value


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        err("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def opt_enum(data, field, allowed, default=None):
    if field not in data or data[field] is None:
        return default
    return req_enum(data, field, allowed)


def req_int(data, field, lo=None, hi=None):
    if not _present(data, field):
        err("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = data[field]
    if not _is_int(value):
        err("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    if lo is not None and value < lo:
        err("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (field, lo))
    if hi is not None and value > hi:
        err("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (field, hi))
    return value


def opt_int(data, field, lo=None, hi=None, default=None):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, lo, hi)


def req_num(data, field, lo=None, hi=None):
    if not _present(data, field):
        err("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = data[field]
    if not _is_num(value):
        err("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        err("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)
    if lo is not None and dec < Decimal(str(lo)):
        err("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (field, lo))
    if hi is not None and dec > Decimal(str(hi)):
        err("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (field, hi))
    return dec


def req_bool(data, field):
    if not _present(data, field):
        err("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, bool):
        err("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return value


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_bool(data, field)


def req_datetime(data, field):
    if not _present(data, field):
        err("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    parsed = parse_iso(data[field])
    if parsed is None:
        err("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % field)
    return parsed


def opt_datetime(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_datetime(data, field)


# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100.")
        if str(raw).strip() != str(limit):
            err("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "offset must be a non-negative integer.")
        if str(raw).strip() != str(offset):
            err("ERR_INVALID_REQUEST", "offset must be a non-negative integer.")
        if offset < 0:
            err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def page(rows, serializer):
    limit, offset = pagination()
    ordered = sort_rows(rows)
    total = len(ordered)
    window = ordered[offset : offset + limit]
    return ok_list([serializer(r) for r in window], total, limit, offset)
