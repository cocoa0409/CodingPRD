"""Core utilities: in-memory store, logical clock, response envelope,
errors, validation helpers, and calculation functions.

Every structural name (headers, envelope fields, pagination fields,
error ids, OCC field) is taken verbatim from PRD.md / SCAFFOLD.yaml.
"""
import itertools
import random
import string
import uuid
import calendar
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import g, request, jsonify

# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
ROLES = {"Sourcing", "Analyst", "FinanceApprover", "CostCenterOwner",
         "Vendor", "SystemAdmin"}

ALL_ROLES = "ALL"  # every known role may read

# ---------------------------------------------------------------------------
# In-memory store (wiped on every process boot; no seeding)
# ---------------------------------------------------------------------------
_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


class Store:
    def __init__(self):
        self.vendors = {}
        self.contracts = {}
        self.services = {}
        self.invoices = {}
        self.line_items = {}
        self.disputes = {}
        self.credits = {}
        self.cost_centers = {}
        self.allocations = {}
        self.recommendations = {}
        # Logical clock — startup default per PRD §3.1 (dt set below once
        # parse_dt is defined)
        self.clock_raw = "2026-05-01T00:00:00Z"
        self.clock_dt = None


db = Store()

# ---------------------------------------------------------------------------
# Ids & timestamps
# ---------------------------------------------------------------------------
def new_id():
    # Opaque UUID string, no type prefix (PRD §2.4)
    return str(uuid.uuid4())


def now_iso():
    # Real server timestamp, ISO 8601 UTC, three fractional digits (PRD §2.2/§2.4)
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def req_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alnum) for _ in range(20))


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if value is None:
        return None
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


db.clock_dt = parse_dt(db.clock_raw)


def format_dt_like(original, dt):
    """Format a computed datetime mirroring the precision of the original."""
    if original and "." in str(original):
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def add_months(dt, months):
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def days_between(start_str, end_str):
    """Half-open day count: end date minus start date (PRD §3.4)."""
    start = parse_dt(start_str)
    end = parse_dt(end_str)
    return (end - start).days


