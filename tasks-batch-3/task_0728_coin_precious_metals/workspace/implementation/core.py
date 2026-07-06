"""Core infrastructure: in-memory store, errors, response envelope, auth,
calculation and validation helpers for the Coin & Precious-Metals Dealer API.

All state is in-memory and wiped on every process start. Nothing is seeded.
"""
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, request, jsonify

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
METALS = {"GOLD", "SILVER", "PLATINUM", "PALLADIUM"}
PRODUCT_TYPES = {"BULLION", "NUMISMATIC"}
ROLES = {"Trader", "SalesAgent", "ComplianceOfficer", "Customer"}
REPORTABLE_THRESHOLD_CENTS = 1_000_000  # $10,000.00

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    """Every collection is a dict keyed by id. Wiped on process start."""

    def __init__(self):
        self.spot_rates = {}
        self.products = {}
        self.inventory_lots = {}
        self.customers = {}
        self.ira_accounts = {}
        self.sell_orders = {}
        self.buy_orders = {}
        self.layaways = {}
        self.consignments = {}
        self.hedge_positions = {}
        self.settlements = {}
        self.appraisers = {}
        self.appraisal_appointments = {}
        self.auction_sessions = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Time / id helpers
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def gen_uuid():
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _serialize(entity):
    """Strip internal (underscore-prefixed) fields."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def _meta(extra=None):
    m = {
        "api_request_id": getattr(g, "request_id", None) or gen_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200, pagination=None):
    is_array = isinstance(data, list)
    if is_array:
        payload = [_serialize(e) for e in data]
    else:
        payload = _serialize(data) if data is not None else {}
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_array else "object",
        "data": payload,
    }
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    """Validate headers (401) and role authorization (403).

    Returns (user_id, role). Raises ApiError otherwise.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        err("ERR_UNAUTHENTICATED", 401, "X-User-ID and X-User-Role headers are required")
    if role not in ROLES or role not in allowed_roles:
        err("ERR_UNAUTHORIZED", 403, "the acting role is not permitted to invoke this endpoint")
    return user_id, role


