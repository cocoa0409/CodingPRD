"""Foundation layer: in-memory store, logical clock, errors, response envelope,
auth middleware, body/query validation helpers.

Every structural name here (headers, envelope fields, pagination names, error ids)
is taken literally from PRD.md §2 and SCAFFOLD.yaml §1.0/§1.4/§1.6.
"""

import random
import re
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

# ---------------------------------------------------------------------------
# Logical clock default (PRD §2.4)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Error catalog (PRD §5 / SCAFFOLD §1.6)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNKNOWN_ACTOR": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_AUTHORITY_TIER_INSUFFICIENT": 403,
    "ERR_VALIDATION": 400,
    "ERR_STAFF_USER_NOT_FOUND": 404,
    "ERR_CONSUMER_NOT_FOUND": 404,
    "ERR_PLANT_NOT_FOUND": 404,
    "ERR_PRODUCTION_LINE_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_PRODUCTION_LOT_NOT_FOUND": 404,
    "ERR_CONTACT_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_SAMPLE_KIT_NOT_FOUND": 404,
    "ERR_REMEDY_NOT_FOUND": 404,
    "ERR_REGULATORY_REPORT_NOT_FOUND": 404,
    "ERR_TREND_SIGNAL_NOT_FOUND": 404,
    "ERR_RESPONSE_TEMPLATE_NOT_FOUND": 404,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_CONTACT_CLOSED": 409,
    "ERR_CONTACT_HAS_COMPLAINTS": 409,
    "ERR_COMPLAINT_STATE_INVALID": 409,
    "ERR_REGULATORY_STATE_INVALID": 409,
    "ERR_REPORT_ALREADY_OPEN": 409,
    "ERR_REMEDY_STATE_INVALID": 409,
    "ERR_SAMPLE_KIT_STATE_INVALID": 409,
    "ERR_TREND_SIGNAL_STATE_INVALID": 409,
    "ERR_LOT_STATE_INVALID": 409,
    "ERR_TEMPLATE_STATE_INVALID": 409,
    "ERR_REPORT_STATE_INVALID": 409,
    "ERR_PRODUCT_UNIDENTIFIED": 409,
    "ERR_LOT_WITHDRAWN": 409,
    "ERR_RECALL_EVALUATION_ACTIVE": 409,
    "ERR_SIGNAL_INVESTIGATION_ACTIVE": 409,
    "ERR_REGULATORY_SUBMISSION_PENDING": 409,
    "ERR_SAMPLE_KIT_IN_FLIGHT": 409,
    "ERR_PLANT_UNDER_INVESTIGATION_HOLD": 409,
    "ERR_KIT_INTERVAL_CONFLICT": 409,
    "ERR_SIGNAL_WINDOW_OVERLAP": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_STALE_COMPLAINT_VERSION": 412,
    "ERR_STALE_SAMPLE_KIT_VERSION": 412,
    "ERR_DUPLICATE_TARGET_INVALID": 422,
    "ERR_S1_MUST_BE_REPORTABLE": 422,
    "ERR_SEVERITY_TOO_LOW_FOR_RECALL": 422,
    "ERR_SIGNAL_EMPTY_MEMBERSHIP": 422,
    "ERR_RECEIVED_AT_IN_FUTURE": 422,
    "ERR_CUSTODY_OUT_OF_ORDER": 422,
    "ERR_CUSTODY_SEQUENCE_INVALID": 422,
    "ERR_WINDOW_INVALID": 422,
    "ERR_SCOPE_SHAPE_INVALID": 422,
    "ERR_CONSUMER_ADDRESS_MISSING": 422,
    "ERR_TEMPLATE_TYPE_MISMATCH": 422,
    "ERR_TEMPLATE_BAND_TOO_LOW": 422,
    "ERR_GOODWILL_ABOVE_MAX": 422,
    "ERR_BATCH_CODE_AMBIGUOUS": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def err(error_id, message=None):
    return ApiError(error_id, message)