# ---------------------------------------------------------------------------
# Errors (SCAFFOLD §1.6 / PRD §5)
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def _meta(pagination=None):
    m = {"api_request_id": req_id(), "api_request_timestamp": now_iso()}
    if pagination is not None:
        m.update(pagination)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, pagination):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def created_list(items):
    """201 response wrapping an array payload (bulk create)."""
    body = {
        "meta": _meta(),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 201


def error_body(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC (PRD §2.1)
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or invalid X-User-ID / X-User-Role headers.")
    g.user_id = uid
    g.role = role
    return uid, role


def authorize(allowed):
    if allowed == ALL_ROLES:
        return
    if g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Acting role not permitted for this operation.")


def guard(allowed):
    """Decorator: authenticate then authorize before the handler runs."""
    from functools import wraps

    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **k):
            authenticate()
            authorize(allowed)
            return fn(*a, **k)
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# Body & field validation (PRD §2.9 band 3 -> ERR_VALIDATION 422)
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object.")
    return body


def require(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {f}")


def check_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError("ERR_VALIDATION", 422, f"Illegal value for {field}: {value}")


def check_non_negative_int(body, fields):
    for f in fields:
        if f in body and body[f] is not None:
            v = body[f]
            if not isinstance(v, bool) and isinstance(v, int):
                if v < 0:
                    raise ApiError("ERR_VALIDATION", 422,
                                   f"{f} must be non-negative.")
            else:
                raise ApiError("ERR_VALIDATION", 422, f"{f} must be an integer.")


def as_int_nonneg(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {field}")
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be an integer.")
    if v < 0:
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be non-negative.")
    return v


def as_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be a boolean.")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def get_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = int(offset) if offset is not None else 0
    except (ValueError, TypeError):
        offset = 0
    if limit > 100:
        limit = 100
    if limit < 1:
        limit = 1
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    """items: full list already ordered. Returns (page, pagination_meta)."""
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    meta = {"limit": limit, "offset": offset,
            "total_count": total, "has_more": has_more}
    return page, meta


def ordered(values):
    """Order a collection of entity dicts by created_at ascending (insertion)."""
    return sorted(values, key=lambda d: d["_seq"])


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def touch(entity):
    """Bump version + updated_at for a mutated versioned entity."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def base_common(extra):
    ts = now_iso()
    d = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
         "_seq": next_seq()}
    d.update(extra)
    return d


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD §1.3 / PRD §3)
# ---------------------------------------------------------------------------
SAAS_PLATFORM_FEE_CENTS = 5000
UTILIZATION_THRESHOLD_PCT = Decimal("70.00")
MAX_DISPUTE_ROUNDS = 2
WEIGHT_SUM_REQUIRED = Decimal("100.00")
CYCLE_DAYS = Decimal(30)
ANNUAL_MONTHS = 12


def round_half_up_int(dec_value):
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_utilization(active_quantity, contracted_quantity):
    if contracted_quantity == 0:
        return 0.0
    val = (Decimal(active_quantity) / Decimal(contracted_quantity) * Decimal(100))
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _tier_discount(qty, volume_tier_enabled):
    if not volume_tier_enabled:
        return Decimal("0.00")
    if qty >= 100:
        return Decimal("0.15")
    if qty >= 50:
        return Decimal("0.10")
    if qty >= 10:
        return Decimal("0.05")
    return Decimal("0.00")


def compute_expected_amount(service, contract, line, variant):
    """invoice_line_expected_amount (SCAFFOLD §1.3 / PRD §3.4)."""
    if variant == "PROVISIONAL":
        qty = service["contracted_quantity"]
        proration = Decimal(1)
    else:  # FINAL
        qty = line["billed_quantity"]
        billed_days = days_between(line["billing_period_start"],
                                   line["billing_period_end"])
        proration = Decimal(billed_days) / CYCLE_DAYS
    discount = _tier_discount(qty, contract["volume_tier_enabled"])
    base = Decimal(service["unit_rate_cents"]) * Decimal(qty)
    discounted_prorated = base * (Decimal(1) - discount) * proration
    rounded = round_half_up_int(discounted_prorated)
    fee = SAAS_PLATFORM_FEE_CENTS if service["service_type"] == "SAAS_SUBSCRIPTION" else 0
    return rounded + fee


def compute_projected_savings(service, target_quantity):
    seats_cut = service["contracted_quantity"] - target_quantity
    if seats_cut < 0:
        seats_cut = 0
    return seats_cut * service["unit_rate_cents"] * ANNUAL_MONTHS


def compute_realized_savings(service, contract, target_quantity, now_dt):
    seats_cut = service["contracted_quantity"] - target_quantity
    if seats_cut < 0:
        seats_cut = 0
    term_end = parse_dt(contract["term_end"])
    months_remaining = ((term_end.year - now_dt.year) * 12
                        + (term_end.month - now_dt.month) + 1)
    return seats_cut * service["unit_rate_cents"] * months_remaining


def compute_allocation_shares(net_amount_cents, alloc_specs):
    """chargeback_allocation (SCAFFOLD §1.3 / PRD §3.6).

    alloc_specs: list of dicts with keys 'weight' (Decimal), 'seq' (int from
    cost center for tie-break), and an opaque 'ref'. Returns list of
    (ref, amount_cents) preserving input order.
    """
    net = Decimal(net_amount_cents)
    rounded = []
    for spec in alloc_specs:
        raw = net * spec["weight"] / Decimal(100)
        rounded.append(round_half_up_int(raw))
    remainder = net_amount_cents - sum(rounded)
    # top-weight allocation: highest weight_pct, tie-break earliest cost center seq
    top_idx = 0
    best = (alloc_specs[0]["weight"], -alloc_specs[0]["cc_seq"])
    for i, spec in enumerate(alloc_specs):
        key = (spec["weight"], -spec["cc_seq"])
        if key > best:
            best = key
            top_idx = i
    results = []
    for i, spec in enumerate(alloc_specs):
        amt = rounded[i] + (remainder if i == top_idx else 0)
        results.append((spec["ref"], amt))
    return results


# ---------------------------------------------------------------------------
# Recompute helpers
# ---------------------------------------------------------------------------
def recompute_contract_committed(contract):
    total = 0
    for s in db.services.values():
        if s["contract_id"] == contract["id"] and s["status"] in ("ACTIVE", "RIGHTSIZED"):
            total += s["unit_rate_cents"] * s["contracted_quantity"]
    contract["monthly_committed_cost_cents"] = total


def lines_of_invoice(invoice_id):
    return [li for li in db.line_items.values() if li["invoice_id"] == invoice_id]


def recompute_invoice_billed_net(invoice):
    lines = lines_of_invoice(invoice["id"])
    billed = sum(li["billed_amount_cents"] for li in lines)
    credited = sum(li["credited_amount_cents"] for li in lines)
    invoice["billed_amount_cents"] = billed
    invoice["net_amount_cents"] = billed - credited


def find(coll, ident, err_id):
    e = coll.get(ident)
    if e is None:
        raise ApiError(err_id, 404, f"{err_id}: {ident}")
    return e


def open_disputes_on_invoice(invoice_id):
    line_ids = {li["id"] for li in lines_of_invoice(invoice_id)}
    return [d for d in db.disputes.values()
            if d["invoice_line_item_id"] in line_ids
            and d["status"] in ("SUBMITTED", "VENDOR_RESPONDED", "RESUBMITTED")]
