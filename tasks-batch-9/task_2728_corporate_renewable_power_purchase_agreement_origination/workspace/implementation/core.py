"""Foundation: in-memory store, logical clock, response envelope, errors, auth."""
import functools
import random
import re
import string
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING, getcontext

from flask import g, jsonify, request

getcontext().prec = 60

LOCK = threading.RLock()

# ---------------------------------------------------------------- logical clock
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

ROLES = [
    "Originator",
    "CreditOfficer",
    "DealCommittee",
    "SettlementAnalyst",
    "RegistryAgent",
    "OfftakerRep",
]
ALL_ROLES = list(ROLES)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self.seq = 0
        self.pricing_nodes = {}
        self.offtakers = {}
        self.projects = {}
        self.deals = {}
        self.rounds = {}
        self.allocations = {}
        self.instruments = {}
        self.conditions = {}
        self.periods = {}
        self.intervals = {}
        self.batches = {}
        self.risk_events = {}


db = Store()


def now():
    """Current logical-clock instant (never the host wall clock)."""
    return db.clock


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())


# ------------------------------------------------------------------ time helpers
def iso_ms(dt):
    if dt is None:
        return None
    d = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        d.year, d.month, d.day, d.hour, d.minute, d.second, d.microsecond // 1000)


_FRAC_RE = re.compile(r"\.(\d+)")


def parse_dt(value):
    """Parse an ISO-8601 datetime.  Returns None when unparseable."""
    if isinstance(value, datetime):
        d = value
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    t = value.strip()
    if not t:
        return None
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"

    def _trim(m):
        digits = m.group(1)
        return "." + digits[:6]

    # normalise over-long fractional seconds (fromisoformat accepts <= 6 digits)
    t = re.sub(r"\.(\d+)", _trim, t, count=1)
    try:
        d = datetime.fromisoformat(t)
    except Exception:
        try:
            d = datetime.strptime(t, "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


DAY = 86400


def add_days(dt, days):
    return dt + timedelta(seconds=DAY * int(days))


def floor_days_between(start, end):
    """floor((end - start) / 86400) using exact whole-second arithmetic."""
    return int((end - start).total_seconds() // DAY)


# --------------------------------------------------------------- decimal helpers
def q(value, places):
    exp = Decimal(1).scaleb(-int(places))
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def dfloor(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_FLOOR))


def dceil(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_CEILING))


D0 = Decimal("0")


