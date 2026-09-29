"""Foundation layer: error catalog, response envelope, logical clock, in-memory
store, auth/RBAC helpers and request-shape validation helpers.

Storage is in-memory only.  Nothing is seeded: every dict below starts empty on
every boot and a fresh process therefore has zero carry-over state.
"""

import random
import re
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------

R_DIRECTOR = "CampaignDirector"
R_ORGANIZER = "FieldOrganizer"
R_COMPLIANCE = "ComplianceOfficer"
R_STRATEGIST = "MessageStrategist"
R_PARTNER = "PartnerDelegate"
R_SUPPORTER = "Supporter"

ALL_ROLES = (
    R_DIRECTOR,
    R_ORGANIZER,
    R_COMPLIANCE,
    R_STRATEGIST,
    R_PARTNER,
    R_SUPPORTER,
)

HDR_USER = "X-User-ID"
HDR_ROLE = "X-User-Role"

# ---------------------------------------------------------------------------
# Error catalog (PRD 5)
# ---------------------------------------------------------------------------

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    "ERR_MILESTONE_NOT_FOUND": 404,
    "ERR_LEGISLATOR_NOT_FOUND": 404,
    "ERR_SUPPORTER_NOT_FOUND": 404,
    "ERR_SEGMENT_NOT_FOUND": 404,
    "ERR_VARIANT_NOT_FOUND": 404,
    "ERR_PARTNER_NOT_FOUND": 404,
    "ERR_ENDORSEMENT_NOT_FOUND": 404,
    "ERR_ACTIVATION_NOT_FOUND": 404,
    "ERR_ACTION_RECORD_NOT_FOUND": 404,
    "ERR_SPOKESPERSON_NOT_FOUND": 404,
    "ERR_MEETING_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_SEGMENT_VERSION": 412,
    "ERR_STALE_VARIANT_VERSION": 412,
    "ERR_CAMPAIGN_NOT_ACTIVE": 409,
    "ERR_CAMPAIGN_FROZEN": 409,
    "ERR_CAMPAIGN_RESTRICTED": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_NO_TARGET_LEGISLATOR": 409,
    "ERR_ACTIVATION_IN_FLIGHT": 409,
    "ERR_OUTSIDE_SEND_WINDOW": 409,
    "ERR_PARTNER_WITHDRAWN": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_NO_ELIGIBLE_VARIANT": 409,
    "ERR_CONSENT_MISSING": 422,
    "ERR_SUPPORTER_SUPPRESSED": 422,
    "ERR_LAWFUL_BASIS_INVALID": 422,
    "ERR_STORY_CONSENT_REQUIRED": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_WINDOW_OUTSIDE_CAMPAIGN": 422,
    "ERR_BLACKOUT_WINDOW": 409,
    "ERR_MEETING_WINDOW_CONFLICT": 409,
    "ERR_CHANNEL_WINDOW_SATURATED": 409,
    "ERR_DUPLICATE_ENDORSEMENT": 409,
    "ERR_DUPLICATE_SPOKESPERSON": 409,
    "ERR_VARIANT_NOT_LOCKED": 409,
    "ERR_SPOKESPERSON_NOT_CERTIFIED": 409,
    "ERR_ENDORSEMENT_QUORUM_NOT_MET": 409,
    "ERR_CAMPAIGN_MISMATCH": 422,
    "ERR_CHANNEL_NOT_IN_VARIANT_SCOPE": 422,
    "ERR_DISTRICT_MISMATCH": 422,
    "ERR_SEGMENT_EMPTY": 409,
    "ERR_FREQUENCY_CAP_EXHAUSTED": 409,
    "ERR_REACH_BELOW_MINIMUM": 409,
    "ERR_DELIVERY_TALLY_MISMATCH": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 422)
        self.message = message or error_id


def err(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.10) -- startup default is exactly 2026-08-01T00:00:00Z
# ---------------------------------------------------------------------------

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock(object):
    now = CLOCK_DEFAULT


def now_dt():
    return Clock.now


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------


class DB(object):
    def __init__(self):
        self.campaigns = {}
        self.milestones = {}
        self.legislators = {}
        self.supporters = {}
        self.consent_events = {}
        self.segments = {}
        self.variants = {}
        self.partners = {}
        self.endorsements = {}
        self.activations = {}
        self.action_records = {}
        self.spokespersons = {}
        self.meetings = {}
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = DB()


# ---------------------------------------------------------------------------
# Timestamp helpers -- ISO 8601 UTC with exactly three fractional digits
# ---------------------------------------------------------------------------


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(([Zz])|([+-]\d{2}:?\d{2}))?$"
)