# ---------------------------------------------------------------------------
# In-memory store.  Starts EMPTY on every boot — nothing is ever seeded.
# ---------------------------------------------------------------------------
class Store(object):
    COLLECTIONS = (
        "staff_users",
        "consumers",
        "plants",
        "production_lines",
        "products",
        "production_lots",
        "contacts",
        "complaints",
        "sample_kits",
        "custody_events",
        "remedies",
        "regulatory_reports",
        "trend_signals",
        "signal_memberships",
        "response_templates",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.seq = 0
        self.clock = DEFAULT_CLOCK

    def snapshot(self):
        import copy

        state = {name: copy.deepcopy(getattr(self, name)) for name in self.COLLECTIONS}
        state["seq"] = self.seq
        state["clock"] = self.clock
        return state

    def restore(self, state):
        for name in self.COLLECTIONS:
            setattr(self, name, state[name])
        self.seq = state["seq"]
        self.clock = state["clock"]


store = Store()
request_lock = threading.RLock()


def now():
    """The logical clock instant (PRD §2.4)."""
    return store.clock


def next_seq():
    store.seq += 1
    return store.seq


def new_id():
    return str(uuid.uuid4())


def base_record(with_version=True):
    rec = {"id": new_id(), "created_at": now(), "_seq": next_seq()}
    if with_version:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD §2.5)."""
    if rec is None:
        return
    if "version" in rec:
        rec["updated_at"] = now()
        rec["version"] = rec["version"] + 1


def sort_records(records):
    """Default ordering: created_at ascending, insertion order as tie-break
    (PRD §2.3 — never by id)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_datetime(value):
    """Parse an ISO-8601 instant.  Returns an aware UTC datetime or None when
    the value cannot be parsed."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        if _DATE_ONLY.match(raw):
            dt = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt
        if raw.endswith("Z") or raw.endswith("z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_datetime(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.5)."""
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


# ---------------------------------------------------------------------------
# Numeric helpers (PRD §2.6)
# ---------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def money(value):
    """Whole cents, rounded half up the moment the value is produced."""
    return int(round_half_up(value, 0))


def num2(value):
    """A 2-decimal-place number for JSON output."""
    if value is None:
        return None
    return float(round_half_up(value, 2))


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return fmt_datetime(dt)


def build_meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, meta_extra=None):
    body = {
        "meta": build_meta(meta_extra),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data if data is not None else {},
    }
    return body, status