def to_decimal(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            d = Decimal(s)
        except Exception:
            return None
        if not d.is_finite():
            return None
        return d
    return None


# ----------------------------------------------------------------------- errors
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_PRICING_NODE_NOT_FOUND": 404,
    "ERR_OFFTAKER_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_DEAL_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_ROUND_NOT_FOUND": 404,
    "ERR_CREDIT_SUPPORT_NOT_FOUND": 404,
    "ERR_CONDITION_PRECEDENT_NOT_FOUND": 404,
    "ERR_SETTLEMENT_PERIOD_NOT_FOUND": 404,
    "ERR_ATTRIBUTE_BATCH_NOT_FOUND": 404,
    "ERR_RISK_EVENT_NOT_FOUND": 404,
    "ERR_GUARANTOR_CYCLE": 422,
    "ERR_NOT_DEAL_COUNTERPARTY": 403,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_OFFTAKER_NOT_QUALIFIED": 422,
    "ERR_CREDIT_TIER_DECLINED": 422,
    "ERR_NO_CONFIRMED_ALLOCATION": 422,
    "ERR_OPEN_RISK_CLAIM": 409,
    "ERR_REGISTRY_ACCOUNT_MISSING": 422,
    "ERR_CLAIM_YEAR_OUT_OF_WINDOW": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_CP_DEADLINE_PASSED": 409,
    "ERR_ROUND_EXPIRED": 409,
    "ERR_INELIGIBLE_ISSUER": 422,
    "ERR_INSTRUMENT_TENOR_TOO_SHORT": 422,
    "ERR_RISK_WINDOW_OVERLAP": 409,
    "ERR_SETTLEMENT_PERIOD_OVERLAP": 409,
    "ERR_HOUR_OUTSIDE_PERIOD": 422,
    "ERR_DUPLICATE_METER_HOUR": 409,
    "ERR_DUPLICATE_ALLOCATION": 409,
    "ERR_DUPLICATE_PRICING_NODE": 409,
    "ERR_PRICE_ADJUSTMENT_INVALID": 422,
    "ERR_PROJECT_CAPACITY_EXCEEDED": 422,
    "ERR_ALLOCATION_EXCEEDS_CONTRACTED_MW": 422,
    "ERR_ALLOCATION_INCOMPLETE": 422,
    "ERR_CREDIT_SUPPORT_SHORTFALL": 422,
    "ERR_RELEASE_BREACHES_COVERAGE": 422,
    "ERR_ATTRIBUTE_QUANTITY_EXCEEDS_MINTABLE": 422,
    "ERR_TERMINATION_RIGHT_NOT_VESTED": 422,
    "ERR_NOT_FOUND": 404,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def bad_request(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


# --------------------------------------------------------------------- envelope
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }


def public(value):
    """Recursively render stored values as JSON-ready primitives."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso_ms(value)
    if isinstance(value, dict):
        return dict((k, public(v)) for k, v in value.items()
                    if not str(k).startswith("_"))
    if isinstance(value, (list, tuple)):
        return [public(v) for v in value]
    return value


def success(data, status=200, pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, (list, tuple)) else "object",
        "data": public(data),
    }
    return jsonify(body), status


def error_body(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ------------------------------------------------------------------------- auth
def require_auth(roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    role = role.strip()
    g.user_id = user_id
    g.role = role
    if role not in ROLES:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", "unknown role %s" % role)
    if roles is not None and role not in roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "role %s may not call this endpoint" % role)


def deny_role(message="role may not perform this action"):
    raise ApiError("ERR_ROLE_NOT_PERMITTED", message)


# ------------------------------------------------------------------ versioning
def touch(row):
    """Bump version/updated_at at most once per HTTP request for a given row."""
    if row is None:
        return
    if "version" not in row:
        return
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    key = row.get("id")
    if key in touched:
        return
    touched.add(key)
    row["version"] = int(row.get("version") or 0) + 1
    row["updated_at"] = now()


def endpoint(roles):
    """Wrap a view: serialise access, authenticate, authorise, build envelope."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with LOCK:
                g.touched = set()
                try:
                    require_auth(roles)
                    out = fn(*args, **kwargs)
                    if isinstance(out, tuple):
                        data = out[0]
                        status = out[1] if len(out) > 1 else 200
                        pagination = out[2] if len(out) > 2 else None
                    else:
                        data, status, pagination = out, 200, None
                    return success(data, status, pagination)
                except ApiError as exc:
                    return error_body(exc)
                except Exception as exc:  # pragma: no cover - defensive
                    sys.stderr.write("unhandled: %r\n" % (exc,))
                    import traceback
                    traceback.print_exc()
                    return error_body(ApiError("ERR_INVALID_REQUEST", str(exc)))
        return wrapper
    return decorator


# ------------------------------------------------------- request body / params
def body():
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        bad_request("request body must be a JSON object")
    return raw


def present(data, name):
    return name in data and data.get(name) is not None


def req_str(data, name, min_len=1, max_len=None):
    if not present(data, name):
        bad_request("%s is required" % name)
    v = data.get(name)
    if not isinstance(v, str):
        bad_request("%s must be a string" % name)
    if len(v) < min_len:
        bad_request("%s must have at least %d characters" % (name, min_len))
    if max_len is not None and len(v) > max_len:
        bad_request("%s must have at most %d characters" % (name, max_len))
    return v


def opt_str(data, name, min_len=1, max_len=None, default=None):
    if not present(data, name):
        return default
    return req_str(data, name, min_len, max_len)


def req_enum(data, name, members):
    v = req_str(data, name, 1, None)
    if v not in members:
        bad_request("%s must be one of %s" % (name, sorted(members)))
    return v


def opt_enum(data, name, members, default=None):
    if not present(data, name):
        return default
    return req_enum(data, name, members)


def req_num(data, name, minimum=None, maximum=None, exclusive_min=False,
            exclusive_max=False):
    if not present(data, name):
        bad_request("%s is required" % name)
    return _num(data.get(name), name, minimum, maximum, exclusive_min,
                exclusive_max)


def opt_num(data, name, minimum=None, maximum=None, exclusive_min=False,
            exclusive_max=False, default=None):
    if not present(data, name):
        return default
    return _num(data.get(name), name, minimum, maximum, exclusive_min,
                exclusive_max)


def _num(raw, name, minimum, maximum, exclusive_min, exclusive_max):
    v = to_decimal(raw)
    if v is None:
        bad_request("%s must be a number" % name)
    if minimum is not None:
        if exclusive_min and v <= Decimal(str(minimum)):
            bad_request("%s must be greater than %s" % (name, minimum))
        if not exclusive_min and v < Decimal(str(minimum)):
            bad_request("%s must be at least %s" % (name, minimum))
    if maximum is not None:
        if exclusive_max and v >= Decimal(str(maximum)):
            bad_request("%s must be less than %s" % (name, maximum))
        if not exclusive_max and v > Decimal(str(maximum)):
            bad_request("%s must be at most %s" % (name, maximum))
    return v


def req_int(data, name, minimum=None, maximum=None):
    if not present(data, name):
        bad_request("%s is required" % name)
    return _int(data.get(name), name, minimum, maximum)


def opt_int(data, name, minimum=None, maximum=None, default=None):
    if not present(data, name):
        return default
    return _int(data.get(name), name, minimum, maximum)


def _int(raw, name, minimum, maximum):
    if isinstance(raw, bool):
        bad_request("%s must be an integer" % name)
    v = to_decimal(raw)
    if v is None or v != v.to_integral_value():
        bad_request("%s must be an integer" % name)
    iv = int(v)
    if minimum is not None and iv < minimum:
        bad_request("%s must be at least %d" % (name, minimum))
    if maximum is not None and iv > maximum:
        bad_request("%s must be at most %d" % (name, maximum))
    return iv


def req_dt(data, name):
    if not present(data, name):
        bad_request("%s is required" % name)
    d = parse_dt(data.get(name))
    if d is None:
        bad_request("%s must be an ISO-8601 UTC datetime" % name)
    return d


def opt_dt(data, name, default=None):
    if not present(data, name):
        return default
    return req_dt(data, name)


def req_bool(data, name):
    if not present(data, name):
        bad_request("%s is required" % name)
    return _bool(data.get(name), name)


def opt_bool(data, name, default=None):
    if not present(data, name):
        return default
    return _bool(data.get(name), name)


def _bool(raw, name):
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        low = raw.strip().lower()
        if low in ("true", "1"):
            return True
        if low in ("false", "0"):
            return False
    bad_request("%s must be a boolean" % name)


def req_list(data, name, min_len=0):
    if not present(data, name):
        bad_request("%s is required" % name)
    v = data.get(name)
    if not isinstance(v, list):
        bad_request("%s must be an array" % name)
    if len(v) < min_len:
        bad_request("%s must contain at least %d items" % (name, min_len))
    return v


def opt_list(data, name, default=None):
    if not present(data, name):
        return list(default) if default is not None else []
    v = data.get(name)
    if not isinstance(v, list):
        bad_request("%s must be an array" % name)
    return v


# ------------------------------------------------------------------- pagination
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    v = to_decimal(raw)
    if v is None or v != v.to_integral_value():
        bad_request("%s must be an integer" % name)
    iv = int(v)
    if minimum is not None and iv < minimum:
        bad_request("%s must be at least %d" % (name, minimum))
    if maximum is not None and iv > maximum:
        bad_request("%s must be at most %d" % (name, maximum))
    return iv


def page(rows):
    limit = _query_int("limit", PAGINATION_DEFAULT_LIMIT,
                       PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    offset = _query_int("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(window)) < total,
    }


def filter_enum(name, members):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in members:
        bad_request("%s must be one of %s" % (name, sorted(members)))
    return raw


def filter_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def filter_int(name, minimum=None, maximum=None):
    return _query_int(name, None, minimum, maximum)


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r.get("_seq", 0)))


