"""Core plumbing: in-memory store, logical clock, envelope, errors, auth, validation.

Storage is in-memory only (Python dicts). The store starts empty on every boot;
no entity is ever seeded at startup.
"""

import re
import secrets
import string
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, request

# ---------------------------------------------------------------------------
# Error catalogue (ids + HTTP statuses from SCAFFOLD.yaml §1.6)
# ---------------------------------------------------------------------------

ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                        # 403
ERR_SELF_REVIEW_FORBIDDEN = "ERR_SELF_REVIEW_FORBIDDEN"  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_VALIDATION = "ERR_VALIDATION"                      # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_REQUEST_NOT_TRIAGED = "ERR_REQUEST_NOT_TRIAGED"    # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412
ERR_ACUITY_EXCEEDS_CONFIG = "ERR_ACUITY_EXCEEDS_CONFIG"  # 422
ERR_CREW_COMPOSITION_INCOMPLETE = "ERR_CREW_COMPOSITION_INCOMPLETE"  # 422
ERR_CREW_UNAVAILABLE = "ERR_CREW_UNAVAILABLE"          # 422
ERR_DUTY_LIMIT_EXCEEDED = "ERR_DUTY_LIMIT_EXCEEDED"    # 422
ERR_INSUFFICIENT_REST = "ERR_INSUFFICIENT_REST"        # 422
ERR_SHIFT_OVERLAP = "ERR_SHIFT_OVERLAP"                # 409
ERR_BELOW_WEATHER_MINIMUMS = "ERR_BELOW_WEATHER_MINIMUMS"  # 422
ERR_ALTERNATE_REQUIRED = "ERR_ALTERNATE_REQUIRED"      # 422
ERR_WEATHER_ASSESSMENT_STALE = "ERR_WEATHER_ASSESSMENT_STALE"  # 422
ERR_AIRCRAFT_NOT_AVAILABLE = "ERR_AIRCRAFT_NOT_AVAILABLE"  # 409
ERR_AIRCRAFT_SCHEDULE_CONFLICT = "ERR_AIRCRAFT_SCHEDULE_CONFLICT"  # 409
ERR_AUTH_REQUIRED = "ERR_AUTH_REQUIRED"                # 422
ERR_REPATRIATION_NOT_READY = "ERR_REPATRIATION_NOT_READY"  # 422
ERR_MISSION_NOT_COMPLETED = "ERR_MISSION_NOT_COMPLETED"  # 409
ERR_PCR_NOT_APPROVED = "ERR_PCR_NOT_APPROVED"          # 422
ERR_PCR_WINDOW_EXPIRED = "ERR_PCR_WINDOW_EXPIRED"      # 422
ERR_TIMELY_FILING_EXPIRED = "ERR_TIMELY_FILING_EXPIRED"  # 422
ERR_LEDGER_IMBALANCE = "ERR_LEDGER_IMBALANCE"          # 422
ERR_APPEAL_LIMIT = "ERR_APPEAL_LIMIT"                  # 422
ERR_MEMBERSHIP_NOT_ELIGIBLE = "ERR_MEMBERSHIP_NOT_ELIGIBLE"  # 422
ERR_REINSTATE_WINDOW_EXPIRED = "ERR_REINSTATE_WINDOW_EXPIRED"  # 422
ERR_DOCS_INCOMPLETE = "ERR_DOCS_INCOMPLETE"            # 422
ERR_DOC_EXPIRED = "ERR_DOC_EXPIRED"                    # 422
ERR_DUPLICATE_INVOICE = "ERR_DUPLICATE_INVOICE"        # 409
ERR_DUPLICATE_REPATRIATION_CASE = "ERR_DUPLICATE_REPATRIATION_CASE"  # 409
ERR_DUPLICATE_PCR = "ERR_DUPLICATE_PCR"                # 409
ERR_GROUND_LEGS_PENDING = "ERR_GROUND_LEGS_PENDING"    # 409


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def fail(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# In-memory store + logical clock
# ---------------------------------------------------------------------------

START_OF_TIME = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0                      # global receipt/creation sequence
        self.clock = START_OF_TIME        # logical clock; never wall-clock
        self.bases = {}
        self.aircraft = {}
        self.crew_members = {}
        self.crew_shifts = {}
        self.patients = {}
        self.memberships = {}
        self.mission_requests = {}
        self.missions = {}
        self.crew_assignments = {}
        self.weather_assessments = {}
        self.ground_legs = {}
        self.bed_reservations = {}
        self.insurance_authorizations = {}
        self.invoices = {}
        self.repatriation_cases = {}
        self.patient_care_reports = {}
        self.qa_review_events = []        # FLAGGED reviews: {author_crew_id, points, created_dt, seq}


db = Store()


def next_seq():
    db.seq += 1
    return db.seq


def now_dt():
    return db.clock


def render_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    d = dt.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


def now_iso():
    return render_ts(db.clock)


def parse_dt(value):
    """Parse an ISO 8601 datetime; naive values are treated as UTC. None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        d = datetime.fromisoformat(s2)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    """Parse a strict YYYY-MM-DD date. Returns a date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Identity, ids, common fields
# ---------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def stamp_new(rec):
    ts = now_iso()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_created_dt"] = db.clock
    rec["_seq"] = next_seq()
    return rec


def stamp_new_immutable(rec):
    """WeatherAssessment: id + created_at only (no updated_at / version)."""
    ts = now_iso()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["_created_dt"] = db.clock
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Every mutation bumps version by exactly one and refreshes updated_at."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD §1.0 / PRD §2.2)
# ---------------------------------------------------------------------------


def _meta():
    return {
        "api_request_id": "req_" + "".join(
            secrets.choice(string.ascii_letters + string.digits) for _ in range(16)
        ),
        "api_request_timestamp": now_iso(),
    }


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth (PRD §2.1): X-User-ID + X-User-Role, six roles
# ---------------------------------------------------------------------------

VALID_ROLES = {
    "OpsAdmin",
    "Dispatcher",
    "MedicalDirector",
    "FlightCrew",
    "BillingSpecialist",
    "QaReviewer",
}


def current_user():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        fail(ERR_UNAUTHENTICATED, 401, "Missing or unrecognized authentication headers")
    return user_id, role


def require_roles(*roles):
    user_id, role = current_user()
    if role not in roles:
        fail(ERR_FORBIDDEN, 403, "Role %s is not permitted for this endpoint" % role)
    return user_id, role


# ---------------------------------------------------------------------------
# Request body + field validation (priority 4 -> ERR_VALIDATION 400)
# ---------------------------------------------------------------------------


def get_body():
    try:
        data = request.get_json(silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


def _missing(body, field):
    return field not in body or body[field] is None


def v_str(body, field, required=True):
    if _missing(body, field):
        if required:
            fail(ERR_VALIDATION, 400, "Field '%s' is required" % field)
        return None
    val = body[field]
    if not isinstance(val, str) or val == "":
        fail(ERR_VALIDATION, 400, "Field '%s' must be a non-empty string" % field)
    return val


def v_int(body, field, required=True, minimum=None, maximum=None):
    if _missing(body, field):
        if required:
            fail(ERR_VALIDATION, 400, "Field '%s' is required" % field)
        return None
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        fail(ERR_VALIDATION, 400, "Field '%s' must be an integer" % field)
    if minimum is not None and val < minimum:
        fail(ERR_VALIDATION, 400, "Field '%s' is below the allowed minimum" % field)
    if maximum is not None and val > maximum:
        fail(ERR_VALIDATION, 400, "Field '%s' exceeds the allowed maximum" % field)
    return val


def v_num(body, field, required=True, minimum=None, exclusive_min=False):
    if _missing(body, field):
        if required:
            fail(ERR_VALIDATION, 400, "Field '%s' is required" % field)
        return None
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        fail(ERR_VALIDATION, 400, "Field '%s' must be a number" % field)
    if minimum is not None:
        if exclusive_min and not (val > minimum):
            fail(ERR_VALIDATION, 400, "Field '%s' must be greater than %s" % (field, minimum))
        if not exclusive_min and val < minimum:
            fail(ERR_VALIDATION, 400, "Field '%s' is below the allowed minimum" % field)
    return val


def v_enum(body, field, allowed, required=True):
    if _missing(body, field):
        if required:
            fail(ERR_VALIDATION, 400, "Field '%s' is required" % field)
        return None
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        fail(ERR_VALIDATION, 400, "Field '%s' must be one of %s" % (field, sorted(allowed)))
    return val


def v_dt(body, field, required=True):
    """Returns (raw_string, parsed_datetime)."""
    if _missing(body, field):
        if required:
            fail(ERR_VALIDATION, 400, "Field '%s' is required" % field)
        return None, None
    raw = body[field]
    parsed = parse_dt(raw)
    if parsed is None:
        fail(ERR_VALIDATION, 400, "Field '%s' must be an ISO 8601 datetime" % field)
    return raw, parsed


def v_date(body, field, required=True):
    if _missing(body, field):
        if required:
            fail(ERR_VALIDATION, 400, "Field '%s' is required" % field)
        return None, None
    raw = body[field]
    parsed = parse_date(raw)
    if parsed is None:
        fail(ERR_VALIDATION, 400, "Field '%s' must be an ISO date YYYY-MM-DD" % field)
    return raw, parsed


def v_bool(body, field, required=False, default=None):
    if _missing(body, field):
        if required:
            fail(ERR_VALIDATION, 400, "Field '%s' is required" % field)
        return default
    val = body[field]
    if not isinstance(val, bool):
        fail(ERR_VALIDATION, 400, "Field '%s' must be a boolean" % field)
    return val


# ---------------------------------------------------------------------------
# Existence helpers (priority 3 -> ERR_NOT_FOUND 404)
# ---------------------------------------------------------------------------


def must_exist(table, rid, what="Resource"):
    rec = table.get(rid) if isinstance(rid, str) else None
    if rec is None:
        fail(ERR_NOT_FOUND, 404, "%s '%s' was not found" % (what, rid))
    return rec


# ---------------------------------------------------------------------------
# Pagination (SCAFFOLD §1.0 / PRD §2.3): limit/offset, defaults 10/0, 1..100
# ---------------------------------------------------------------------------


def pagination_params():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            fail(ERR_VALIDATION, 400, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            fail(ERR_VALIDATION, 400, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            fail(ERR_VALIDATION, 400, "offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            fail(ERR_VALIDATION, 400, "offset must be >= 0")
    return limit, offset


def list_response(records, serializer, filters):
    """records: iterable of stored dicts. filters: {query_param: record_field}."""
    limit, offset = pagination_params()
    items = list(records)
    for param, field in filters.items():
        raw = request.args.get(param)
        if raw is not None:
            items = [r for r in items if str(r.get(field)) == raw]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)
