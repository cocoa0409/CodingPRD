"""Core primitives: logical clock, in-memory store, response envelope, errors,
authentication and request-body validation.

Every structural name in this module (header names, envelope field names,
pagination parameter names, error identifiers) is taken verbatim from PRD.md
sections 2.1 - 2.9 and SCAFFOLD.yaml `response_envelope` / `errors`.
"""

import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

# ---------------------------------------------------------------------------
# Roles (PRD 2.1 - exactly seven, spelled as declared)
# ---------------------------------------------------------------------------
ROLES = (
    "ProgramAdmin",
    "IncidentLead",
    "LegalCounsel",
    "CommsLead",
    "Spokesperson",
    "SocialListener",
    "ExecSponsor",
)
# ProgramAdmin identity is opaque; the other six are entity_backed:TeamMember.
ENTITY_BACKED_ROLES = tuple(r for r in ROLES if r != "ProgramAdmin")
ALL_ROLES = list(ROLES)

HDR_USER_ID = "X-User-ID"
HDR_USER_ROLE = "X-User-Role"

# ---------------------------------------------------------------------------
# Error catalogue (PRD section 5 / SCAFFOLD 1.6)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_TEAM_MEMBER_NOT_FOUND": 404,
    "ERR_CHANNEL_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_SIGNAL_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_APPROVAL_TASK_NOT_FOUND": 404,
    "ERR_NOTICE_NOT_FOUND": 404,
    "ERR_MATERIAL_NOT_FOUND": 404,
    "ERR_INTERVIEW_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_STALE_INCIDENT_VERSION": 412,
    "ERR_STALE_CHANNEL_VERSION": 412,
    "ERR_INVALID_SIGNAL_STATE": 409,
    "ERR_INCIDENT_NOT_ACTIVATED": 409,
    "ERR_INCIDENT_ALREADY_RESOLVED": 409,
    "ERR_COMMS_POSTURE_FROZEN": 409,
    "ERR_STATEMENT_NOT_IN_REVIEW": 409,
    "ERR_STATEMENT_STATE_INVALID": 409,
    "ERR_APPROVAL_TASK_NOT_PENDING": 409,
    "ERR_ASSIGNMENT_NOT_ACKNOWLEDGED": 409,
    "ERR_ASSIGNMENT_STATE_INVALID": 409,
    "ERR_NOTICE_STATE_INVALID": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    "ERR_INTERVIEW_STATE_INVALID": 409,
    "ERR_MATERIAL_STATE_INVALID": 409,
    "ERR_REVIEW_STATE_INVALID": 409,
    "ERR_PRIVILEGE_NOT_CLEARED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_APPROVER_UNAVAILABLE": 409,
    "ERR_DUPLICATE_ASSIGNMENT_ROLE": 409,
    "ERR_STATEMENT_NOT_PUBLISHED": 409,
    "ERR_CORRECTION_STATEMENT_REQUIRED": 409,
    "ERR_NO_ESCALATED_SIGNAL": 422,
    "ERR_ESCALATION_PATH_UNVERIFIED": 422,
    "ERR_TRAINING_NOT_CURRENT": 422,
    "ERR_REVIEW_DEADLINE_PASSED": 409,
    "ERR_EMBARGO_NOT_REACHED": 409,
    "ERR_SPOKESPERSON_DOUBLE_BOOKED": 409,
    "ERR_ESCALATION_THRESHOLD_NOT_MET": 422,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_NOTICE_SEQUENCE_VIOLATION": 409,
    "ERR_QUESTION_PACK_INCOMPLETE": 422,
    "ERR_VIRALITY_THRESHOLD_NOT_MET": 422,
    "ERR_OPEN_NOTICES_BLOCK_RESOLUTION": 409,
    "ERR_OPEN_CLAIMS_BLOCK_RESOLUTION": 409,
    "ERR_CHANNEL_CORRECTION_CAPACITY": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or error_id


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Decimal / arithmetic helpers (PRD 2.7)
# ---------------------------------------------------------------------------
TWO = Decimal("0.01")
FOUR = Decimal("0.0001")


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round2(value):
    return D(value).quantize(TWO, rounding=ROUND_HALF_UP)


