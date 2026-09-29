"""Foundation: error type, response envelope, logical clock, in-memory store.

Every structural name here is taken from PRD.md (sections 2.1 - 2.4) and
SCAFFOLD.yaml `response_envelope`.
"""
import json
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import g, request

# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

# PRD section 5: complete error catalogue -> HTTP status.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_FORM_NOT_FOUND": 404,
    "ERR_AGENT_NOT_FOUND": 404,
    "ERR_EVALUATOR_NOT_FOUND": 404,
    "ERR_INTERACTION_NOT_FOUND": 404,
    "ERR_SCAN_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_SELECTION_NOT_FOUND": 404,
    "ERR_EVALUATION_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_SUBMISSION_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_COACHING_PLAN_NOT_FOUND": 404,
    "ERR_STALE_INTERACTION_VERSION": 412,
    "ERR_STALE_AGENT_VERSION": 412,
    "ERR_STALE_EVALUATION_VERSION": 412,
    "ERR_FORM_NOT_DRAFT": 409,
    "ERR_FORM_NOT_ACTIVE": 409,
    "ERR_PLAN_NOT_DRAFT": 409,
    "ERR_PLAN_NOT_OPEN": 409,
    "ERR_SELECTION_NOT_ASSIGNABLE": 409,
    "ERR_SELECTION_TERMINAL": 409,
    "ERR_EVALUATION_NOT_EDITABLE": 409,
    "ERR_EVALUATION_NOT_DELIVERABLE": 409,
    "ERR_FEEDBACK_ALREADY_DELIVERED": 409,
    "ERR_FEEDBACK_NOT_DELIVERED": 409,
    "ERR_CONSENT_ALREADY_DENIED": 409,
    "ERR_SESSION_NOT_OPEN": 409,
    "ERR_SESSION_NOT_SCORING": 409,
    "ERR_DISPUTE_NOT_REVIEWABLE": 409,
    "ERR_DISPUTE_NOT_RESOLVABLE": 409,
    "ERR_DISPUTE_NOT_RESPONDABLE": 409,
    "ERR_COACHING_PLAN_TERMINAL": 409,
    "ERR_CONSENT_NOT_VERIFIED": 422,
    "ERR_EVALUATOR_NOT_CALIBRATED": 409,
    "ERR_COMPLIANCE_HOLD_OPEN": 409,
    "ERR_FORM_VERSION_MISMATCH": 422,
    "ERR_GUIDANCE_VERSION_STALE": 409,
    "ERR_WEIGHTS_NOT_100": 422,
    "ERR_NO_COMPLIANCE_BEHAVIOR": 422,
    "ERR_DUPLICATE_BEHAVIOR_CODE": 422,
    "ERR_SOURCE_MIX_INVALID": 422,
    "ERR_ITEM_SCORE_INCOMPLETE": 422,
    "ERR_ITEM_SCORE_OUT_OF_RANGE": 422,
    "ERR_NA_NOT_ALLOWED": 422,
    "ERR_SOURCE_NOT_ELIGIBLE": 422,
    "ERR_DUPLICATE_INTERACTION_SELECTION": 409,
    "ERR_SESSION_PARTICIPANT_DUPLICATE": 409,
    "ERR_DISPUTE_ALREADY_OPEN": 409,
    "ERR_DISPUTE_ROUND_LIMIT": 422,
    "ERR_SESSIONS_INCOMPLETE": 422,
    "ERR_INSUFFICIENT_EVALUATION_HISTORY": 422,
    "ERR_INVALID_TIME_RANGE": 422,
    "ERR_PLAN_PERIOD_OVERLAP": 409,
    "ERR_EVALUATOR_WINDOW_CONFLICT": 409,
    "ERR_DISPUTE_WINDOW_EXPIRED": 422,
    "ERR_ESCALATION_NOT_DUE": 422,
    "ERR_AGENT_QUOTA_EXCEEDED": 422,
    "ERR_SOURCE_MIX_EXCEEDED": 422,
    "ERR_EVALUATOR_CAPACITY_EXCEEDED": 422,
    "ERR_RECOGNITION_THRESHOLD_NOT_MET": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_STATUS[error_id]


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Timestamps and the logical clock (PRD section 2.4)
# --------------------------------------------------------------------------

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")


