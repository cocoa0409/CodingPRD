"""Core plumbing: errors, in-memory store, logical clock, envelope, auth,
validation helpers, decimal math, shared lookups/serializers.

Storage is in-memory only (module-level dicts). The store starts empty on
every boot; nothing is seeded.
"""
import re
import uuid
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR
from functools import wraps

from flask import request, g, jsonify


# ----------------------------- errors -----------------------------

class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


def bad_request(msg):
    err("ERR_INVALID_REQUEST", 400, msg)


# ----------------------------- store ------------------------------

db = {
    "foresters": {},
    "landowners": {},
    "buyers": {},
    "contractors": {},
    "tracts": {},
    "stands": {},
    "cruises": {},
    "prescriptions": {},
    "sales": {},
    "bids": {},
    "contracts": {},
    "bonds": {},
    "tickets": {},
    "settlements": {},
    "inspections": {},
    "obligations": {},
    "surveys": {},
    "valuations": {},
}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


# --------------------------- logical clock ------------------------
# Startup default is exactly 2026-05-01T00:00:00Z; never wall-clock.

_clock = {"dt": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return _clock["dt"]


def today():
    return _clock["dt"].date()


def set_clock(dt):
    _clock["dt"] = dt


def fmt_ts(dt):
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000)


def now_iso():
    return fmt_ts(now())


ISO_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$")