# --------------------------------------------------------------------- lookups
def find(collection, key, error_id):
    row = collection.get(key)
    if row is None:
        raise ApiError(error_id, "%s not found" % key)
    return row


def get_pricing_node(node_id):
    return find(db.pricing_nodes, node_id, "ERR_PRICING_NODE_NOT_FOUND")


def get_offtaker(off_id):
    return find(db.offtakers, off_id, "ERR_OFFTAKER_NOT_FOUND")


def get_project(project_id):
    return find(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")


def get_deal(deal_id):
    return find(db.deals, deal_id, "ERR_DEAL_NOT_FOUND")


def get_round(round_id):
    return find(db.rounds, round_id, "ERR_ROUND_NOT_FOUND")


def get_allocation(alloc_id):
    return find(db.allocations, alloc_id, "ERR_ALLOCATION_NOT_FOUND")


def get_instrument(inst_id):
    return find(db.instruments, inst_id, "ERR_CREDIT_SUPPORT_NOT_FOUND")


def get_condition(cp_id):
    return find(db.conditions, cp_id, "ERR_CONDITION_PRECEDENT_NOT_FOUND")


def get_period(period_id):
    return find(db.periods, period_id, "ERR_SETTLEMENT_PERIOD_NOT_FOUND")


def get_batch(batch_id):
    return find(db.batches, batch_id, "ERR_ATTRIBUTE_BATCH_NOT_FOUND")


def get_risk_event(event_id):
    return find(db.risk_events, event_id, "ERR_RISK_EVENT_NOT_FOUND")


def deal_allocations(deal_id):
    return sort_created([a for a in db.allocations.values()
                         if a["deal_id"] == deal_id])


def deal_rounds(deal_id):
    return sorted([r for r in db.rounds.values() if r["deal_id"] == deal_id],
                  key=lambda r: r["round_number"])


def deal_instruments(deal_id):
    return sort_created([i for i in db.instruments.values()
                         if i["deal_id"] == deal_id])


def deal_conditions(deal_id):
    return sort_created([c for c in db.conditions.values()
                         if c["deal_id"] == deal_id])


def deal_periods(deal_id):
    return sort_created([p for p in db.periods.values()
                         if p["deal_id"] == deal_id])


def deal_batches(deal_id):
    return sort_created([b for b in db.batches.values()
                         if b["deal_id"] == deal_id])


def deal_risk_events(deal_id):
    return sort_created([e for e in db.risk_events.values()
                         if e["deal_id"] == deal_id])


def period_intervals(period_id):
    return sorted([i for i in db.intervals.values()
                   if i["settlement_period_id"] == period_id],
                  key=lambda i: (i["hour_start"], i.get("_seq", 0)))


def project_deals(project_id):
    return sort_created([d for d in db.deals.values()
                         if d["project_id"] == project_id])


def offtaker_deals(off_id):
    return sort_created([d for d in db.deals.values()
                         if d["anchor_offtaker_id"] == off_id])


def require_counterparty(deal, anchor_only=False):
    """Priority 7 - ERR_NOT_DEAL_COUNTERPARTY for OfftakerRep callers."""
    if g.role != "OfftakerRep":
        return
    if g.user_id == deal.get("anchor_offtaker_id"):
        return
    if not anchor_only:
        for alloc in db.allocations.values():
            if (alloc["deal_id"] == deal["id"]
                    and alloc["offtaker_id"] == g.user_id
                    and alloc["status"] == "CONFIRMED"):
                return
    raise ApiError("ERR_NOT_DEAL_COUNTERPARTY",
                   "caller is not a counterparty of this deal")