def error_body(error_id, message):
    return {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginated(items, limit, offset):
    total = len(items)
    page = items[offset : offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return success(page, 200, meta_extra)


# ---------------------------------------------------------------------------
# Auth (PRD §2.1, validation ladder steps 1-3)
# ---------------------------------------------------------------------------
ROLE_SYSTEM_ADMIN = "SystemAdmin"
ROLE_CARE_AGENT = "CareAgent"
ROLE_CARE_SUPERVISOR = "CareSupervisor"
ROLE_QUALITY_LEAD = "QualityLead"
ROLE_REGULATORY_OFFICER = "RegulatoryOfficer"
ROLE_CONSUMER = "Consumer"


class Actor(object):
    def __init__(self, user_id, role, entity):
        self.user_id = user_id
        self.role = role
        self.entity = entity

    @property
    def authority_tier(self):
        if self.entity is None:
            return None
        return self.entity.get("authority_tier")


def authorize(allowed_roles):
    """Steps 1-3 of the validation ladder, in order."""
    raw_id = request.headers.get("X-User-ID")
    raw_role = request.headers.get("X-User-Role")

    if raw_id is None or not raw_id.strip():
        raise err("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    user_id = raw_id.strip()
    role = (raw_role or "").strip()

    entity = None
    if role != ROLE_SYSTEM_ADMIN:
        staff = store.staff_users.get(user_id)
        if staff is not None:
            if not staff.get("is_active"):
                raise err("ERR_UNKNOWN_ACTOR", "the acting staff member is not active")
            entity = staff
        else:
            consumer = store.consumers.get(user_id)
            if consumer is None:
                raise err("ERR_UNKNOWN_ACTOR", "X-User-ID does not resolve to a known actor")
            entity = consumer

    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "role %r may not perform this operation" % role)

    return Actor(user_id, role, entity)


def authorize_clock():
    """POST /_clock/set_current_utc — the single endpoint that needs no X-User-ID."""
    raw_role = request.headers.get("X-User-Role")
    role = (raw_role or "").strip()
    if role and role != ROLE_SYSTEM_ADMIN:
        raise err("ERR_UNAUTHORIZED", "only SystemAdmin may set the logical clock")
    raw_id = request.headers.get("X-User-ID")
    return Actor((raw_id or "").strip() or None, ROLE_SYSTEM_ADMIN, None)


# ---------------------------------------------------------------------------
# Body / query validation helpers
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_data(cache=True)
    if not data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_VALIDATION", "request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise err("ERR_VALIDATION", "request body must be a JSON object")
    return parsed


def check_required(body, names):
    """Validation ladder step 7 — presence of every required field, before any
    type/enum/range inspection."""
    for name in names:
        if name not in body or body[name] is None:
            raise err("ERR_VALIDATION", "%s is required" % name)


def _present(body, name):
    return name in body and body[name] is not None


def v_string(body, name, min_len=1, max_len=None, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        raise err("ERR_VALIDATION", "%s must be a string" % name)
    if len(value) < min_len:
        raise err("ERR_VALIDATION", "%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise err("ERR_VALIDATION", "%s must be at most %d characters" % (name, max_len))
    return value


def v_int(body, name, min_value=None, max_value=None, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_VALIDATION", "%s must be an integer" % name)
    if min_value is not None and value < min_value:
        raise err("ERR_VALIDATION", "%s must be >= %s" % (name, min_value))
    if max_value is not None and value > max_value:
        raise err("ERR_VALIDATION", "%s must be <= %s" % (name, max_value))
    return value


def v_bool(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise err("ERR_VALIDATION", "%s must be a boolean" % name)
    return value


def v_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise err(
            "ERR_VALIDATION",
            "%s must be one of %s" % (name, ", ".join(sorted(allowed))),
        )
    return value


def v_datetime(body, name, default=None):
    if not _present(body, name):
        return default
    parsed = parse_datetime(body[name])
    if parsed is None:
        raise err("ERR_VALIDATION", "%s must be an ISO 8601 datetime" % name)
    return parsed


def v_string_array(body, name, max_items, item_min, item_max, default=None):
    if not _present(body, name):
        return list(default) if default is not None else None
    value = body[name]
    if not isinstance(value, list):
        raise err("ERR_VALIDATION", "%s must be an array" % name)
    if len(value) > max_items:
        raise err("ERR_VALIDATION", "%s may hold at most %d entries" % (name, max_items))
    for item in value:
        if not isinstance(item, str):
            raise err("ERR_VALIDATION", "%s entries must be strings" % name)
        if len(item) < item_min or len(item) > item_max:
            raise err(
                "ERR_VALIDATION",
                "%s entries must be %d..%d characters" % (name, item_min, item_max),
            )
    return list(value)


_INT_RE = re.compile(r"^[+-]?\d+$")


def pagination():
    """Validation ladder step 9 (PRD §2.3)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not _INT_RE.match(raw.strip()):
            raise err("ERR_VALIDATION", "limit must be an integer from 1 through 100")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION", "limit must be an integer from 1 through 100")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not _INT_RE.match(raw.strip()):
            raise err("ERR_VALIDATION", "offset must be an integer of at least 0")
        offset = int(raw.strip())
        if offset < 0:
            raise err("ERR_VALIDATION", "offset must be an integer of at least 0")
    return limit, offset


def q_enum(name, allowed):
    """A query-parameter enum filter; unrecognised values are rejected."""
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value not in allowed:
        raise err("ERR_VALIDATION", "%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def q_str(name):
    if name not in request.args:
        return None
    return request.args.get(name)


def q_bool(name):
    if name not in request.args:
        return None
    raw = (request.args.get(name) or "").strip().lower()
    if raw in ("true", "1"):
        return True
    if raw in ("false", "0"):
        return False
    raise err("ERR_VALIDATION", "%s must be true or false" % name)


# ---------------------------------------------------------------------------
# Existence helpers (validation ladder steps 4-5)
# ---------------------------------------------------------------------------
_NOT_FOUND = {
    "staff_users": "ERR_STAFF_USER_NOT_FOUND",
    "consumers": "ERR_CONSUMER_NOT_FOUND",
    "plants": "ERR_PLANT_NOT_FOUND",
    "production_lines": "ERR_PRODUCTION_LINE_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "production_lots": "ERR_PRODUCTION_LOT_NOT_FOUND",
    "contacts": "ERR_CONTACT_NOT_FOUND",
    "complaints": "ERR_COMPLAINT_NOT_FOUND",
    "sample_kits": "ERR_SAMPLE_KIT_NOT_FOUND",
    "remedies": "ERR_REMEDY_NOT_FOUND",
    "regulatory_reports": "ERR_REGULATORY_REPORT_NOT_FOUND",
    "trend_signals": "ERR_TREND_SIGNAL_NOT_FOUND",
    "response_templates": "ERR_RESPONSE_TEMPLATE_NOT_FOUND",
}


def must_get(collection, record_id):
    coll = getattr(store, collection)
    if not isinstance(record_id, str) or record_id not in coll:
        raise err(_NOT_FOUND[collection], "%s %r was not found" % (collection[:-1], record_id))
    return coll[record_id]


def unique_or_conflict(collection, field, value, scope=None):
    """Validation ladder step 11."""
    for rec in getattr(store, collection).values():
        if rec.get(field) != value:
            continue
        if scope is not None:
            scope_field, scope_value = scope
            if rec.get(scope_field) != scope_value:
                continue
        raise err("ERR_DUPLICATE_CODE", "%s %r already exists" % (field, value))


def hours_between(start, end):
    delta = end - start
    return dec(delta.total_seconds()) / dec(3600)


def days(count):
    return timedelta(days=count)


def hours(count):
    return timedelta(hours=count)