def parse_iso_datetime(s):
    """Parse an ISO-8601 datetime; returns aware UTC datetime."""
    if not isinstance(s, str) or not ISO_DT_RE.match(s.strip()):
        bad_request("malformed datetime: %r" % (s,))
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        bad_request("malformed datetime: %r" % (s,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date_str(s):
    if not isinstance(s, str) or not DATE_RE.match(s.strip()):
        bad_request("malformed date: %r" % (s,))
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        bad_request("malformed date: %r" % (s,))


def add_months(dt, months):
    total = (dt.year * 12 + (dt.month - 1)) + months
    y, m = total // 12, total % 12 + 1
    # clamp day to days in month
    if m == 12:
        last = date(y, 12, 31).day
    else:
        last = (date(y, m + 1, 1) - timedelta(days=1)).day
    d = min(dt.day, last)
    return dt.replace(year=y, month=m, day=d)


def add_years_date(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29 -> Feb 28
        return d.replace(year=d.year + years, day=28)


# --------------------------- decimal math -------------------------

def D(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def rhu(x):
    """round-half-up to integer, returned as int."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(x):
    """round-half-up to 2 decimal places, returned as Decimal."""
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def dfloor(x):
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_FLOOR))


# ----------------------------- envelope ---------------------------

def _req_id():
    return "req_" + uuid.uuid4().hex[:24]


def success(data, code=200, is_array=False, page_meta=None):
    meta = {"api_request_id": _req_id(), "api_request_timestamp": now_iso()}
    if page_meta is not None:
        meta.update(page_meta)
    body = {
        "meta": meta,
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    return jsonify(body), code


def error_response(e):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": now_iso()},
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.status


# ------------------------------ auth ------------------------------

ALL_ROLES = {
    "PlatformAdmin", "Forester", "Landowner", "Buyer", "Contractor",
    "AgencyInspector",
}


def require_roles(*roles):
    """Decorator: validate X-User-ID / X-User-Role headers, then role gate."""
    allowed = set(roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ALL_ROLES:
                err("ERR_UNAUTHENTICATED", 401,
                    "missing or invalid X-User-ID / X-User-Role headers")
            if allowed and role not in allowed:
                err("ERR_FORBIDDEN_ROLE", 403,
                    "role %s is not authorized for this endpoint" % role)
            g.uid = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


# -------------------------- body validation -----------------------

def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad_request("request body must be a JSON object")
    return data


def check_known(body, allowed):
    for k in body:
        if k not in allowed:
            bad_request("unknown field: %s" % k)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def f_str(body, name, required=True, default=None):
    v = body.get(name)
    if v is None:
        if required:
            bad_request("missing required field: %s" % name)
        return default
    if not isinstance(v, str):
        bad_request("field %s must be a string" % name)
    return v


def f_int(body, name, required=True, default=None, minv=None):
    v = body.get(name)
    if v is None:
        if required:
            bad_request("missing required field: %s" % name)
        return default
    if not is_int(v):
        bad_request("field %s must be an integer" % name)
    if minv is not None and v < minv:
        bad_request("field %s must be >= %s" % (name, minv))
    return v


def f_num(body, name, required=True, default=None, minv=None, gt=None):
    v = body.get(name)
    if v is None:
        if required:
            bad_request("missing required field: %s" % name)
        return default
    if not is_num(v):
        bad_request("field %s must be a number" % name)
    if minv is not None and v < minv:
        bad_request("field %s must be >= %s" % (name, minv))
    if gt is not None and not (v > gt):
        bad_request("field %s must be > %s" % (name, gt))
    return v


def f_enum(body, name, allowed, required=True, default=None):
    v = body.get(name)
    if v is None:
        if required:
            bad_request("missing required field: %s" % name)
        return default
    if v not in allowed:
        bad_request("field %s must be one of %s" % (name, sorted(allowed)))
    return v


def f_date(body, name, required=True, default=None):
    v = body.get(name)
    if v is None:
        if required:
            bad_request("missing required field: %s" % name)
        return default
    parse_date_str(v)  # validates
    return v


def f_datetime(body, name, required=True, default=None):
    v = body.get(name)
    if v is None:
        if required:
            bad_request("missing required field: %s" % name)
        return default
    parse_iso_datetime(v)  # validates
    return v


def f_array(body, name, required=True, default=None):
    v = body.get(name)
    if v is None:
        if required:
            bad_request("missing required field: %s" % name)
        return default
    if not isinstance(v, list):
        bad_request("field %s must be an array" % name)
    return v


# --------------------------- entity helpers -----------------------

def new_common(ent):
    """Attach system fields for a fully-versioned entity."""
    ent["id"] = new_id()
    ts = now_iso()
    ent["created_at"] = ts
    ent["updated_at"] = ts
    ent["version"] = 1
    ent["_seq"] = next_seq()
    return ent


def new_light(ent):
    """Registry entities carry only id + created_at (no updated_at/version)."""
    ent["id"] = new_id()
    ent["created_at"] = now_iso()
    ent["_seq"] = next_seq()
    return ent


def bump(ent):
    ent["version"] += 1
    ent["updated_at"] = now_iso()


def pub(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


# --------------------------- lookups ------------------------------

def get_party(uid):
    for coll in ("foresters", "landowners", "buyers", "contractors"):
        if uid in db[coll]:
            return db[coll][uid]
    return None


def get_tract(tid):
    t = db["tracts"].get(tid)
    if t is None:
        err("ERR_TRACT_NOT_FOUND", 404, "tract not found: %s" % tid)
    return t


def get_stand(sid):
    s = db["stands"].get(sid)
    if s is None:
        err("ERR_STAND_NOT_FOUND", 404, "stand not found: %s" % sid)
    return s


def get_cruise(cid):
    c = db["cruises"].get(cid)
    if c is None:
        err("ERR_CRUISE_NOT_FOUND", 404, "cruise not found: %s" % cid)
    return c


def get_prescription(pid):
    p = db["prescriptions"].get(pid)
    if p is None:
        err("ERR_PRESCRIPTION_NOT_FOUND", 404, "prescription not found: %s" % pid)
    return p


def get_sale(sid):
    s = db["sales"].get(sid)
    if s is None:
        err("ERR_SALE_NOT_FOUND", 404, "sale not found: %s" % sid)
    return s


def get_bid(bid):
    b = db["bids"].get(bid)
    if b is None:
        err("ERR_BID_NOT_FOUND", 404, "bid not found: %s" % bid)
    return b


def get_contract(cid):
    c = db["contracts"].get(cid)
    if c is None:
        err("ERR_CONTRACT_NOT_FOUND", 404, "contract not found: %s" % cid)
    return c


def get_bond(bid):
    b = db["bonds"].get(bid)
    if b is None:
        err("ERR_BOND_NOT_FOUND", 404, "bond not found: %s" % bid)
    return b


def get_ticket(tid):
    t = db["tickets"].get(tid)
    if t is None:
        err("ERR_TICKET_NOT_FOUND", 404, "scale ticket not found: %s" % tid)
    return t


def get_settlement(sid):
    s = db["settlements"].get(sid)
    if s is None:
        err("ERR_SETTLEMENT_NOT_FOUND", 404, "settlement not found: %s" % sid)
    return s


def get_inspection(iid):
    i = db["inspections"].get(iid)
    if i is None:
        err("ERR_INSPECTION_NOT_FOUND", 404, "inspection not found: %s" % iid)
    return i


def get_obligation(oid):
    o = db["obligations"].get(oid)
    if o is None:
        err("ERR_OBLIGATION_NOT_FOUND", 404, "obligation not found: %s" % oid)
    return o


def get_survey(sid):
    s = db["surveys"].get(sid)
    if s is None:
        err("ERR_SURVEY_NOT_FOUND", 404, "survey not found: %s" % sid)
    return s


def get_valuation(vid):
    v = db["valuations"].get(vid)
    if v is None:
        err("ERR_VALUATION_NOT_FOUND", 404, "valuation not found: %s" % vid)
    return v


def party_or_404(pid):
    p = get_party(pid)
    if p is None:
        err("ERR_PARTY_NOT_FOUND", 404, "party not found: %s" % pid)
    return p


# cross-aggregate helpers

def bond_of_contract(contract_id):
    for b in db["bonds"].values():
        if b["contract_id"] == contract_id:
            return b
    return None


def obligation_of_contract(contract_id):
    for o in db["obligations"].values():
        if o["contract_id"] == contract_id:
            return o
    return None


def sale_of_contract(c):
    return db["sales"].get(c["sale_id"])


def tract_of_sale(sale):
    return db["tracts"].get(sale["tract_id"])


def stand_of_sale(sale):
    return db["stands"].get(sale["stand_id"])


def prescription_of_sale(sale):
    return db["prescriptions"].get(sale["prescription_id"])


def cruise_of_sale(sale):
    p = prescription_of_sale(sale)
    return db["cruises"].get(p["cruise_id"]) if p else None


def tract_of_contract(c):
    sale = sale_of_contract(c)
    return tract_of_sale(sale) if sale else None


def open_major_findings(contract_id):
    n = 0
    for i in db["inspections"].values():
        if (i["contract_id"] == contract_id and i["status"] == "NONCOMPLIANT"
                and i.get("severity") == "MAJOR"):
            n += 1
    return n


def contract_out(c):
    o = pub(c)
    o["open_major_findings_count"] = open_major_findings(c["id"])
    total = 0
    by_species = {}
    for t in db["tickets"].values():
        if t["contract_id"] == c["id"] and t["status"] == "VERIFIED":
            total += t["bf_governing"]
            by_species[t["species"]] = by_species.get(t["species"], 0) + t["bf_governing"]
    o["cumulative_verified_bf"] = total
    o["verified_volume_by_species"] = [
        {"species": s, "volume_bf": v} for s, v in sorted(by_species.items())
    ]
    return o


def settlement_out(s):
    o = pub(s)
    interest = 0
    if s["status"] == "APPROVED" and s.get("due_date"):
        due = parse_date_str(s["due_date"])
        days_late = (today() - due).days
        if days_late < 0:
            days_late = 0
        periods = days_late // 30
        if periods > 0:
            interest = dfloor(D(s["net_cents"]) * D("0.015") * periods)
    o["accrued_interest_cents"] = interest
    return o


# --------------------------- pagination ---------------------------

def paginate(items, filters):
    """items: iterable of entity dicts. filters: {param: field_name}."""
    out = list(items)
    for param, field in filters.items():
        v = request.args.get(param)
        if v is not None:
            out = [e for e in out if str(e.get(field)) == v]
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            bad_request("limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            bad_request("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            bad_request("offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            bad_request("offset must be >= 0")
    out.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(out)
    page = out[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


# --------------------- state-machine error helpers -----------------

def check_transition(ent, from_states, terminal_states, what):
    """Terminal lockdown first, then generic invalid transition.

    A from-state that is itself listed as terminal (e.g. Settlement PAID,
    which permits only the PAID -> REFUNDED compensating transition) is
    exempt from the lockdown for this trigger."""
    if ent["status"] in (terminal_states - set(from_states)):
        err("ERR_ALREADY_TERMINAL", 409,
            "%s is in terminal state %s" % (what, ent["status"]))
    if ent["status"] not in from_states:
        err("ERR_INVALID_TRANSITION", 409,
            "cannot perform this action on %s in state %s" % (what, ent["status"]))
