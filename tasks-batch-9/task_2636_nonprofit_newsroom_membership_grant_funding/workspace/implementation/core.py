"""Core infrastructure: in-memory store, logical clock, response envelope,
error type, auth, validation helpers, pagination, numeric + date utilities.

Storage is in-memory only.  The store starts completely empty on every boot;
nothing is seeded, preloaded or hardcoded.
"""

import os
import random
import re
import string
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

COLLECTIONS = (
    "fiscal_periods",
    "membership_tiers",
    "members",
    "coverage_areas",
    "funders",
    "gift_offers",
    "grant_proposals",
    "grant_reports",
    "contributions",
    "firewall_disclosures",
    "influence_contacts",
    "collaborations",
    "collaboration_partners",
)

DB = {name: {} for name in COLLECTIONS}

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

STATE = {
    "clock": CLOCK_EPOCH,
    "seq": 0,
    "receipt_counter": 0,
}


def reset_store():
    for name in COLLECTIONS:
        DB[name] = {}
    STATE["clock"] = CLOCK_EPOCH
    STATE["seq"] = 0
    STATE["receipt_counter"] = 0


def now_clock():
    """Current value of the logical clock (a timezone-aware UTC datetime)."""
    return STATE["clock"]


def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]


def next_receipt_number():
    STATE["receipt_counter"] += 1
    return "RCPT-%06d" % STATE["receipt_counter"]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Timestamp / date formatting
# ---------------------------------------------------------------------------