def parse_dt(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s or not _DT_RE.match(s):
        return None
    s = s.replace(" ", "T").replace("t", "T")
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def whole_minute(dt):
    return dt.second == 0 and dt.microsecond == 0


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------

D0 = Decimal("0")
CENT = Decimal("0.01")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def r2(value):
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def r0(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num(value):
    """Render a Decimal as a JSON number."""
    if value is None:
        return None
    return float(value)


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------


def new_row(versioned=True):
    ts = now_dt()
    row = {"id": str(uuid.uuid4()), "created_at": ts, "_seq": db.next_seq()}
    if versioned:
        row["updated_at"] = ts
        row["version"] = 1
    return row


def touch(row):
    """Mark a row mutated.

    PRD 2.4: `version` "increments by exactly 1 on every mutation of that row".
    A single request is one mutation of a given row however many derived fields
    settle inside it -- a transition that also re-derives the posture of the very
    campaign it transitioned still reports "the campaign's version increments by
    1" -- so the increment is idempotent for the lifetime of one request while
    `updated_at` keeps tracking the latest write.
    """
    row["updated_at"] = now_dt()
    try:
        seen = g._touched_rows
    except (AttributeError, RuntimeError):
        seen = None
        try:
            seen = set()
            g._touched_rows = seen
        except RuntimeError:
            seen = None
    if seen is not None:
        key = row.get("id")
        if key in seen:
            return
        seen.add(key)
    row["version"] = int(row.get("version", 1)) + 1


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------

_ID_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    return (
        jsonify({"meta": _meta(), "response_type": "object", "data": data}),
        status,
    )


def ok_list(items, limit, offset):
    total = len(items)
    page = items[offset : offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    return (
        jsonify({"meta": meta, "response_type": "array", "data": page}),
        200,
    )


def error_response(exc):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": exc.error_id, "message": exc.message},
            }
        ),
        exc.http_status,
    )


# ---------------------------------------------------------------------------
# Auth + RBAC (ladder rungs 1 and 2)
# ---------------------------------------------------------------------------


def require_role(*allowed):
    user_id = request.headers.get(HDR_USER)
    role = request.headers.get(HDR_ROLE)
    if not user_id or not str(user_id).strip():
        err("ERR_UNAUTHENTICATED", "missing %s header" % HDR_USER)
    if not role or role not in ALL_ROLES:
        err("ERR_UNAUTHENTICATED", "missing or unrecognised %s header" % HDR_ROLE)
    g.user_id = str(user_id).strip()
    g.role = role
    if allowed and role not in allowed:
        err("ERR_ROLE_NOT_PERMITTED", "role %s may not perform this operation" % role)


# ---------------------------------------------------------------------------
# Request body / query-string validation (ladder rung 5)
# ---------------------------------------------------------------------------


