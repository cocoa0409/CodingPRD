"""Foundation: logical clock, in-memory store, response envelope, errors, auth, validators.

Structural names are taken from PRD.md:
  - auth headers: X-User-ID / X-User-Role  (PRD 2.1)
  - envelope: meta{api_request_id, api_request_timestamp} / response_type / data  (PRD 2.2)
  - pagination: limit / offset / total_count / has_more, default 10, min 1, max 100  (PRD 2.3)
  - OCC fields: expected_cumulative_file_version, expected_inspection_request_version (PRD 2.10)
"""

import random
import string
import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

API_PREFIX = "/records-office"

# --------------------------------------------------------------------------- #
# Logical clock (PRD 2.5): before any clock-setting call it reads exactly
# 2026-08-01T00:00:00Z and never falls back to wall-clock time.
# --------------------------------------------------------------------------- #
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


class _Clock(object):
    def __init__(self):
        self.value = DEFAULT_CLOCK

    def reset(self):
        self.value = DEFAULT_CLOCK


CLOCK = _Clock()


def clock_now():
    return CLOCK.value


def set_clock(instant):
    CLOCK.value = instant


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #
def iso(instant):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.6)."""
    if instant is None:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    instant = instant.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        instant.year, instant.month, instant.day,
        instant.hour, instant.minute, instant.second,
        instant.microsecond // 1000,
    )


def parse_instant(raw):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None on failure."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_calendar_date(raw):
    """Parse a strict YYYY-MM-DD calendar date, or None on failure."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if len(text) != 10:
        return None
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except (ValueError, TypeError):
        return None


def add_calendar_days(instant, days):
    """Calendar-day offset: add whole days preserving time of day (PRD 2.5)."""
    return instant + timedelta(days=int(days))


def add_business_days(anchor, days):
    """Business-day offset (PRD 2.5). The anchor's own calendar day is never
    counted; only Mon-Fri are counted; no holiday calendar exists."""
    cursor = anchor
    counted = 0
    days = int(days)
    while counted < days:
        cursor = cursor + timedelta(days=1)
        if cursor.weekday() <= 4:
            counted += 1
    return cursor


def end_of_day(instant):
    """The instant's UTC calendar date at 23:59:59.999Z."""
    return datetime(instant.year, instant.month, instant.day, 23, 59, 59, 999000,
                    tzinfo=timezone.utc)


def add_whole_years(instant, years):
    """Whole-year offset preserving month/day/time; Feb 29 -> the 28th (PRD 2.5)."""
    years = int(years)
    target_year = instant.year + years
    month = instant.month
    day = instant.day
    try:
        return instant.replace(year=target_year)
    except ValueError:
        return instant.replace(year=target_year, month=month, day=28)