def iso_ms(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_date(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    """Strict YYYY-MM-DD -> date, or None when unparseable."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_instant(value):
    """Lenient ISO 8601 UTC instant parser -> aware datetime, or None."""
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
        d = parse_date(value)
        if d is None:
            return None
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def day_start(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def clock_date():
    return now_clock().date()


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def round_half_up(numerator, denominator=1):
    """Round numerator/denominator half away from zero to the nearest integer."""
    q = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bps_of(amount_cents, bps):
    return round_half_up(int(amount_cents) * int(bps), 10000)


# ---------------------------------------------------------------------------
# Calendar month arithmetic with day-of-month clamping
# ---------------------------------------------------------------------------

def add_months_clamped(anchor, months):
    """Advance `anchor` by `months` calendar months keeping its day-of-month,
    clamping to the last day of the target month when the day does not exist."""
    total = (anchor.year * 12 + (anchor.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    last = monthrange(year, month)[1]
    return date(year, month, min(anchor.day, last))


def span_months(start, end):
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


# ---------------------------------------------------------------------------
# Error catalogue
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_MEMBER_SCOPE_FORBIDDEN": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_FISCAL_PERIOD_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_TIER_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_COVERAGE_AREA_NOT_FOUND": 404,
    "ERR_FUNDER_NOT_FOUND": 404,
    "ERR_GIFT_OFFER_NOT_FOUND": 404,
    "ERR_GRANT_PROPOSAL_NOT_FOUND": 404,
    "ERR_GRANT_REPORT_NOT_FOUND": 404,
    "ERR_CONTRIBUTION_NOT_FOUND": 404,
    "ERR_DISCLOSURE_NOT_FOUND": 404,
    "ERR_INFLUENCE_CONTACT_NOT_FOUND": 404,
    "ERR_COLLABORATION_NOT_FOUND": 404,
    "ERR_PARTNER_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_BPS_RANGE": 422,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_SPEND_EXCEEDS_RELEASE": 422,
    "ERR_AWARD_AMOUNT_INVALID": 422,
    "ERR_FUNDER_NOT_INSTITUTIONAL": 422,
    "ERR_STREAM_SOURCE_MISMATCH": 422,
    "ERR_WINDOW_OUTSIDE_PERIOD": 422,
    "ERR_CLOCK_REWIND": 422,
    "ERR_BENEFIT_CODE_DUPLICATE": 422,
    "ERR_CONTRIBUTION_BELOW_TIER_MINIMUM": 422,
    "ERR_PERIOD_LOCKED": 409,
    "ERR_TERMINAL_STATE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_UNSETTLED_CONTRIBUTIONS": 409,
    "ERR_BOARD_OVERRIDE_NOT_WARRANTED": 409,
    "ERR_TIER_NOT_PUBLISHED": 409,
    "ERR_MEMBER_NOT_ACTIVE": 409,
    "ERR_FUNDER_RESTRICTED": 409,
    "ERR_FUNDER_RISK_TOO_HIGH": 409,
    "ERR_DISCLOSURE_REQUIRED": 409,
    "ERR_DISCLOSURE_STALE": 409,
    "ERR_PUBLICATION_GATE_BLOCKED": 409,
    "ERR_EDITORIAL_CONDITION_PRESENT": 409,
    "ERR_CONDITION_ROUNDS_EXHAUSTED": 409,
    "ERR_REVISION_ROUNDS_EXHAUSTED": 409,
    "ERR_BOARD_RATIFICATION_REQUIRED": 409,
    "ERR_DISCLOSURE_IN_USE": 409,
    "ERR_SUPERSEDE_TARGET_INVALID": 409,
    "ERR_REPORT_SEQUENCE_VIOLATION": 409,
    "ERR_VARIANCE_UNACCEPTABLE": 409,
    "ERR_FUNDER_COOLING_OFF_VIOLATION": 409,
    "ERR_COLLABORATION_WINDOW_OVERLAP": 409,
    "ERR_REPORT_PERIOD_NOT_ELAPSED": 409,
    "ERR_COLLABORATION_WINDOW_OPEN": 409,
    "ERR_CREDIT_SHARE_SUM_INVALID": 409,
    "ERR_COST_SHARE_SUM_INVALID": 409,
    "ERR_RESTRICTED_GRANT_CAP_EXCEEDED": 409,
    "ERR_PARTNER_DUPLICATE": 409,
    "ERR_LAST_PARTNER_WITHDRAWAL": 409,
    "ERR_NO_CONFIRMED_PARTNER": 409,
    "ERR_BENEFIT_VALUE_EXCEEDS_CONTRIBUTION": 409,
    "ERR_POSTURE_BLOCKS_RELEASE": 409,
    "ERR_RELEASE_CAP_EXCEEDED": 409,
    "ERR_RELEASE_EXCEEDS_AWARD": 409,
    "ERR_PROPOSAL_DELINQUENT": 409,
    "ERR_REFUND_WINDOW_CLOSED": 409,
    "ERR_RESERVE_FLOOR_BREACH": 409,
    "ERR_CONCENTRATION_BOARD_REVIEW_REQUIRED": 409,
    "ERR_STALE_FUNDER_VERSION": 412,
    "ERR_STALE_MEMBER_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 422)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def build_meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {"meta": build_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def list_response(items, total_count, limit, offset, status=200):
    meta = build_meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Authentication and role based access control
# ---------------------------------------------------------------------------

ROLE_DEVELOPMENT_OFFICER = "DevelopmentOfficer"
ROLE_EDITORIAL_DIRECTOR = "EditorialDirector"
ROLE_FINANCE_CONTROLLER = "FinanceController"
ROLE_BOARD_OVERSIGHT = "BoardOversight"
ROLE_MEMBER = "Member"

ALL_ROLES = (
    ROLE_DEVELOPMENT_OFFICER,
    ROLE_EDITORIAL_DIRECTOR,
    ROLE_FINANCE_CONTROLLER,
    ROLE_BOARD_OVERSIGHT,
    ROLE_MEMBER,
)


def authenticate(*allowed_roles):
    """Priority 1 (ERR_UNAUTHENTICATED) then priority 2 (ERR_UNAUTHORIZED)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip() or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and a recognised X-User-Role are required")
    if allowed_roles and role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)
    g.user_id = str(user_id)
    g.user_role = role
    return str(user_id), role


def member_scope(target_member_id):
    """Priority 5: a Member caller may only reach its own row."""
    if g.get("user_role") == ROLE_MEMBER and g.get("user_id") != target_member_id:
        fail("ERR_MEMBER_SCOPE_FORBIDDEN", "a Member may only act on its own membership")


def acting_user():
    return g.get("user_id")


def is_member_caller():
    return g.get("user_role") == ROLE_MEMBER


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------

def new_row(collection, fields, versioned=True):
    row = {"id": new_id()}
    row.update(fields)
    stamp = iso_ms(now_clock())
    row["created_at"] = stamp
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = next_seq()
    DB[collection][row["id"]] = row
    return row


def touch(row):
    row["updated_at"] = iso_ms(now_clock())
    row["version"] = int(row.get("version", 1)) + 1
    return row


def apply_changes(row, changes, force=False):
    """Write `changes`; bump version/updated_at only when something differs,
    unless `force` is set for a transition the PRD says always bumps."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed or force:
        touch(row)
    return changed


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def rows(collection):
    return sorted(DB[collection].values(), key=lambda r: r["_seq"])


def find(collection, **criteria):
    out = []
    for row in rows(collection):
        if all(row.get(k) == v for k, v in criteria.items()):
            out.append(row)
    return out


def lookup(collection, row_id, error_id):
    row = DB[collection].get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id, "%s not found" % collection[:-1].replace("_", " "))
    return row


def lookup_fk(collection, row_id, error_id):
    """Body FK resolution (priority 4).  A null/absent value is not resolved."""
    if row_id is None:
        return None
    if not isinstance(row_id, str):
        fail(error_id, "referenced row not found")
    row = DB[collection].get(row_id)
    if row is None:
        fail(error_id, "referenced row not found")
    return row


# ---------------------------------------------------------------------------
# Request body and field validation (priority 6 unless noted)
# ---------------------------------------------------------------------------

_MISSING = object()


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return payload


def raw(data, name):
    return data.get(name, _MISSING)


def is_present(data, name):
    value = data.get(name, _MISSING)
    return value is not _MISSING and value is not None


def v_str(data, name, required=True, min_len=1, max_len=None, default=None,
          pattern=None):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s is too short" % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s is too long" % name)
    if pattern is not None and not re.match(pattern, value):
        fail("ERR_INVALID_REQUEST", "%s is malformed" % name)
    return value


def v_int(data, name, required=True, minimum=None, maximum=None, default=None):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s is below the minimum of %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s is above the maximum of %s" % (name, maximum))
    return value


def v_bool(data, name, required=True, default=None):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return value


def v_enum(data, name, allowed, required=True, default=None):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def v_date(data, name, required=True, default=None):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    parsed = parse_date(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 date (YYYY-MM-DD)" % name)
    return parsed


def v_instant(data, name, required=True, default=None):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    parsed = parse_instant(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC instant" % name)
    return parsed


def v_bps(data, name, required=True, default=None, minimum=0, maximum=10000):
    """Integer shape is priority 6; the range itself is priority 7."""
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if value < minimum or value > maximum:
        fail("ERR_INVALID_BPS_RANGE",
             "%s must be between %s and %s inclusive" % (name, minimum, maximum))
    return value


def check_bps_range(name, value, minimum=0, maximum=10000):
    if value is None:
        return None
    if value < minimum or value > maximum:
        fail("ERR_INVALID_BPS_RANGE",
             "%s must be between %s and %s inclusive" % (name, minimum, maximum))
    return value


def check_date_order(earlier, later, strict=True):
    if earlier is None or later is None:
        return
    if strict:
        if not earlier < later:
            fail("ERR_INVALID_DATE_RANGE", "the start must precede the end")
    else:
        if earlier > later:
            fail("ERR_INVALID_DATE_RANGE", "the start must not follow the end")


# ---------------------------------------------------------------------------
# Pagination and query parsing
# ---------------------------------------------------------------------------

def q_int(name, default, minimum=None, maximum=None):
    text = request.args.get(name)
    if text is None or text == "":
        return default
    try:
        value = int(text)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s is below the minimum of %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s is above the maximum of %s" % (name, maximum))
    return value


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def q_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    low = value.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be true or false" % name)


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_date(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    parsed = parse_date(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 date (YYYY-MM-DD)" % name)
    return parsed


def pagination():
    limit = q_int("limit", 10, minimum=1, maximum=100)
    offset = q_int("offset", 0, minimum=0)
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