class LogicalClock(object):
    def __init__(self):
        self.now = CLOCK_EPOCH

    def set(self, dt):
        self.now = dt


CLOCK = LogicalClock()


def clock_now():
    return CLOCK.now


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def now_iso():
    return fmt_dt(clock_now())


def parse_dt(value):
    """Strict RFC 3339 UTC with trailing Z; returns aware datetime or None."""
    if not isinstance(value, str) or not _DT_RE.match(value):
        return None
    try:
        frac = ""
        base = value[:-1]
        if "." in base:
            base, frac = base.split(".", 1)
            frac = (frac + "000000")[:6]
        dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
        return dt.replace(microsecond=int(frac or 0), tzinfo=timezone.utc)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Decimal helpers (PRD section 2.6)
# --------------------------------------------------------------------------

TWO = Decimal("0.01")


def q2(value):
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def ceil_int(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_CEILING))


# --------------------------------------------------------------------------
# Response envelope (PRD section 2.2)
# --------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def envelope_meta():
    stamp = datetime.now(timezone.utc)
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(stamp),
    }


def jsonify_out(payload, status):
    from flask import Response
    body = json.dumps(payload, default=_json_default)
    return Response(body, status=status, mimetype="application/json")


def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return fmt_dt(obj)
    raise TypeError(repr(obj))


def ok(data, status=200):
    return jsonify_out(
        {"meta": envelope_meta(), "response_type": "object", "data": data}, status
    )


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = envelope_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return jsonify_out(
        {"meta": meta, "response_type": "array", "data": rows}, 200
    )


def error_response(err):
    return jsonify_out(
        {
            "meta": envelope_meta(),
            "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message},
        },
        err.http_status,
    )


# --------------------------------------------------------------------------
# In-memory store.  Nothing is seeded: every row is built by an API call.
# --------------------------------------------------------------------------

KINDS = (
    "forms",
    "behaviors",
    "agents",
    "evaluators",
    "interactions",
    "scans",
    "plans",
    "selections",
    "evaluations",
    "sessions",
    "submissions",
    "disputes",
    "coaching_plans",
)

DB = {kind: {} for kind in KINDS}

_SEQ = {"n": 0}


def _next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_row(kind, fields, common=True):
    """Create a stored row.  `common` False -> CalibrationSubmission shape
    (PRD 2.4: it carries only id and created_at)."""
    stamp = now_iso()
    row = {"id": str(uuid.uuid4()), "created_at": stamp}
    if common:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = _next_seq()
    row["_kind"] = kind
    row.update(fields)
    DB[kind][row["id"]] = row
    return row


def touch(row):
    """A mutation: refresh updated_at and increment version by exactly one."""
    if "version" in row:
        row["updated_at"] = now_iso()
        row["version"] = row["version"] + 1
    return row


def rows(kind):
    return list(DB[kind].values())


def sort_key(row):
    return (row["created_at"], row["_seq"])


def sorted_rows(items):
    return sorted(items, key=sort_key)


def get(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[kind].get(row_id)


def require(kind, row_id, error_id):
    row = get(kind, row_id)
    if row is None:
        fail(error_id, "%s does not identify a stored %s" % (row_id, kind))
    return row


# --------------------------------------------------------------------------
# Request body access
# --------------------------------------------------------------------------


def body():
    """Parse the JSON body.  Floats become Decimal so the literal number of
    fractional digits is preserved (PRD 2.6)."""
    if hasattr(g, "_parsed_body"):
        return g._parsed_body
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        parsed = {}
    else:
        try:
            parsed = json.loads(raw, parse_float=Decimal)
        except (ValueError, TypeError):
            fail("ERR_INVALID_REQUEST", "request body is not valid JSON")
        if not isinstance(parsed, dict):
            fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    g._parsed_body = parsed
    return parsed