def round_half_up(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def whole_minutes(start, end):
    return int((end - start).total_seconds() // 60)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


def validation_error(message):
    raise ApiError("ERR_VALIDATION", 400, message)


# --------------------------------------------------------------------------- #
# In-memory store. Starts EMPTY on every boot; nothing is seeded.
# --------------------------------------------------------------------------- #
class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.state_rules = {}          # state_code -> row
        self.districts = {}
        self.students = {}
        self.withdrawals = {}
        self.cumulative_files = {}
        self.file_components = {}
        self.discipline_incidents = {}
        self.records_requests = {}
        self.inspection_rooms = {}
        self.inspection_requests = {}
        self.review_appointments = {}
        self.hearing_officers = {}
        self.amendment_requests = {}
        self.legal_demands = {}
        self.disclosure_entries = {}
        self.retention_schedules = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


STORE = Store()


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def base_row(with_version=True):
    """Common resource properties (PRD 2.6)."""
    now = clock_now()
    row = {
        "id": new_id(),
        "created_at": now,
        "_seq": STORE.next_seq(),
    }
    if with_version:
        row["updated_at"] = now
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and increment version (an accepted mutation)."""
    row["updated_at"] = clock_now()
    row["version"] = int(row.get("version", 1)) + 1


# --------------------------------------------------------------------------- #
# Auth (PRD 2.1)
# --------------------------------------------------------------------------- #
ROLE_SYSTEM_ADMIN = "SystemAdmin"
ROLE_RECORDS_CLERK = "RecordsClerk"
ROLE_RECORDS_OFFICER = "RecordsOfficer"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_LEGAL_AFFAIRS_OFFICER = "LegalAffairsOfficer"
ROLE_RECEIVING_REGISTRAR = "ReceivingRegistrar"
ROLE_PARENT = "Parent"
ROLE_ELIGIBLE_STUDENT = "EligibleStudent"

ALL_ROLES = [
    ROLE_SYSTEM_ADMIN, ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER,
    ROLE_COMPLIANCE_OFFICER, ROLE_LEGAL_AFFAIRS_OFFICER,
    ROLE_RECEIVING_REGISTRAR, ROLE_PARENT, ROLE_ELIGIBLE_STUDENT,
]

READ_STAFF = [ROLE_SYSTEM_ADMIN, ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER,
              ROLE_COMPLIANCE_OFFICER, ROLE_LEGAL_AFFAIRS_OFFICER,
              ROLE_RECEIVING_REGISTRAR]


def user_id():
    return request.headers.get("X-User-ID")


def user_role():
    return request.headers.get("X-User-Role")


def require_role(allowed):
    """Band 20: role permission. Checked after path/body existence."""
    role = user_role()
    uid = user_id()
    if not role or not uid or role not in allowed:
        err("ERR_UNAUTHORIZED", 403, "Role is absent or not permitted for this endpoint.")
    return role


# --------------------------------------------------------------------------- #
# Request body / query helpers
# --------------------------------------------------------------------------- #
def body():
    payload = request.get_json(silent=True)
    if payload is None or not isinstance(payload, dict):
        return {}
    return payload


MISSING = object()


def field(payload, name):
    return payload.get(name, MISSING)


def require_present(payload, name):
    value = payload.get(name, MISSING)
    if value is MISSING or value is None:
        validation_error("Field '%s' is required." % name)
    return value


def require_string(payload, name):
    value = require_present(payload, name)
    if not isinstance(value, str) or value.strip() == "":
        validation_error("Field '%s' must be a non-empty string." % name)
    return value


def require_bool(payload, name):
    value = require_present(payload, name)
    if not isinstance(value, bool):
        validation_error("Field '%s' must be a boolean." % name)
    return value


def optional_bool(payload, name, default=False):
    value = payload.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, bool):
        validation_error("Field '%s' must be a boolean." % name)
    return value


def require_int(payload, name, minimum=None, maximum=None):
    value = require_present(payload, name)
    if isinstance(value, bool) or not isinstance(value, int):
        validation_error("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        validation_error("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        validation_error("Field '%s' must be <= %s." % (name, maximum))
    return value


def optional_int(payload, name, default=None, minimum=None, maximum=None):
    value = payload.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        validation_error("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        validation_error("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        validation_error("Field '%s' must be <= %s." % (name, maximum))
    return value


def require_enum(payload, name, allowed):
    value = require_present(payload, name)
    if not isinstance(value, str) or value not in allowed:
        validation_error("Field '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def optional_enum(payload, name, allowed, default=None):
    value = payload.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        validation_error("Field '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def require_instant(payload, name):
    raw = require_present(payload, name)
    parsed = parse_instant(raw)
    if parsed is None:
        validation_error("Field '%s' must be an ISO 8601 instant." % name)
    return parsed


def require_subset(payload, name, allowed, order):
    value = require_present(payload, name)
    if not isinstance(value, list) or len(value) == 0:
        validation_error("Field '%s' must be a non-empty array." % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            validation_error("Field '%s' contains an unsupported value." % name)
    return order_categories(value, order)


def order_categories(values, order):
    """Return the supplied values in the fixed order, de-duplicated."""
    result = []
    for candidate in order:
        if candidate in values and candidate not in result:
            result.append(candidate)
    return result


# --------------------------------------------------------------------------- #
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------- #
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        validation_error("Query parameter '%s' must be an integer." % name)


def pagination():
    limit = _query_int("limit", PAGINATION_DEFAULT_LIMIT)
    offset = _query_int("offset", 0)
    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        validation_error("Query parameter 'limit' must be between 1 and 100.")
    if offset < 0:
        validation_error("Query parameter 'offset' must be >= 0.")
    return limit, offset


def query_value(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_bool(name):
    raw = query_value(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    validation_error("Query parameter '%s' must be a boolean." % name)


def sorted_rows(rows):
    return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))