def round4(value):
    return D(value).quantize(FOUR, rounding=ROUND_HALF_UP)


def floor_minutes(start, end):
    """Whole minutes between two instants, fractional remainder discarded."""
    return int((end - start).total_seconds() // 60)


def floor_days(start, end):
    return int((end - start).total_seconds() // 86400)


# ---------------------------------------------------------------------------
# Datetime handling (PRD 2.4: ISO 8601 UTC, three fractional digits)
# ---------------------------------------------------------------------------
CLOCK_STARTUP = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def parse_datetime(raw):
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso(value):
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), value.microsecond // 1000)


# ---------------------------------------------------------------------------
# In-memory store. Starts empty on every boot; nothing is ever seeded.
# ---------------------------------------------------------------------------
class Store:
    COLLECTIONS = (
        "members",
        "channels",
        "signals",
        "incidents",
        "assignments",
        "statements",
        "tasks",
        "notices",
        "materials",
        "interviews",
        "claims",
        "reviews",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.clock = CLOCK_STARTUP

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


store = Store()


def new_id():
    return str(uuid.uuid4())


def new_record(extra=None):
    """Common properties of every persisted resource (PRD 2.4)."""
    now = store.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    if extra:
        rec.update(extra)
    rec["_seq"] = store.next_seq()
    return rec


def touch(record):
    """Every mutation bumps updated_at and increments version by exactly 1."""
    record["updated_at"] = store.now()
    record["version"] = record["version"] + 1


def sort_key(record):
    return (record["created_at"], record["_seq"])


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    now = datetime.now(timezone.utc)
    return {"api_request_id": _request_id(), "api_request_timestamp": iso(now)}


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": jsonable(data or {})}
    return jsonify(body), status


def ok_list(records, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(records)) < total_count
    body = {"meta": meta, "response_type": "array", "data": [jsonable(r) for r in records]}
    return jsonify(body), 200


def error_response(exc):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), exc.http_status


# ---------------------------------------------------------------------------
# Authentication / RBAC / identity resolution
# Order of rejection steps 1-3 (PRD 2.9).
# ---------------------------------------------------------------------------
class Caller:
    __slots__ = ("user_id", "role", "member")

    def __init__(self, user_id, role, member):
        self.user_id = user_id
        self.role = role
        self.member = member

    @property
    def is_admin(self):
        return self.role == "ProgramAdmin"

    @property
    def privilege_cleared(self):
        return bool(self.member and self.member.get("privilege_cleared"))


def authenticate(allowed_roles):
    user_id = request.headers.get(HDR_USER_ID)
    role = request.headers.get(HDR_USER_ROLE)
    # 1. Header presence and role validity.
    if not user_id or not user_id.strip() or not role or not role.strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    user_id = user_id.strip()
    role = role.strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unknown role '%s'." % role)
    # 2. Endpoint role authorisation.
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this endpoint." % role)
    # 3. Entity-backed identity resolution.
    member = None
    if role in ENTITY_BACKED_ROLES:
        member = store.members.get(user_id)
        if member is None:
            fail("ERR_TEAM_MEMBER_NOT_FOUND", "X-User-ID does not resolve to a TeamMember.")
    return Caller(user_id, role, member)


# ---------------------------------------------------------------------------
# Request-body validation (PRD 2.9 step 4 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
_SENTINEL = object()


class Field:
    def __init__(self, name, kind, required=False, default=_SENTINEL, **opts):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.opts = opts


def raw_body():
    if request.content_length in (None, 0):
        data = request.get_data(cache=True, as_text=True)
        if not data or not data.strip():
            return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        data = request.get_data(cache=True, as_text=True)
        if not data or not data.strip():
            return {}
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _bad(name, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def _check_string(field, value):
    if not isinstance(value, str):
        _bad(field.name, "must be a string")
    if field.opts.get("nonempty", True) and not value.strip():
        _bad(field.name, "must be non-empty")
    max_len = field.opts.get("max_len")
    if max_len is not None and len(value) > max_len:
        _bad(field.name, "must be at most %d characters" % max_len)
    return value


def _check_int(field, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field.name, "must be an integer")
    lo = field.opts.get("min")
    hi = field.opts.get("max")
    if lo is not None and value < lo:
        _bad(field.name, "must be >= %s" % lo)
    if hi is not None and value > hi:
        _bad(field.name, "must be <= %s" % hi)
    return value


def _check_number(field, value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        _bad(field.name, "must be a number")
    dec = D(value)
    lo = field.opts.get("min")
    hi = field.opts.get("max")
    if lo is not None and dec < D(lo):
        _bad(field.name, "must be >= %s" % lo)
    if hi is not None and dec > D(hi):
        _bad(field.name, "must be <= %s" % hi)
    places = field.opts.get("places")
    if places == 2:
        return round2(dec)
    if places == 4:
        return round4(dec)
    return dec


def validate_body(fields, body=None):
    """Validate the request body against a declared field list.

    Unknown fields, missing required fields, wrong scalar types, out-of-range
    numbers, non-member enum values and malformed datetimes are all
    ERR_INVALID_REQUEST (400).
    """
    body = raw_body() if body is None else body
    declared = {f.name for f in fields}
    for key in body:
        if key not in declared:
            fail("ERR_INVALID_REQUEST", "Unknown field '%s'." % key)
    out = {}
    for field in fields:
        if field.name not in body or body[field.name] is None:
            if field.name in body and body[field.name] is None and field.opts.get("nullable"):
                out[field.name] = None
                continue
            if field.required:
                fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field.name)
            if field.default is not _SENTINEL:
                out[field.name] = field.default
            continue
        value = body[field.name]
        kind = field.kind
        if kind == "string":
            out[field.name] = _check_string(field, value)
        elif kind == "bool":
            if not isinstance(value, bool):
                _bad(field.name, "must be a boolean")
            out[field.name] = value
        elif kind == "int":
            out[field.name] = _check_int(field, value)
        elif kind == "number":
            out[field.name] = _check_number(field, value)
        elif kind == "enum":
            if not isinstance(value, str) or value not in field.opts["values"]:
                _bad(field.name, "must be one of %s" % sorted(field.opts["values"]))
            out[field.name] = value
        elif kind == "datetime":
            parsed = parse_datetime(value)
            if parsed is None:
                _bad(field.name, "must be an ISO 8601 UTC datetime")
            out[field.name] = parsed
        elif kind == "id":
            if not isinstance(value, str) or not value.strip():
                _bad(field.name, "must be a non-empty string identifier")
            out[field.name] = value
        else:  # pragma: no cover - defensive
            raise RuntimeError("unknown field kind %s" % kind)
    return out


# ---------------------------------------------------------------------------
# Pagination + collection filters (PRD 2.3 / 2.5)
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        text = args.get("limit")
        if not re.fullmatch(r"-?\d+", (text or "").strip()):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        limit = int(text)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args:
        text = args.get("offset")
        if not re.fullmatch(r"-?\d+", (text or "").strip()):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        offset = int(text)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def enum_filter(name, values):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value not in values:
        fail("ERR_INVALID_REQUEST", "Filter '%s' must be one of %s." % (name, sorted(values)))
    return value


def bool_filter(name):
    if name not in request.args:
        return None
    value = (request.args.get(name) or "").strip().lower()
    if value in ("true", "1"):
        return True
    if value in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Filter '%s' must be true or false." % name)


def int_filter(name):
    if name not in request.args:
        return None
    value = (request.args.get(name) or "").strip()
    if not re.fullmatch(r"-?\d+", value):
        fail("ERR_INVALID_REQUEST", "Filter '%s' must be an integer." % name)
    return int(value)


def str_filter(name):
    if name not in request.args:
        return None
    return request.args.get(name)


def paged(records, limit, offset):
    records = sorted(records, key=sort_key)
    total = len(records)
    window = records[offset : offset + limit]
    return window, total
