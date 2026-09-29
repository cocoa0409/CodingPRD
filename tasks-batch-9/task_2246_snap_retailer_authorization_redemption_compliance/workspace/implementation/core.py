"""Foundation: logical clock, in-memory store, response envelope, errors, auth."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from fractions import Fraction

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Error catalogue (§1.6 / PRD §5)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_MISSING_USER_CONTEXT": 400,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_OWNER_NOT_FOUND": 404,
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_INSPECTOR_NOT_FOUND": 404,
    "ERR_STORE_VISIT_NOT_FOUND": 404,
    "ERR_POS_TRANSACTION_NOT_FOUND": 404,
    "ERR_REDEMPTION_PERIOD_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    "ERR_SANCTION_CASE_NOT_FOUND": 404,
    "ERR_DEPOT_NOT_FOUND": 404,
    "ERR_TERMINAL_NOT_FOUND": 404,
    "ERR_DEPLOYMENT_NOT_FOUND": 404,
    "ERR_EQUIPMENT_ORDER_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_STORE_VERSION": 412,
    "ERR_STALE_SANCTION_CASE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_TERMINAL_DEPLOYMENT_NOT_ACTIVE": 409,
    "ERR_INVESTIGATION_NOT_SUBSTANTIATED": 409,
    "ERR_REMAND_LIMIT_REACHED": 409,
    "ERR_STORE_NOT_AUTHORIZED": 403,
    "ERR_OWNER_PERMANENTLY_DISQUALIFIED": 403,
    "ERR_OWNER_BARRED": 403,
    "ERR_REPLY_WINDOW_CLOSED": 409,
    "ERR_REPLY_WINDOW_OPEN": 409,
    "ERR_ADMIN_REVIEW_WINDOW_CLOSED": 409,
    "ERR_CMP_ELECTION_WINDOW_CLOSED": 409,
    "ERR_ENFORCEMENT_NOT_DUE": 409,
    "ERR_VISIT_WINDOW_NOT_OPEN": 409,
    "ERR_PERIOD_NOT_ELAPSED": 409,
    "ERR_INSPECTOR_WINDOW_CONFLICT": 409,
    "ERR_TERMINAL_ALREADY_COMMITTED": 409,
    "ERR_REDEMPTION_PERIOD_OVERLAP": 409,
    "ERR_DUPLICATE_TERMINAL_SERIAL": 409,
    "ERR_DUPLICATE_PERIOD_INDEX": 409,
    "ERR_APPLICATION_ALREADY_OPEN": 409,
    "ERR_STORE_TERMINAL_SLOTS_EXCEEDED": 409,
    "ERR_INSPECTOR_DAILY_LIMIT_EXCEEDED": 409,
    "ERR_DEPOT_STOCK_EXHAUSTED": 409,
    "ERR_STAPLE_STOCK_INSUFFICIENT": 422,
    "ERR_CRITERION_B_NOT_MET": 422,
    "ERR_DEPTH_OF_STOCK_INSUFFICIENT": 422,
    "ERR_INSUFFICIENT_EVIDENCE": 422,
    "ERR_TRIGGER_PERIOD_NOT_FLAGGED": 422,
    "ERR_CMP_NOT_AVAILABLE": 409,
    "ERR_CMP_OVERPAYMENT": 422,
    "ERR_NO_REDEMPTION_HISTORY": 422,
    "ERR_NO_ELIGIBLE_ITEMS": 422,
    "ERR_SPLIT_TENDER_SHORTFALL": 422,
    "ERR_SANCTION_TYPE_NOT_ALLOWED": 422,
    "ERR_REDEMPTION_PERIOD_CLOSED": 409,
    "ERR_TRANSFER_CMP_OUTSTANDING": 409,
    "ERR_OWNERSHIP_UNCHANGED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.current = CLOCK_EPOCH

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt

    def reset(self):
        self.current = CLOCK_EPOCH


clock = Clock()


def now():
    return clock.now()


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_months(dt, months):
    if months is None:
        return None
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
            if day < 1:
                raise


def whole_days_between(later, earlier):
    """Whole (floored) days between two instants."""
    return int((later - earlier).total_seconds() // 86400)


# ---------------------------------------------------------------------------
# Rounding discipline (PRD §2.7)
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Half-up (away from zero) rounding of an exact rational to an integer."""
    frac = Fraction(value)
    if frac >= 0:
        return int((frac.numerator * 2 + frac.denominator) // (frac.denominator * 2))
    pos = -frac
    return -int((pos.numerator * 2 + pos.denominator) // (pos.denominator * 2))


def floor_div(numerator, denominator):
    return numerator // denominator


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    COLLECTIONS = (
        "owners", "stores", "applications", "inspectors", "store_visits",
        "pos_transactions", "redemption_periods", "investigations",
        "sanction_cases", "cmp_elections", "penalty_ledger_entries",
        "equipment_depots", "ebt_terminals", "terminal_deployments",
        "equipment_orders",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.fns_sequence = 1000001

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_fns_number(self):
        value = self.fns_sequence
        self.fns_sequence += 1
        return "FNS-%07d" % value


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_new(row):
    instant = now()
    row["id"] = new_id()
    row["created_at"] = instant
    row["updated_at"] = instant
    row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    row["updated_at"] = now()
    row["version"] = row.get("version", 1) + 1
    return row


def ordered(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(rows, pagination):
    meta = _meta()
    meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Auth / RBAC (PRD §2.1, §2.8 rules 1-2)
# ---------------------------------------------------------------------------
ROLES = ("Anonymous", "RetailerOwner", "StoreClerk", "Inspector", "FnsAdmin",
         "FnsAnalyst", "AdminReviewOfficer")


def require_auth(roles, anonymous_allowed=False):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if anonymous_allowed:
        # POST /owners: the single endpoint that does not require the headers.
        if role is not None and role not in roles:
            fail("ERR_ROLE_NOT_PERMITTED")
        g.user_id = user_id
        g.role = role
        return {"user_id": user_id, "role": role}
    if not user_id or not role:
        fail("ERR_MISSING_USER_CONTEXT")
    if role not in roles:
        fail("ERR_ROLE_NOT_PERMITTED")
    g.user_id = user_id
    g.role = role
    return {"user_id": user_id, "role": role}


def actor():
    return getattr(g, "user_id", None)


def actor_role():
    return getattr(g, "role", None)


# ---------------------------------------------------------------------------
# Path / body reference resolution (PRD §2.8 rules 3-4, §2.9)
# ---------------------------------------------------------------------------
def resolve_path(collection, identifier, error_id):
    row = collection.get(identifier)
    if row is None:
        fail(error_id)
    return row


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        return {"__invalid__": True}
    return body


def resolve_body_ref(body, field, collection, error_id, optional=False):
    if not isinstance(body, dict):
        return None
    if field not in body or body[field] is None:
        if optional:
            return None
        return None  # absence is a schema problem, handled at priority 7
    value = body[field]
    if not isinstance(value, str):
        fail(error_id)
    row = collection.get(value)
    if row is None:
        fail(error_id)
    return row


# ---------------------------------------------------------------------------
# Schema validation helpers (PRD §2.8 rule 7)
# ---------------------------------------------------------------------------
def bad_request(message="Request body failed validation."):
    raise ApiError("ERR_INVALID_REQUEST", message)


def ensure_object(body):
    if not isinstance(body, dict) or body.get("__invalid__"):
        bad_request("Request body must be a JSON object.")


def req_str(body, field, allow_empty=False):
    value = body.get(field)
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % field)
    if not allow_empty and value == "":
        bad_request("Field '%s' must not be empty." % field)
    return value


def opt_str(body, field, default=None, allow_empty=True):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % field)
    if not allow_empty and value == "":
        bad_request("Field '%s' must not be empty." % field)
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(body, field, minimum=None, maximum=None):
    value = body.get(field)
    if not _is_int(value):
        bad_request("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '%s' must be <= %s." % (field, maximum))
    return value


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, minimum, maximum)


def opt_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad_request("Field '%s' must be a number." % field)
    return value


def req_bool(body, field):
    value = body.get(field)
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % field)
    return value


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return req_bool(body, field)