def get_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        err("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def check_shape(body, required=(), optional=()):
    allowed = set(required) | set(optional)
    for key in body.keys():
        if key not in allowed:
            err("ERR_INVALID_REQUEST", "unknown field '%s'" % key)
    for key in required:
        if key not in body or body[key] is None:
            err("ERR_INVALID_REQUEST", "field '%s' is required" % key)


def f_str(body, key, max_len=None, required=True, allow_empty=False):
    if key not in body or body[key] is None:
        if required:
            err("ERR_INVALID_REQUEST", "field '%s' is required" % key)
        return None
    value = body[key]
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", "field '%s' must be a string" % key)
    if not allow_empty and not value.strip():
        err("ERR_INVALID_REQUEST", "field '%s' must be non-empty" % key)
    if max_len is not None and len(value) > max_len:
        err(
            "ERR_INVALID_REQUEST",
            "field '%s' exceeds maximum length %d" % (key, max_len),
        )
    return value


def f_enum(body, key, choices, required=True):
    if key not in body or body[key] is None:
        if required:
            err("ERR_INVALID_REQUEST", "field '%s' is required" % key)
        return None
    value = body[key]
    if not isinstance(value, str) or value not in choices:
        err(
            "ERR_INVALID_REQUEST",
            "field '%s' must be one of %s" % (key, ", ".join(sorted(choices))),
        )
    return value


def f_int(body, key, required=True, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        if required:
            err("ERR_INVALID_REQUEST", "field '%s' is required" % key)
        return None
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        err("ERR_INVALID_REQUEST", "field '%s' must be an integer" % key)
    if minimum is not None and value < minimum:
        err("ERR_INVALID_REQUEST", "field '%s' must be >= %d" % (key, minimum))
    if maximum is not None and value > maximum:
        err("ERR_INVALID_REQUEST", "field '%s' must be <= %d" % (key, maximum))
    return value


def f_num(body, key, required=True, minimum=None):
    if key not in body or body[key] is None:
        if required:
            err("ERR_INVALID_REQUEST", "field '%s' is required" % key)
        return None
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        err("ERR_INVALID_REQUEST", "field '%s' must be a number" % key)
    value = dec(value)
    if minimum is not None and value < dec(minimum):
        err("ERR_INVALID_REQUEST", "field '%s' must be >= %s" % (key, minimum))
    return value


def f_bool(body, key, required=True, must_be=None):
    if key not in body or body[key] is None:
        if required:
            err("ERR_INVALID_REQUEST", "field '%s' is required" % key)
        return None
    value = body[key]
    if not isinstance(value, bool):
        err("ERR_INVALID_REQUEST", "field '%s' must be a boolean" % key)
    if must_be is not None and value is not must_be:
        err("ERR_INVALID_REQUEST", "field '%s' must be %s" % (key, str(must_be).lower()))
    return value


def f_dt(body, key, required=True):
    if key not in body or body[key] is None:
        if required:
            err("ERR_INVALID_REQUEST", "field '%s' is required" % key)
        return None
    parsed = parse_dt(body[key])
    if parsed is None:
        err("ERR_INVALID_REQUEST", "field '%s' must be an ISO 8601 timestamp" % key)
    return parsed


def f_str_list(body, key, choices=None, required=True, allow_empty=True, max_len=None):
    if key not in body or body[key] is None:
        if required:
            err("ERR_INVALID_REQUEST", "field '%s' is required" % key)
        return None
    value = body[key]
    if not isinstance(value, list):
        err("ERR_INVALID_REQUEST", "field '%s' must be an array" % key)
    if not allow_empty and len(value) == 0:
        err("ERR_INVALID_REQUEST", "field '%s' must be non-empty" % key)
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            err("ERR_INVALID_REQUEST", "field '%s' must contain non-empty strings" % key)
        if choices is not None and item not in choices:
            err(
                "ERR_INVALID_REQUEST",
                "field '%s' contains an unrecognised value" % key,
            )
        if max_len is not None and len(item) > max_len:
            err("ERR_INVALID_REQUEST", "field '%s' entry is too long" % key)
        out.append(item)
    return out


_INT_RE = re.compile(r"^[+-]?\d+$")


def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        raw = raw_limit.strip()
        if not _INT_RE.match(raw):
            err("ERR_INVALID_REQUEST", "limit must be an integer")
        limit = int(raw)
        if limit < 1 or limit > 100:
            err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is not None:
        raw = raw_offset.strip()
        if not _INT_RE.match(raw):
            err("ERR_INVALID_REQUEST", "offset must be an integer")
        offset = int(raw)
        if offset < 0:
            err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def q_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    err("ERR_INVALID_REQUEST", "query parameter '%s' must be a boolean" % name)


# ---------------------------------------------------------------------------
# Existence lookups (ladder rungs 3 and 4)
# ---------------------------------------------------------------------------

_COLLECTIONS = {
    "campaign": ("campaigns", "ERR_CAMPAIGN_NOT_FOUND"),
    "milestone": ("milestones", "ERR_MILESTONE_NOT_FOUND"),
    "legislator": ("legislators", "ERR_LEGISLATOR_NOT_FOUND"),
    "supporter": ("supporters", "ERR_SUPPORTER_NOT_FOUND"),
    "consent_event": ("consent_events", "ERR_SUPPORTER_NOT_FOUND"),
    "segment": ("segments", "ERR_SEGMENT_NOT_FOUND"),
    "variant": ("variants", "ERR_VARIANT_NOT_FOUND"),
    "partner": ("partners", "ERR_PARTNER_NOT_FOUND"),
    "endorsement": ("endorsements", "ERR_ENDORSEMENT_NOT_FOUND"),
    "activation": ("activations", "ERR_ACTIVATION_NOT_FOUND"),
    "action_record": ("action_records", "ERR_ACTION_RECORD_NOT_FOUND"),
    "spokesperson": ("spokespersons", "ERR_SPOKESPERSON_NOT_FOUND"),
    "meeting": ("meetings", "ERR_MEETING_NOT_FOUND"),
}


def must(kind, row_id):
    attr, error_id = _COLLECTIONS[kind]
    if not isinstance(row_id, str):
        err(error_id, "%s not found" % kind)
    row = getattr(db, attr).get(row_id)
    if row is None:
        err(error_id, "%s '%s' not found" % (kind, row_id))
    return row


def must_fk(kind, body, key, required=True):
    """Resolve a foreign key carried in the request body.

    Runs at ladder rung 4, i.e. before request-shape validation, so a value of
    the wrong type resolves to nothing and yields the 404 for that collection.
    An absent key is left to rung 5.
    """
    if key not in body or body[key] is None:
        if required:
            return None
        return None
    return must(kind, body[key])
