"""Core infrastructure: in-memory store, logical clock, response envelope,
errors, auth and schema-validation helpers.

Storage is in-memory only. Nothing is seeded at import time or at boot.
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import jsonify, request

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLE_ADMIN = "TicketOpsAdmin"
ROLE_REVENUE = "RevenueManager"
ROLE_SALES = "SalesRep"
ROLE_HOLDER = "AccountHolder"
ALL_ROLES = (ROLE_ADMIN, ROLE_REVENUE, ROLE_SALES, ROLE_HOLDER)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

DEFAULT_CLOCK_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.seasons = {}
        self.games = {}
        self.seats = {}
        self.plans = {}
        self.reps = {}
        self.accounts = {}
        self.orders = {}
        self.holds = {}
        self.packages = {}
        self.transfers = {}
        self.clock = DEFAULT_CLOCK_UTC


db = Store()


def now():
    return db.clock


def set_clock(dt):
    db.clock = dt


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_iso(value):
    """Parse an ISO-8601 UTC instant.  Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days(n):
    return timedelta(days=n)


def floor_days_between(later, earlier):
    """Whole days between two instants: elapsed seconds // 86400."""
    delta = later - earlier
    secs = delta.total_seconds()
    if secs < 0:
        return 0
    return int(secs // 86400)


# ---------------------------------------------------------------------------
# Money helpers (PRD 2.6) - integer cents, round half up
# ---------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value):
    """Round a Decimal to whole cents, half-up (away from zero at .5)."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round to exactly two decimal places, half-up.  Returns a float."""
    return float(D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


def bad_request(message="Request failed schema validation."):
    err("ERR_INVALID_REQUEST", 400, message)


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": iso(now())}


def _convert(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict((k, _convert(v)) for k, v in value.items() if not k.startswith("_"))
    if isinstance(value, (list, tuple)):
        return [_convert(v) for v in value]
    return value


def serialize(row):
    if row is None:
        return {}
    return dict((k, _convert(v)) for k, v in row.items() if not k.startswith("_"))


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": serialize(data) if isinstance(data, dict) else data}
    return jsonify(body), status


def ok_list(rows, status=200):
    body = {"meta": _meta(), "response_type": "array", "data": [serialize(r) for r in rows]}
    return jsonify(body), status


def ok_page(rows, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    body = {"meta": meta, "response_type": "array", "data": [serialize(r) for r in rows]}
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---------------------------------------------------------------------------
# Common fields / versioning (PRD 2.4)
# ---------------------------------------------------------------------------
def base_fields():
    stamp = now()
    return {"created_at": stamp, "updated_at": stamp, "version": 1}


def bump(row):
    """Every mutation of a row refreshes updated_at and increments version."""
    if row is None:
        return
    row["updated_at"] = now()
    row["version"] = row.get("version", 0) + 1


# ---------------------------------------------------------------------------
# Auth (ladder rungs 1 and 2)
# ---------------------------------------------------------------------------
class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    @property
    def is_revenue(self):
        return self.role == ROLE_REVENUE

    @property
    def is_sales(self):
        return self.role == ROLE_SALES

    @property
    def is_holder(self):
        return self.role == ROLE_HOLDER


def authenticate():
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not str(user_id).strip():
        err("ERR_UNAUTHENTICATED", 401, "Missing X-User-ID header.")
    if not role or role not in ALL_ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or invalid X-User-Role header.")
    return Caller(str(user_id), role)


def endpoint(*roles):
    """Decorator: rung 1 (authentication) then rung 2 (authorisation)."""
    allowed = set(roles) if roles else set(ALL_ROLES)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            caller = authenticate()
            if caller.role not in allowed:
                err("ERR_UNAUTHORIZED", 403, "Role %s may not invoke this operation." % caller.role)
            return fn(caller, *args, **kwargs)

        return wrapper

    return deco


READ_ROLES = ALL_ROLES


# ---------------------------------------------------------------------------
# Body / query schema helpers (ladder rung 3)
# ---------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        bad_request("Request body must be a JSON object.")
    if not isinstance(data, dict):
        bad_request("Request body must be a JSON object.")
    return data


def req_str(data, field, min_len=1, max_len=None):
    if field not in data or data[field] is None:
        bad_request("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % field)
    if len(value) < min_len:
        bad_request("Field '%s' is too short." % field)
    if max_len is not None and len(value) > max_len:
        bad_request("Field '%s' is too long." % field)
    return value


def opt_str(data, field, default=None, max_len=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % field)
    if max_len is not None and len(value) > max_len:
        bad_request("Field '%s' is too long." % field)
    return value


def req_enum(data, field, members):
    value = req_str(data, field)
    if value not in members:
        bad_request("Field '%s' must be one of %s." % (field, ", ".join(members)))
    return value


def opt_enum(data, field, members, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str) or value not in members:
        bad_request("Field '%s' must be one of %s." % (field, ", ".join(members)))
    return value


def req_int(data, field, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        bad_request("Field '%s' is required." % field)
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '%s' must be <= %s." % (field, maximum))
    return value


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, minimum, maximum)


def req_number(data, field, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        bad_request("Field '%s' is required." % field)
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad_request("Field '%s' must be a number." % field)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '%s' must be <= %s." % (field, maximum))
    return value


def opt_number(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    return req_number(data, field, minimum, maximum)


def req_datetime(data, field):
    if field not in data or data[field] is None:
        bad_request("Field '%s' is required." % field)
    parsed = parse_iso(data[field])
    if parsed is None:
        bad_request("Field '%s' must be an ISO-8601 UTC instant." % field)
    return parsed


def req_id_list(data, field):
    if field not in data or data[field] is None:
        bad_request("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, list) or len(value) == 0:
        bad_request("Field '%s' must be a non-empty array." % field)
    for item in value:
        if not isinstance(item, str) or not item:
            bad_request("Field '%s' must contain id strings." % field)
    if len(set(value)) != len(value):
        bad_request("Field '%s' must not contain duplicates." % field)
    return list(value)


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit))
        except Exception:
            bad_request("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad_request("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset))
        except Exception:
            bad_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad_request("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))


def apply_filters(rows, spec):
    """spec: list of (query-param-name, row-field-name)."""
    out = rows
    for param, field in spec:
        value = request.args.get(param)
        if value is not None:
            out = [r for r in out if r.get(field) == value]
    return out


# ---------------------------------------------------------------------------
# Existence lookups (ladder rungs 4 and 5)
# ---------------------------------------------------------------------------
def find_season(season_id):
    row = db.seasons.get(season_id)
    if row is None:
        err("ERR_SEASON_NOT_FOUND", 404, "Season %s does not exist." % season_id)
    return row


def find_game(game_id):
    row = db.games.get(game_id)
    if row is None:
        err("ERR_GAME_NOT_FOUND", 404, "Game %s does not exist." % game_id)
    return row


def find_seat(seat_id):
    row = db.seats.get(seat_id)
    if row is None:
        err("ERR_SEAT_NOT_FOUND", 404, "Seat %s does not exist." % seat_id)
    return row


def find_plan(plan_id):
    row = db.plans.get(plan_id)
    if row is None:
        err("ERR_PLAN_NOT_FOUND", 404, "Season plan %s does not exist." % plan_id)
    return row


def find_account(account_id):
    row = db.accounts.get(account_id)
    if row is None:
        err("ERR_ACCOUNT_NOT_FOUND", 404, "Account %s does not exist." % account_id)
    return row


def find_order(order_id):
    row = db.orders.get(order_id)
    if row is None:
        err("ERR_ORDER_NOT_FOUND", 404, "Plan order %s does not exist." % order_id)
    return row


def find_hold(hold_id):
    row = db.holds.get(hold_id)
    if row is None:
        err("ERR_HOLD_NOT_FOUND", 404, "Seat hold %s does not exist." % hold_id)
    return row


def find_package(package_id):
    row = db.packages.get(package_id)
    if row is None:
        err("ERR_PACKAGE_NOT_FOUND", 404, "Hospitality package %s does not exist." % package_id)
    return row


def find_transfer(transfer_id):
    row = db.transfers.get(transfer_id)
    if row is None:
        err("ERR_TRANSFER_NOT_FOUND", 404, "Ticket transfer %s does not exist." % transfer_id)
    return row


def find_rep(rep_id):
    row = db.reps.get(rep_id)
    if row is None:
        err("ERR_REP_NOT_FOUND", 404, "Service rep %s does not exist." % rep_id)
    return row