def req_enum(body, field, allowed):
    value = body.get(field)
    if not isinstance(value, str) or value not in allowed:
        bad_request("Field '%s' must be one of %s." % (field, sorted(allowed)))
    return value


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, allowed)


def req_dt(body, field):
    value = body.get(field)
    parsed = parse_dt(value)
    if parsed is None:
        bad_request("Field '%s' must be an ISO-8601 timestamp." % field)
    return parsed


def req_array(body, field, non_empty=True):
    value = body.get(field)
    if not isinstance(value, list):
        bad_request("Field '%s' must be an array." % field)
    if non_empty and not value:
        bad_request("Field '%s' must not be empty." % field)
    return value


def opt_array(body, field, default=None, non_empty=True):
    if field not in body or body[field] is None:
        return default
    return req_array(body, field, non_empty)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def pagination_args():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad_request("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad_request("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad_request("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination_args()
    total = len(rows)
    page = rows[offset:offset + limit]
    return [serializer(r) for r in page], {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }


def filter_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def filter_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    low = value.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    bad_request("Query parameter '%s' must be a boolean." % name)


# ---------------------------------------------------------------------------
# Per-request mutation batching: one version bump per row per request (§2.5)
# ---------------------------------------------------------------------------
def mark(row):
    """Record that `row` was mutated by this request."""
    if row is None:
        return None
    dirty = getattr(g, "_dirty_rows", None)
    if dirty is None:
        dirty = []
        g._dirty_rows = dirty
    for existing in dirty:
        if existing is row:
            return row
    dirty.append(row)
    return row


def commit():
    """Apply exactly one updated_at/version bump to every mutated row."""
    dirty = getattr(g, "_dirty_rows", None) or []
    for row in dirty:
        touch(row)
    g._dirty_rows = []