# ---------------------------------------------------------------------------
# Rounding / calculations
# ---------------------------------------------------------------------------
def rhu(value):
    """Round-half-up a Decimal to an integer number of cents (away from zero on ties)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dec(x):
    return Decimal(str(x))


def unit_melt_value_cents(product, spot_rate):
    """spot * weight * purity, round half up once."""
    spot = _dec(spot_rate["price_per_troy_oz_cents"])
    weight = _dec(product["weight_troy_oz"])
    purity = _dec(product["purity"])
    return rhu(spot * weight * purity)


def unit_sell_price_cents(product, spot_rate):
    melt = unit_melt_value_cents(product, spot_rate)
    premium = product["numismatic_premium_cents"] if product["product_type"] == "NUMISMATIC" else 0
    base = _dec(melt + premium)
    spread = _dec(product["min_sell_spread_pct"])
    return rhu(base * (Decimal(1) + spread))


def unit_buy_payout_cents(product, spot_rate):
    melt = unit_melt_value_cents(product, spot_rate)
    premium = product["numismatic_premium_cents"] if product["product_type"] == "NUMISMATIC" else 0
    base = _dec(melt + premium)
    spread = _dec(product["buy_spread_pct"])
    return rhu(base * (Decimal(1) - spread))


def available_lots_for_product(product_id):
    """AVAILABLE lots (available_qty > 0) for a product, ordered for FIFO:
    (created_at ASC, available_qty ASC, seq ASC). id is never used to break ties."""
    lots = [
        lot for lot in db.inventory_lots.values()
        if lot["product_id"] == product_id and lot["available_qty"] > 0
    ]
    lots.sort(key=lambda l: (l["created_at"], l["available_qty"], l["_seq"]))
    return lots


def aggregate_available_qty(product_id):
    return sum(
        lot["available_qty"]
        for lot in db.inventory_lots.values()
        if lot["product_id"] == product_id and lot["available_qty"] > 0
    )


def sell_cogs_provisional_cents(product_id, quantity):
    lots = available_lots_for_product(product_id)
    total_avail = sum(l["available_qty"] for l in lots)
    if total_avail == 0:
        return 0
    weighted_sum = sum(_dec(l["acquisition_unit_cost_cents"]) * l["available_qty"] for l in lots)
    wavg = rhu(weighted_sum / _dec(total_avail))
    return wavg * quantity


def sell_cogs_final_and_consume(product_id, quantity, commit=True):
    """FIFO consumption. Returns (final_cogs_cents, list_of_(lot, take)).
    When commit is True, mutates the lots (available_qty/sold_qty/status/version/updated_at)."""
    lots = available_lots_for_product(product_id)
    remaining = quantity
    final_cogs = 0
    consumed = []
    for lot in lots:
        if remaining <= 0:
            break
        take = min(remaining, lot["available_qty"])
        final_cogs += take * lot["acquisition_unit_cost_cents"]
        remaining -= take
        consumed.append((lot, take))
    if commit:
        for lot, take in consumed:
            lot["available_qty"] -= take
            lot["sold_qty"] += take
            _recompute_lot_status(lot)
            touch(lot)
    return final_cogs, consumed


def _recompute_lot_status(lot):
    if lot["available_qty"] == 0 and lot["sold_qty"] == lot["total_qty"]:
        lot["status"] = "DEPLETED"
    else:
        lot["status"] = "AVAILABLE"


def hedge_unrealized_cents(position):
    spot = get_spot_for_metal(position["metal"])
    if spot is None:
        return position.get("unrealized_pnl_cents", 0)
    delta = _dec(position["entry_spot_cents"] - spot["price_per_troy_oz_cents"])
    return rhu(delta * _dec(position["short_troy_oz"]))


def get_spot_for_metal(metal):
    for sr in db.spot_rates.values():
        if sr["metal"] == metal:
            return sr
    return None


# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------
def stamp_new(entity):
    """Attach id + common system fields and a monotonic seq to a new entity."""
    ts = now_iso()
    entity["id"] = gen_uuid()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    """Record a mutation: bump version + updated_at."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Request body / validation helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        err("ERR_INVALID_REQUEST", 400, "request body must be a JSON object")
    return body


def bad_request(msg):
    err("ERR_INVALID_REQUEST", 400, msg)


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        bad_request(f"'{field}' is required and must be a non-empty string")
    return v


def require_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        bad_request(f"'{field}' is required and must be an integer")
    if minimum is not None and v < minimum:
        bad_request(f"'{field}' must be >= {minimum}")
    return v


def require_number(body, field, gt=None, ge=None, lt=None, le=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad_request(f"'{field}' is required and must be a number")
    if gt is not None and not (v > gt):
        bad_request(f"'{field}' must be > {gt}")
    if ge is not None and not (v >= ge):
        bad_request(f"'{field}' must be >= {ge}")
    if lt is not None and not (v < lt):
        bad_request(f"'{field}' must be < {lt}")
    if le is not None and not (v <= le):
        bad_request(f"'{field}' must be <= {le}")
    return v


def require_enum(body, field, domain):
    v = body.get(field)
    if not isinstance(v, str) or v not in domain:
        bad_request(f"'{field}' must be one of {sorted(domain)}")
    return v


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        bad_request(f"'{field}' must be a boolean")
    return v


def parse_dt(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        bad_request(f"'{field}' is required and must be an ISO 8601 datetime string")
    raw = v.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        bad_request(f"'{field}' must be a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            bad_request("'limit' must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            bad_request(f"'limit' must be between {PAGINATION_MIN_LIMIT} and {PAGINATION_MAX_LIMIT}")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            bad_request("'offset' must be an integer")
        if offset < 0:
            bad_request("'offset' must be >= 0")
    return limit, offset


def paginate(items):
    """Sort by created_at ASC (seq tiebreak), apply limit/offset, return (page, meta)."""
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
