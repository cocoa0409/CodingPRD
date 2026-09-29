"""Shared helpers: timestamps, rounding, request-shape validation."""
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone

from flask import g, request

from errors import ApiError

UTC = timezone.utc

# ---------------------------------------------------------------- constants
APPEAL_WINDOW_HOURS = 336
MAX_REVISION_ROUNDS = 2
MAX_APPEALS_PER_CLAIM = 1
MIN_PROVISIONAL_COVERAGE_BP = 5000
RUBRIC_MAX_POINTS = 4
ASSIGNMENT_BUFFER_HOURS = 24
DEFAULT_MASTERY_THRESHOLD_BP = 7000
DEFAULT_PASS_THRESHOLD_BP = 7000

SOURCE_TYPES = ["CREDIT_BY_EXAM", "PORTFOLIO", "MILITARY_TRAINING", "INDUSTRY_CREDENTIAL"]
CREDENTIAL_SOURCE_TYPES = ["CREDIT_BY_EXAM", "MILITARY_TRAINING", "INDUSTRY_CREDENTIAL"]
COURSE_LEVELS = ["LOWER", "UPPER"]

TERMINAL_ASSESSMENT_STATES = {"AWARDED", "DENIED_FINAL", "WITHDRAWN"}
RESERVING_STATES = {"SUBMITTED", "UNDER_ASSESSMENT", "REVISION_REQUESTED", "SCORED"}
DUPLICATE_BLOCKING_STATES = {
    "SUBMITTED", "UNDER_ASSESSMENT", "REVISION_REQUESTED", "SCORED",
    "CAP_BLOCKED", "AWARDED", "DENIED", "APPEAL_PENDING",
}


# ---------------------------------------------------------------- identifiers
def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ---------------------------------------------------------------- timestamps
def real_now():
    return datetime.now(UTC)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if _DATE_ONLY.match(text):
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
        norm = text
        if norm.endswith("Z") or norm.endswith("z"):
            norm = norm[:-1] + "+00:00"
        parsed = datetime.fromisoformat(norm)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def put_dt(row, name, dt, raw=None):
    """Store a datetime field: public value is the raw string, parsed value cached."""
    if dt is None:
        row[name] = None
    else:
        row[name] = raw if raw is not None else fmt_dt(dt)
    row.setdefault("_dt", {})[name] = dt


def dtv(row, name):
    return (row.get("_dt") or {}).get(name)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


# ---------------------------------------------------------------- arithmetic
def rhu(numerator, denominator):
    """Round-half-up integer division, sign aware."""
    if denominator == 0:
        return 0
    negative = (numerator < 0) != (denominator < 0)
    n, d = abs(numerator), abs(denominator)
    q, r = divmod(n, d)
    if 2 * r >= d:
        q += 1
    return -q if negative else q


# ---------------------------------------------------------------- row touching
def touch(row):
    """Bump updated_at/version once per row per request."""
    if row is None:
        return
    key = (row.get("_kind"), row.get("id"))
    seen = getattr(g, "touched", None)
    if seen is None:
        seen = set()
        g.touched = seen
    if key in seen:
        return
    seen.add(key)
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = real_now()


# ---------------------------------------------------------------- body helpers
def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def present(body, name):
    return name in body and body[name] is not None


def require(body, name):
    if not present(body, name):
        raise ApiError("ERR_INVALID_REQUEST", "%s is required" % name)
    return body[name]


def as_int(value, name, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if lo is not None and value < lo:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at least %s" % (name, lo))
    if hi is not None and value > hi:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at most %s" % (name, hi))
    return value


def as_str(value, name, min_len=1, max_len=None, pattern=None):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a string" % name)
    if len(value) < min_len:
        raise ApiError("ERR_INVALID_REQUEST", "%s is too short" % name)
    if max_len is not None and len(value) > max_len:
        raise ApiError("ERR_INVALID_REQUEST", "%s is too long" % name)
    if pattern is not None and not re.match(pattern, value):
        raise ApiError("ERR_INVALID_REQUEST", "%s has an invalid format" % name)
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return value


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def as_dt(value, name):
    parsed = parse_dt(value)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp" % name)
    return value, parsed


def as_id(value, name):
    if not isinstance(value, str) or not value:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a string identifier" % name)
    return value
