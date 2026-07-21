"""
Natural-Grocery & Consumer Co-op API (task_1017).

Python + Flask, in-memory store, boots empty on every process start.
All structural names (headers, envelope, error ids, pagination fields) are taken
verbatim from PRD.md / SCAFFOLD.yaml.
"""
import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# Constants (pinned by PRD / SCAFFOLD)
# ---------------------------------------------------------------------------
WORKING_MEMBER_DISCOUNT_PCT = Decimal("0.10")
TAX_RATE = Decimal("0.08")
MIN_PATRONAGE_CENTS = 5000
RETENTION_PCT = Decimal("0.20")
WORKING_MEMBER_MIN_HOURS = 12
QUORUM_PCT = Decimal("0.5")
REST_BUFFER_MINUTES = 60
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"

VALID_ROLES = {"CoopAdmin", "FinanceManager", "InventoryManager", "Cashier",
               "BoardAdmin", "Member"}

DEPARTMENTS = {"GROCERY", "PRODUCE", "BULK", "CAFE_DELI"}
UNIT_TYPES = {"EACH", "WEIGHT"}
PROPOSAL_TYPES = {"BYLAW", "BUDGET", "POLICY"}
DEAL_TYPES = {"AD", "MEMBER_DEAL"}
VOTE_CHOICES = {"FOR", "AGAINST", "ABSTAIN"}
ALLOC_METHODS = {"ESTIMATED", "FINAL"}
ADVANCE_ACTIONS = {"SUBMIT", "REQUEST_REVISIONS", "OPEN_VOTING", "WITHDRAW"}

# ---------------------------------------------------------------------------
# Error catalog (id -> http status)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INVALID_REQUEST": 400,
    "ERR_LINE_UNIT_INPUT_INVALID": 400,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FISCAL_YEAR_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_REGISTER_NOT_FOUND": 404,
    "ERR_SALE_NOT_FOUND": 404,
    "ERR_PROMOTION_NOT_FOUND": 404,
    "ERR_SHIFT_NOT_FOUND": 404,
    "ERR_PROPOSAL_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_APPROVABLE": 409,
    "ERR_FISCAL_YEAR_NOT_OPEN": 409,
    "ERR_FISCAL_YEAR_NOT_CLOSED": 409,
    "ERR_LOT_NOT_DRAFT": 409,
    "ERR_REGISTER_CLOSED": 409,
    "ERR_SALE_NOT_BUILDING": 409,
    "ERR_PAYMENT_NOT_UNPAID": 409,
    "ERR_PAYMENT_NOT_PAID": 409,
    "ERR_SALE_NOT_FINALIZED": 409,
    "ERR_PROPOSAL_INVALID_ACTION": 409,
    "ERR_PROPOSAL_NOT_VOTING": 409,
    "ERR_ALLOCATION_NOT_DRAFT": 409,
    "ERR_PROMO_WINDOW_OVERLAP": 409,
    "ERR_SHIFT_OVERLAP": 409,
    "ERR_VENDOR_NOT_APPROVED": 409,
    "ERR_LOT_PRODUCT_MISMATCH": 409,
    "ERR_NOT_ELIGIBLE_VOTER": 409,
    "ERR_ALREADY_VOTED": 409,
    "ERR_QUORUM_NOT_MET": 409,
    "ERR_OPEN_FISCAL_YEAR_EXISTS": 409,
    "ERR_STALE_FISCAL_YEAR_VERSION": 412,
    "ERR_PRODUCT_RECALLED": 422,
    "ERR_INSUFFICIENT_INVENTORY": 422,
    "ERR_EQUITY_BELOW_SHARE_PRICE": 422,
    "ERR_DECLARED_RATE_REQUIRED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http = ERROR_HTTP.get(error_id, 400)


# ---------------------------------------------------------------------------
# In-memory store (empty on every boot; never seeded)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.fiscal_years = {}
        self.members = {}
        self.vendors = {}
        self.products = {}
        self.lots = {}
        self.registers = {}
        self.sales = {}
        self.promotions = {}
        self.shifts = {}
        self.proposals = {}
        self.allocations = {}
        self._seq = 0
        self._member_number = 0
        self.clock = parse_iso(DEFAULT_CLOCK)

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_member_number(self):
        self._member_number += 1
        return self._member_number


# ---------------------------------------------------------------------------
# Time / rounding helpers
# ---------------------------------------------------------------------------
def parse_iso(value):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "invalid datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def rhu(dec_value):
    """Round a Decimal to a whole integer, half-up."""
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(dec_value):
    """Round a Decimal to 2 decimal places, half-up; return float."""
    return float(Decimal(dec_value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, is_array=False, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    return jsonify(body), status


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_list(entities):
    return [serialize(e) for e in entities]


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_entity(bucket, fields):
    eid = str(uuid.uuid4())
    ts = now_iso()
    entity = {"id": eid}
    entity.update(fields)
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = store.next_seq()
    bucket[eid] = entity
    return entity


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def by_seq(entities):
    return sorted(entities, key=lambda e: e["_seq"])


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def get_body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_INVALID_REQUEST", "body must be an object")
    return b


def require_field(b, field):
    if field not in b or b[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", f"missing field: {field}")
    return b[field]


def require_int(b, field):
    val = require_field(b, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_INVALID_REQUEST", f"field must be an integer: {field}")
    return val


def require_str(b, field):
    val = require_field(b, field)
    if not isinstance(val, str) or val == "":
        raise ApiError("ERR_INVALID_REQUEST", f"field must be a string: {field}")
    return val


def parse_pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "invalid limit")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit out of range")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "invalid offset")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset out of range")
    return limit, offset


def paginate(items):
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, pag


# ---------------------------------------------------------------------------
# Lookups (raise 404 with the resource-specific error id)
# ---------------------------------------------------------------------------
def find(bucket, ident, not_found_error):
    entity = bucket.get(ident)
    if entity is None:
        raise ApiError(not_found_error)
    return entity


def open_fiscal_year():
    for fy in store.fiscal_years.values():
        if fy["status"] == "OPEN":
            return fy
    return None


def most_recent_fiscal_year():
    years = list(store.fiscal_years.values())
    if not years:
        return None
    return max(years, key=lambda f: f["_seq"])


# ---------------------------------------------------------------------------
# Derived-field recomputation
# ---------------------------------------------------------------------------
def recompute_product(product):
    posted = [l for l in store.lots.values()
              if l["product_id"] == product["id"] and l["status"] == "POSTED"]
    total = sum(l["qty_on_hand"] for l in posted)
    value = sum(l["qty_on_hand"] * l["unit_cost_cents"] for l in posted)
    product["qty_on_hand_total"] = total
    product["needs_reorder"] = total <= product["reorder_point"]
    product["inventory_value_cents"] = value if isinstance(value, int) else int(round(value))
    touch(product)


def recompute_working_hours(member):
    total = sum(s["hours"] for s in store.shifts.values()
                if s["member_id"] == member["id"] and s["status"] == "COMPLETED")
    total = rhu2(Decimal(str(total)))
    member["working_hours_balance"] = total
    member["is_working_member"] = total >= WORKING_MEMBER_MIN_HOURS


def recompute_quorum(proposal):
    votes_cast = proposal["for_count"] + proposal["against_count"] + proposal["abstain_count"]
    eligible = proposal["eligible_board_member_count"]
    required = -(-eligible // 2)  # ceil(eligible / 2) == ceil(0.5 * eligible)
    proposal["quorum_met"] = votes_cast >= required


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http


@app.errorhandler(Exception)
def handle_unexpected(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Health / readiness
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def health():
    return ok({})


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = auth()
    require_role(role, {"CoopAdmin"})
    b = get_body()
    value = require_field(b, "to_iso8601")
    store.clock = parse_iso(value)
    return ok({})


# ===========================================================================
# FiscalYear
# ===========================================================================
@app.route("/coop/fiscal-years", methods=["POST"])
def create_fiscal_year():
    _, role = auth()
    require_role(role, {"CoopAdmin"})
    b = get_body()
    year = require_int(b, "year")
    patronage_rate = require_field(b, "patronage_rate")
    if not isinstance(patronage_rate, (int, float)) or isinstance(patronage_rate, bool):
        raise ApiError("ERR_INVALID_REQUEST", "invalid patronage_rate")
    equity_share_price_cents = require_int(b, "equity_share_price_cents")
    if open_fiscal_year() is not None:
        raise ApiError("ERR_OPEN_FISCAL_YEAR_EXISTS")
    fy = new_entity(store.fiscal_years, {
        "year": year,
        "status": "OPEN",
        "patronage_rate": patronage_rate,
        "equity_share_price_cents": equity_share_price_cents,
        "total_equity_cents": 0,
        "total_patronage_cents": 0,
    })
    return ok(serialize(fy), 201)


@app.route("/coop/fiscal-years/<fid>", methods=["GET"])
def get_fiscal_year(fid):
    auth()
    fy = find(store.fiscal_years, fid, "ERR_FISCAL_YEAR_NOT_FOUND")
    return ok(serialize(fy))


@app.route("/coop/fiscal-years/<fid>/close", methods=["POST"])
def close_fiscal_year(fid):
    _, role = auth()
    require_role(role, {"FinanceManager"})
    fy = find(store.fiscal_years, fid, "ERR_FISCAL_YEAR_NOT_FOUND")
    if fy["status"] != "OPEN":
        raise ApiError("ERR_FISCAL_YEAR_NOT_OPEN")
    fy["status"] = "CLOSED"
    touch(fy)
    # participation lapse sweep
    for m in store.members.values():
        if m["membership_status"] == "ACTIVE" and m["patronage_cents_ytd"] < MIN_PATRONAGE_CENTS:
            m["membership_status"] = "LAPSED"
            touch(m)
    return ok(serialize(fy))


# ===========================================================================
# Member
# ===========================================================================
@app.route("/coop/members", methods=["POST"])
def create_member():
    _, role = auth()
    require_role(role, {"CoopAdmin"})
    b = get_body()
    full_name = require_str(b, "full_name")
    email = require_str(b, "email")
    is_board_member = b.get("is_board_member", False)
    if not isinstance(is_board_member, bool):
        raise ApiError("ERR_INVALID_REQUEST", "is_board_member must be boolean")
    member = new_entity(store.members, {
        "full_name": full_name,
        "email": email,
        "member_number": store.next_member_number(),
        "is_board_member": is_board_member,
        "membership_status": "PENDING",
        "equity_paid_in_cents": 0,
        "patronage_cents_ytd": 0,
        "working_hours_balance": 0,
        "is_working_member": False,
        "patronage_dividend_cents": 0,
    })
    return ok(serialize(member), 201)


@app.route("/coop/members/<mid>", methods=["GET"])
def get_member(mid):
    auth()
    member = find(store.members, mid, "ERR_MEMBER_NOT_FOUND")
    return ok(serialize(member))


@app.route("/coop/members/<mid>/approve", methods=["POST"])
def approve_member(mid):
    _, role = auth()
    require_role(role, {"CoopAdmin"})
    member = find(store.members, mid, "ERR_MEMBER_NOT_FOUND")
    if member["membership_status"] not in ("PENDING", "LAPSED"):
        raise ApiError("ERR_MEMBER_NOT_APPROVABLE")
    fy = open_fiscal_year() or most_recent_fiscal_year()
    share_price = fy["equity_share_price_cents"] if fy else 0
    if member["equity_paid_in_cents"] < share_price:
        raise ApiError("ERR_EQUITY_BELOW_SHARE_PRICE")
    member["membership_status"] = "ACTIVE"
    touch(member)
    return ok(serialize(member))


@app.route("/coop/members/<mid>/equity-contribution", methods=["POST"])
def equity_contribution(mid):
    _, role = auth()
    require_role(role, {"FinanceManager"})
    member = find(store.members, mid, "ERR_MEMBER_NOT_FOUND")
    b = get_body()
    amount = require_int(b, "amount_cents")
    fy = open_fiscal_year()
    if fy is None:
        raise ApiError("ERR_FISCAL_YEAR_NOT_OPEN")
    member["equity_paid_in_cents"] += amount
    touch(member)
    fy["total_equity_cents"] += amount
    touch(fy)
    return ok(serialize(member))


@app.route("/coop/members/<mid>/drop", methods=["POST"])
def drop_member(mid):
    _, role = auth()
    require_role(role, {"CoopAdmin"})
    member = find(store.members, mid, "ERR_MEMBER_NOT_FOUND")
    if member["membership_status"] == "DROPPED":
        return ok(serialize(member))
    fy = open_fiscal_year()
    if fy is not None and member["equity_paid_in_cents"]:
        fy["total_equity_cents"] -= member["equity_paid_in_cents"]
        touch(fy)
    member["equity_paid_in_cents"] = 0
    member["membership_status"] = "DROPPED"
    touch(member)
    return ok(serialize(member))


# ===========================================================================
# Vendor
# ===========================================================================
@app.route("/coop/vendors", methods=["POST"])
def create_vendor():
    _, role = auth()
    require_role(role, {"InventoryManager"})
    b = get_body()
    name = require_str(b, "name")
    vendor = new_entity(store.vendors, {"name": name, "status": "PENDING"})
    return ok(serialize(vendor), 201)


@app.route("/coop/vendors/<vid>", methods=["GET"])
def get_vendor(vid):
    auth()
    vendor = find(store.vendors, vid, "ERR_VENDOR_NOT_FOUND")
    return ok(serialize(vendor))


@app.route("/coop/vendors/<vid>/set-status", methods=["POST"])
def set_vendor_status(vid):
    _, role = auth()
    require_role(role, {"InventoryManager"})
    vendor = find(store.vendors, vid, "ERR_VENDOR_NOT_FOUND")
    b = get_body()
    status = require_field(b, "status")
    if status not in ("APPROVED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_REQUEST", "invalid target status")
    vendor["status"] = status
    touch(vendor)
    return ok(serialize(vendor))


# ===========================================================================
# Product
# ===========================================================================
@app.route("/coop/products", methods=["POST"])
def create_product():
    _, role = auth()
    require_role(role, {"InventoryManager"})
    b = get_body()
    # body-FK existence first (existence passes before the required-field check)
    vendor_id = require_str(b, "vendor_id")
    find(store.vendors, vendor_id, "ERR_VENDOR_NOT_FOUND")
    sku = require_str(b, "sku")
    name = require_str(b, "name")
    department = require_field(b, "department")
    if department not in DEPARTMENTS:
        raise ApiError("ERR_INVALID_REQUEST", "invalid department")
    unit_type = require_field(b, "unit_type")
    if unit_type not in UNIT_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "invalid unit_type")
    base_price_cents = require_int(b, "base_price_cents")
    reorder_point = require_int(b, "reorder_point")
    reorder_qty = require_int(b, "reorder_qty")
    tare_grams = b.get("tare_grams", 0)
    if tare_grams is None:
        tare_grams = 0
    if isinstance(tare_grams, bool) or not isinstance(tare_grams, int):
        raise ApiError("ERR_INVALID_REQUEST", "invalid tare_grams")
    is_taxable = b.get("is_taxable", False)
    is_prepared_food = b.get("is_prepared_food", False)
    if not isinstance(is_taxable, bool) or not isinstance(is_prepared_food, bool):
        raise ApiError("ERR_INVALID_REQUEST", "invalid flag")
    product = new_entity(store.products, {
        "vendor_id": vendor_id,
        "sku": sku,
        "name": name,
        "department": department,
        "unit_type": unit_type,
        "base_price_cents": base_price_cents,
        "tare_grams": tare_grams,
        "is_taxable": is_taxable,
        "is_prepared_food": is_prepared_food,
        "reorder_point": reorder_point,
        "reorder_qty": reorder_qty,
        "status": "ACTIVE",
        "qty_on_hand_total": 0,
        "needs_reorder": 0 <= reorder_point,
        "inventory_value_cents": 0,
        "last_shrink_cost_cents": 0,
    })
    return ok(serialize(product), 201)


@app.route("/coop/products", methods=["GET"])
def list_products():
    auth()
    items = list(store.products.values())
    vendor_id = request.args.get("vendor_id")
    if vendor_id is not None:
        items = [p for p in items if p["vendor_id"] == vendor_id]
    items = by_seq(items)
    page, pag = paginate(items)
    return ok(serialize_list(page), is_array=True, pagination=pag)


@app.route("/coop/products/<pid>", methods=["GET"])
def get_product(pid):
    auth()
    product = find(store.products, pid, "ERR_PRODUCT_NOT_FOUND")
    return ok(serialize(product))


@app.route("/coop/products/<pid>", methods=["PATCH"])
def update_product(pid):
    _, role = auth()
    require_role(role, {"InventoryManager"})
    product = find(store.products, pid, "ERR_PRODUCT_NOT_FOUND")
    b = get_body()
    changed = False
    reorder_changed = False
    if "base_price_cents" in b and b["base_price_cents"] is not None:
        val = b["base_price_cents"]
        if isinstance(val, bool) or not isinstance(val, int):
            raise ApiError("ERR_INVALID_REQUEST", "invalid base_price_cents")
        product["base_price_cents"] = val
        changed = True
    if "reorder_point" in b and b["reorder_point"] is not None:
        val = b["reorder_point"]
        if isinstance(val, bool) or not isinstance(val, int):
            raise ApiError("ERR_INVALID_REQUEST", "invalid reorder_point")
        product["reorder_point"] = val
        changed = True
        reorder_changed = True
    if "reorder_qty" in b and b["reorder_qty"] is not None:
        val = b["reorder_qty"]
        if isinstance(val, bool) or not isinstance(val, int):
            raise ApiError("ERR_INVALID_REQUEST", "invalid reorder_qty")
        product["reorder_qty"] = val
        changed = True
    if "status" in b and b["status"] is not None:
        val = b["status"]
        if val not in ("ACTIVE", "RECALLED", "DISCONTINUED"):
            raise ApiError("ERR_INVALID_REQUEST", "invalid status")
        product["status"] = val
        changed = True
    if reorder_changed:
        product["needs_reorder"] = product["qty_on_hand_total"] <= product["reorder_point"]
    if changed:
        touch(product)
    return ok(serialize(product))


@app.route("/coop/products/<pid>/shrink", methods=["POST"])
def shrink_product(pid):
    _, role = auth()
    require_role(role, {"InventoryManager"})
    product = find(store.products, pid, "ERR_PRODUCT_NOT_FOUND")
    b = get_body()
    quantity = require_int(b, "quantity")
    if quantity < 0:
        raise ApiError("ERR_INVALID_REQUEST", "quantity must be >= 0")
    posted = by_seq([l for l in store.lots.values()
                     if l["product_id"] == pid and l["status"] == "POSTED"])
    remaining = quantity
    cost = 0
    for lot in posted:
        if remaining <= 0:
            break
        take = min(remaining, lot["qty_on_hand"])
        if take <= 0:
            continue
        cost += take * lot["unit_cost_cents"]
        lot["qty_on_hand"] -= take
        lot["qty_shrunk"] += take
        touch(lot)
        remaining -= take
    product["last_shrink_cost_cents"] = cost
    recompute_product(product)
    return ok(serialize(product))


# ===========================================================================
# InventoryLot
# ===========================================================================
@app.route("/coop/inventory-lots", methods=["POST"])
def create_inventory_lot():
    _, role = auth()
    require_role(role, {"InventoryManager"})
    b = get_body()
    product_id = require_str(b, "product_id")
    find(store.products, product_id, "ERR_PRODUCT_NOT_FOUND")
    vendor_id = require_str(b, "vendor_id")
    find(store.vendors, vendor_id, "ERR_VENDOR_NOT_FOUND")
    received_qty = require_int(b, "received_qty")
    unit_cost_cents = require_int(b, "unit_cost_cents")
    expiry_date = b.get("expiry_date")
    if expiry_date is not None:
        parse_iso(expiry_date)  # validate format
    lot = new_entity(store.lots, {
        "product_id": product_id,
        "vendor_id": vendor_id,
        "received_qty": received_qty,
        "unit_cost_cents": unit_cost_cents,
        "expiry_date": expiry_date,
        "status": "DRAFT",
        "qty_on_hand": 0,
        "qty_sold": 0,
        "qty_shrunk": 0,
    })
    return ok(serialize(lot), 201)


@app.route("/coop/inventory-lots", methods=["GET"])
def list_inventory_lots():
    auth()
    items = list(store.lots.values())
    product_id = request.args.get("product_id")
    vendor_id = request.args.get("vendor_id")
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    if vendor_id is not None:
        items = [l for l in items if l["vendor_id"] == vendor_id]
    items = by_seq(items)
    page, pag = paginate(items)
    return ok(serialize_list(page), is_array=True, pagination=pag)


@app.route("/coop/inventory-lots/<lid>", methods=["GET"])
def get_inventory_lot(lid):
    auth()
    lot = find(store.lots, lid, "ERR_LOT_NOT_FOUND")
    return ok(serialize(lot))


@app.route("/coop/inventory-lots/<lid>/post", methods=["POST"])
def post_inventory_lot(lid):
    _, role = auth()
    require_role(role, {"InventoryManager"})
    lot = find(store.lots, lid, "ERR_LOT_NOT_FOUND")
    if lot["status"] != "DRAFT":
        raise ApiError("ERR_LOT_NOT_DRAFT")
    vendor = store.vendors.get(lot["vendor_id"])
    if vendor is None or vendor["status"] != "APPROVED":
        raise ApiError("ERR_VENDOR_NOT_APPROVED")
    lot["status"] = "POSTED"
    lot["qty_on_hand"] = lot["received_qty"]
    lot["qty_sold"] = 0
    lot["qty_shrunk"] = 0
    touch(lot)
    product = store.products.get(lot["product_id"])
    if product is not None:
        recompute_product(product)
    return ok(serialize(lot))


# ===========================================================================
# Register
# ===========================================================================
@app.route("/coop/registers", methods=["POST"])
def create_register():
    _, role = auth()
    require_role(role, {"Cashier"})
    b = get_body()
    name = require_str(b, "name")
    register = new_entity(store.registers, {"name": name, "status": "CLOSED"})
    return ok(serialize(register), 201)


@app.route("/coop/registers/<rid>", methods=["GET"])
def get_register(rid):
    auth()
    register = find(store.registers, rid, "ERR_REGISTER_NOT_FOUND")
    return ok(serialize(register))


@app.route("/coop/registers/<rid>/set-open", methods=["POST"])
def set_register_open(rid):
    _, role = auth()
    require_role(role, {"Cashier"})
    register = find(store.registers, rid, "ERR_REGISTER_NOT_FOUND")
    b = get_body()
    is_open = require_field(b, "is_open")
    if not isinstance(is_open, bool):
        raise ApiError("ERR_INVALID_REQUEST", "is_open must be boolean")
    register["status"] = "OPEN" if is_open else "CLOSED"
    touch(register)
    return ok(serialize(register))


# ===========================================================================
# Sale
# ===========================================================================
def recompute_sale_totals(sale):
    sale["subtotal_cents"] = sum(l["line_subtotal_cents"] for l in sale["lines"])
    sale["tax_total_cents"] = sum(l["line_tax_cents"] for l in sale["lines"])
    sale["total_cents"] = sale["subtotal_cents"] + sale["tax_total_cents"]
    sale["patronage_eligible_cents"] = sum(
        l["line_subtotal_cents"] for l in sale["lines"] if l["is_patronage_eligible"])


@app.route("/coop/sales", methods=["POST"])
def create_sale():
    _, role = auth()
    require_role(role, {"Cashier"})
    b = get_body()
    register_id = require_str(b, "register_id")
    find(store.registers, register_id, "ERR_REGISTER_NOT_FOUND")
    member_id = b.get("member_id")
    if member_id is not None:
        find(store.members, member_id, "ERR_MEMBER_NOT_FOUND")
    sale = new_entity(store.sales, {
        "register_id": register_id,
        "member_id": member_id,
        "checkout_status": "BUILDING",
        "payment_status": "UNPAID",
        "lines": [],
        "subtotal_cents": 0,
        "tax_total_cents": 0,
        "total_cents": 0,
        "patronage_eligible_cents": 0,
    })
    return ok(serialize(sale), 201)


@app.route("/coop/sales", methods=["GET"])
def list_sales():
    auth()
    items = list(store.sales.values())
    member_id = request.args.get("member_id")
    register_id = request.args.get("register_id")
    if member_id is not None:
        items = [s for s in items if s["member_id"] == member_id]
    if register_id is not None:
        items = [s for s in items if s["register_id"] == register_id]
    items = by_seq(items)
    page, pag = paginate(items)
    return ok(serialize_list(page), is_array=True, pagination=pag)


@app.route("/coop/sales/<sid>", methods=["GET"])
def get_sale(sid):
    auth()
    sale = find(store.sales, sid, "ERR_SALE_NOT_FOUND")
    return ok(serialize(sale))


def resolve_promotion(product, member):
    """Return the winning active promotion for this product, or None."""
    clock = store.clock
    candidates = []
    for promo in store.promotions.values():
        if promo["product_id"] != product["id"]:
            continue
        start = parse_iso(promo["start_date"])
        end = parse_iso(promo["end_date"])
        if not (clock >= start and clock < end):
            continue
        if promo["member_only"]:
            if member is None or member["membership_status"] != "ACTIVE":
                continue
        candidates.append(promo)
    if not candidates:
        return None
    # lowest promo_price_cents; tie-break earliest start_date then earliest created_at (_seq)
    candidates.sort(key=lambda p: (p["promo_price_cents"], parse_iso(p["start_date"]), p["_seq"]))
    return candidates[0]


@app.route("/coop/sales/<sid>/lines", methods=["POST"])
def add_sale_line(sid):
    _, role = auth()
    require_role(role, {"Cashier"})
    sale = find(store.sales, sid, "ERR_SALE_NOT_FOUND")
    b = get_body()
    product_id = require_str(b, "product_id")
    product = find(store.products, product_id, "ERR_PRODUCT_NOT_FOUND")
    lot_id = require_str(b, "inventory_lot_id")
    lot = find(store.lots, lot_id, "ERR_LOT_NOT_FOUND")

    # state: sale must be BUILDING
    if sale["checkout_status"] != "BUILDING":
        raise ApiError("ERR_SALE_NOT_BUILDING")

    # unit input coherence (400) depends on resolved product's unit_type
    quantity = b.get("quantity")
    gross = b.get("gross_weight_grams")
    if product["unit_type"] == "EACH":
        if quantity is None:
            raise ApiError("ERR_LINE_UNIT_INPUT_INVALID")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ApiError("ERR_LINE_UNIT_INPUT_INVALID")
    else:  # WEIGHT
        if gross is None:
            raise ApiError("ERR_LINE_UNIT_INPUT_INVALID")
        if isinstance(gross, bool) or not isinstance(gross, (int, float)) or gross <= 0:
            raise ApiError("ERR_LINE_UNIT_INPUT_INVALID")

    # business-safety (prio 5): recalled product
    if product["status"] == "RECALLED":
        raise ApiError("ERR_PRODUCT_RECALLED")

    # business-referential (prio 7): lot must belong to product
    if lot["product_id"] != product_id:
        raise ApiError("ERR_LOT_PRODUCT_MISMATCH")

    member = store.members.get(sale["member_id"]) if sale["member_id"] else None

    # --- pricing ---
    promo = resolve_promotion(product, member)
    if promo is None:
        unit_price = product["base_price_cents"]
        applied_member_only = False
    else:
        unit_price = promo["promo_price_cents"]
        applied_member_only = promo["member_only"]

    if (member is not None and member["is_working_member"] and not applied_member_only):
        unit_price = rhu(Decimal(unit_price) * (Decimal("1") - WORKING_MEMBER_DISCOUNT_PCT))

    if product["unit_type"] == "EACH":
        units = quantity
        units_dec = Decimal(quantity)
        net_weight_grams = None
        line_quantity = quantity
        line_gross = None
    else:
        net_weight_grams = gross - product["tare_grams"]
        units_dec = Decimal(str(net_weight_grams)) / Decimal("1000")
        units = float(units_dec)
        line_quantity = None
        line_gross = gross

    line_subtotal = rhu(Decimal(unit_price) * units_dec)
    if product["is_taxable"]:
        line_tax = rhu(Decimal(line_subtotal) * TAX_RATE)
    else:
        line_tax = 0
    line_total = line_subtotal + line_tax
    is_patronage_eligible = not product["is_prepared_food"]

    line = {
        "product_id": product_id,
        "inventory_lot_id": lot_id,
        "quantity": line_quantity,
        "gross_weight_grams": line_gross,
        "net_weight_grams": net_weight_grams,
        "units": units,
        "unit_price_cents": unit_price,
        "line_subtotal_cents": line_subtotal,
        "line_tax_cents": line_tax,
        "line_total_cents": line_total,
        "is_patronage_eligible": is_patronage_eligible,
        "applied_member_only": applied_member_only,
    }
    sale["lines"].append(line)
    recompute_sale_totals(sale)
    touch(sale)
    return ok(serialize(sale))


@app.route("/coop/sales/<sid>/finalize", methods=["POST"])
def finalize_sale(sid):
    _, role = auth()
    require_role(role, {"Cashier"})
    sale = find(store.sales, sid, "ERR_SALE_NOT_FOUND")
    # state (prio 4)
    if sale["checkout_status"] != "BUILDING":
        raise ApiError("ERR_SALE_NOT_BUILDING")
    register = store.registers.get(sale["register_id"])
    if register is None or register["status"] != "OPEN":
        raise ApiError("ERR_REGISTER_CLOSED")
    # business-safety (prio 5): recalled
    for line in sale["lines"]:
        prod = store.products.get(line["product_id"])
        if prod is not None and prod["status"] == "RECALLED":
            raise ApiError("ERR_PRODUCT_RECALLED")
    # fiscal (prio 9): sufficient inventory (cumulative per lot)
    needed = {}
    for line in sale["lines"]:
        needed[line["inventory_lot_id"]] = needed.get(line["inventory_lot_id"], 0) + line["units"]
    for lot_id, need in needed.items():
        lot = store.lots.get(lot_id)
        if lot is None or lot["qty_on_hand"] < need:
            raise ApiError("ERR_INSUFFICIENT_INVENTORY")

    # commit
    affected_products = set()
    for line in sale["lines"]:
        lot = store.lots[line["inventory_lot_id"]]
        lot["qty_sold"] += line["units"]
        lot["qty_on_hand"] -= line["units"]
        touch(lot)
        affected_products.add(lot["product_id"])
    for pid in affected_products:
        prod = store.products.get(pid)
        if prod is not None:
            recompute_product(prod)
    sale["checkout_status"] = "FINALIZED"
    touch(sale)
    member = store.members.get(sale["member_id"]) if sale["member_id"] else None
    if member is not None and member["membership_status"] == "ACTIVE":
        member["patronage_cents_ytd"] += sale["patronage_eligible_cents"]
        touch(member)
        fy = open_fiscal_year()
        if fy is not None:
            fy["total_patronage_cents"] += sale["patronage_eligible_cents"]
            touch(fy)
    return ok(serialize(sale))


@app.route("/coop/sales/<sid>/pay", methods=["POST"])
def pay_sale(sid):
    _, role = auth()
    require_role(role, {"Cashier"})
    sale = find(store.sales, sid, "ERR_SALE_NOT_FOUND")
    if sale["payment_status"] != "UNPAID":
        raise ApiError("ERR_PAYMENT_NOT_UNPAID")
    sale["payment_status"] = "PAID"
    touch(sale)
    return ok(serialize(sale))


@app.route("/coop/sales/<sid>/refund", methods=["POST"])
def refund_sale(sid):
    _, role = auth()
    require_role(role, {"Cashier"})
    sale = find(store.sales, sid, "ERR_SALE_NOT_FOUND")
    if sale["payment_status"] != "PAID":
        raise ApiError("ERR_PAYMENT_NOT_PAID")
    if sale["checkout_status"] != "FINALIZED":
        raise ApiError("ERR_SALE_NOT_FINALIZED")
    affected_products = set()
    for line in sale["lines"]:
        lot = store.lots.get(line["inventory_lot_id"])
        if lot is None:
            continue
        lot["qty_sold"] -= line["units"]
        lot["qty_on_hand"] += line["units"]
        touch(lot)
        affected_products.add(lot["product_id"])
    for pid in affected_products:
        prod = store.products.get(pid)
        if prod is not None:
            recompute_product(prod)
    sale["payment_status"] = "REFUNDED"
    touch(sale)
    member = store.members.get(sale["member_id"]) if sale["member_id"] else None
    if member is not None and member["membership_status"] == "ACTIVE":
        member["patronage_cents_ytd"] -= sale["patronage_eligible_cents"]
        touch(member)
        fy = open_fiscal_year()
        if fy is not None:
            fy["total_patronage_cents"] -= sale["patronage_eligible_cents"]
            touch(fy)
    return ok(serialize(sale))


# ===========================================================================
# Promotion
# ===========================================================================
@app.route("/coop/promotions", methods=["POST"])
def create_promotion():
    _, role = auth()
    require_role(role, {"InventoryManager"})
    b = get_body()
    product_id = require_str(b, "product_id")
    find(store.products, product_id, "ERR_PRODUCT_NOT_FOUND")
    deal_type = require_field(b, "deal_type")
    if deal_type not in DEAL_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "invalid deal_type")
    promo_price_cents = require_int(b, "promo_price_cents")
    start_raw = require_field(b, "start_date")
    end_raw = require_field(b, "end_date")
    start = parse_iso(start_raw)
    end = parse_iso(end_raw)
    member_only = b.get("member_only", False)
    if not isinstance(member_only, bool):
        raise ApiError("ERR_INVALID_REQUEST", "member_only must be boolean")
    if deal_type == "MEMBER_DEAL":
        member_only = True
    # temporal overlap (prio 6), half-open [start, end)
    for other in store.promotions.values():
        if other["product_id"] != product_id:
            continue
        os_ = parse_iso(other["start_date"])
        oe = parse_iso(other["end_date"])
        if start < oe and os_ < end:
            raise ApiError("ERR_PROMO_WINDOW_OVERLAP")
    promo = new_entity(store.promotions, {
        "product_id": product_id,
        "deal_type": deal_type,
        "promo_price_cents": promo_price_cents,
        "member_only": member_only,
        "start_date": start_raw,
        "end_date": end_raw,
    })
    return ok(serialize(promo), 201)


@app.route("/coop/promotions", methods=["GET"])
def list_promotions():
    auth()
    items = list(store.promotions.values())
    product_id = request.args.get("product_id")
    if product_id is not None:
        items = [p for p in items if p["product_id"] == product_id]
    items = by_seq(items)
    page, pag = paginate(items)
    return ok(serialize_list(page), is_array=True, pagination=pag)


@app.route("/coop/promotions/<pid>", methods=["GET"])
def get_promotion(pid):
    auth()
    promo = find(store.promotions, pid, "ERR_PROMOTION_NOT_FOUND")
    return ok(serialize(promo))


# ===========================================================================
# WorkingMemberShift
# ===========================================================================
@app.route("/coop/working-shifts", methods=["POST"])
def create_working_shift():
    _, role = auth()
    require_role(role, {"Member", "CoopAdmin"})
    b = get_body()
    member_id = require_str(b, "member_id")
    find(store.members, member_id, "ERR_MEMBER_NOT_FOUND")
    department = require_field(b, "department")
    if department not in DEPARTMENTS:
        raise ApiError("ERR_INVALID_REQUEST", "invalid department")
    start_raw = require_field(b, "start_at")
    end_raw = require_field(b, "end_at")
    start = parse_iso(start_raw)
    end = parse_iso(end_raw)
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", "end_at must be after start_at")
    # rest-buffer overlap (prio 6): gap to any other shift of this member >= 60 min
    buffer = timedelta(minutes=REST_BUFFER_MINUTES)
    for other in store.shifts.values():
        if other["member_id"] != member_id:
            continue
        os_ = parse_iso(other["start_at"])
        oe = parse_iso(other["end_at"])
        if start >= oe:
            gap = start - oe
        elif os_ >= end:
            gap = os_ - end
        else:
            raise ApiError("ERR_SHIFT_OVERLAP")  # true overlap
        if gap < buffer:
            raise ApiError("ERR_SHIFT_OVERLAP")
    hours = rhu2(Decimal(str((end - start).total_seconds())) / Decimal("3600"))
    shift = new_entity(store.shifts, {
        "member_id": member_id,
        "department": department,
        "start_at": start_raw,
        "end_at": end_raw,
        "hours": hours,
        "status": "SCHEDULED",
    })
    return ok(serialize(shift), 201)


@app.route("/coop/working-shifts", methods=["GET"])
def list_working_shifts():
    auth()
    items = list(store.shifts.values())
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [s for s in items if s["member_id"] == member_id]
    items = by_seq(items)
    page, pag = paginate(items)
    return ok(serialize_list(page), is_array=True, pagination=pag)


@app.route("/coop/working-shifts/<sid>", methods=["GET"])
def get_working_shift(sid):
    auth()
    shift = find(store.shifts, sid, "ERR_SHIFT_NOT_FOUND")
    return ok(serialize(shift))


@app.route("/coop/working-shifts/<sid>/complete", methods=["POST"])
def complete_working_shift(sid):
    _, role = auth()
    require_role(role, {"InventoryManager", "CoopAdmin"})
    shift = find(store.shifts, sid, "ERR_SHIFT_NOT_FOUND")
    if shift["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_REQUEST", "shift not SCHEDULED")
    shift["status"] = "COMPLETED"
    touch(shift)
    member = store.members.get(shift["member_id"])
    if member is not None:
        recompute_working_hours(member)
        touch(member)
    return ok(serialize(shift))


# ===========================================================================
# BoardProposal
# ===========================================================================
@app.route("/coop/board-proposals", methods=["POST"])
def create_board_proposal():
    _, role = auth()
    require_role(role, {"BoardAdmin"})
    b = get_body()
    title = require_str(b, "title")
    proposal_type = require_field(b, "proposal_type")
    if proposal_type not in PROPOSAL_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "invalid proposal_type")
    proposal = new_entity(store.proposals, {
        "title": title,
        "proposal_type": proposal_type,
        "status": "DRAFT",
        "eligible_board_member_count": 0,
        "voter_member_ids": [],
        "for_count": 0,
        "against_count": 0,
        "abstain_count": 0,
        "quorum_met": False,
        "outcome": "PENDING",
    })
    return ok(serialize(proposal), 201)


@app.route("/coop/board-proposals/<pid>", methods=["GET"])
def get_board_proposal(pid):
    auth()
    proposal = find(store.proposals, pid, "ERR_PROPOSAL_NOT_FOUND")
    return ok(serialize(proposal))


@app.route("/coop/board-proposals/<pid>/advance", methods=["POST"])
def advance_board_proposal(pid):
    _, role = auth()
    require_role(role, {"BoardAdmin"})
    proposal = find(store.proposals, pid, "ERR_PROPOSAL_NOT_FOUND")
    b = get_body()
    action = require_field(b, "action")
    if action not in ADVANCE_ACTIONS:
        raise ApiError("ERR_INVALID_REQUEST", "invalid action")
    status = proposal["status"]
    if action == "SUBMIT":
        if status != "DRAFT":
            raise ApiError("ERR_PROPOSAL_INVALID_ACTION")
        proposal["status"] = "UNDER_REVIEW"
    elif action == "REQUEST_REVISIONS":
        if status != "UNDER_REVIEW":
            raise ApiError("ERR_PROPOSAL_INVALID_ACTION")
        proposal["status"] = "DRAFT"
    elif action == "OPEN_VOTING":
        if status != "UNDER_REVIEW":
            raise ApiError("ERR_PROPOSAL_INVALID_ACTION")
        proposal["status"] = "VOTING"
        proposal["eligible_board_member_count"] = sum(
            1 for m in store.members.values()
            if m["is_board_member"] and m["membership_status"] == "ACTIVE")
        recompute_quorum(proposal)
    elif action == "WITHDRAW":
        if status not in ("DRAFT", "UNDER_REVIEW", "VOTING"):
            raise ApiError("ERR_PROPOSAL_INVALID_ACTION")
        proposal["status"] = "WITHDRAWN"
    touch(proposal)
    return ok(serialize(proposal))


@app.route("/coop/board-proposals/<pid>/votes", methods=["POST"])
def cast_board_vote(pid):
    uid, role = auth()
    require_role(role, {"Member"})
    b = get_body()
    member_id = require_str(b, "member_id")
    # ownership (prio 2): body member_id must equal caller's X-User-ID
    if member_id != uid:
        raise ApiError("ERR_UNAUTHORIZED")
    vote = require_field(b, "vote")
    if vote not in VOTE_CHOICES:
        raise ApiError("ERR_INVALID_REQUEST", "invalid vote")
    proposal = find(store.proposals, pid, "ERR_PROPOSAL_NOT_FOUND")
    member = find(store.members, member_id, "ERR_MEMBER_NOT_FOUND")
    # state (prio 4)
    if proposal["status"] != "VOTING":
        raise ApiError("ERR_PROPOSAL_NOT_VOTING")
    # referential (prio 7): eligible = ACTIVE board member
    if not (member["is_board_member"] and member["membership_status"] == "ACTIVE"):
        raise ApiError("ERR_NOT_ELIGIBLE_VOTER")
    # constraint (prio 8): one vote per proposal
    if member_id in proposal["voter_member_ids"]:
        raise ApiError("ERR_ALREADY_VOTED")
    if vote == "FOR":
        proposal["for_count"] += 1
    elif vote == "AGAINST":
        proposal["against_count"] += 1
    else:
        proposal["abstain_count"] += 1
    proposal["voter_member_ids"].append(member_id)
    recompute_quorum(proposal)
    touch(proposal)
    return ok(serialize(proposal))


@app.route("/coop/board-proposals/<pid>/tally", methods=["POST"])
def tally_board_proposal(pid):
    _, role = auth()
    require_role(role, {"BoardAdmin"})
    proposal = find(store.proposals, pid, "ERR_PROPOSAL_NOT_FOUND")
    if proposal["status"] != "VOTING":
        raise ApiError("ERR_PROPOSAL_NOT_VOTING")
    recompute_quorum(proposal)
    if not proposal["quorum_met"]:
        raise ApiError("ERR_QUORUM_NOT_MET")
    if proposal["for_count"] > proposal["against_count"]:
        proposal["status"] = "APPROVED"
        proposal["outcome"] = "APPROVED"
    else:
        proposal["status"] = "REJECTED"
        proposal["outcome"] = "REJECTED"
    touch(proposal)
    return ok(serialize(proposal))


# ===========================================================================
# PatronageAllocation
# ===========================================================================
@app.route("/coop/patronage-allocations", methods=["POST"])
def create_patronage_allocation():
    _, role = auth()
    require_role(role, {"FinanceManager"})
    b = get_body()
    fiscal_year_id = require_str(b, "fiscal_year_id")
    fy = find(store.fiscal_years, fiscal_year_id, "ERR_FISCAL_YEAR_NOT_FOUND")
    method = require_field(b, "method")
    if method not in ALLOC_METHODS:
        raise ApiError("ERR_INVALID_REQUEST", "invalid method")
    expected = require_int(b, "expected_fiscal_year_version")
    declared_rate = b.get("declared_rate")
    if declared_rate is not None and (isinstance(declared_rate, bool)
                                      or not isinstance(declared_rate, (int, float))):
        raise ApiError("ERR_INVALID_REQUEST", "invalid declared_rate")
    # OCC (prio 8): stale fiscal-year version guard
    if expected != fy["version"]:
        raise ApiError("ERR_STALE_FISCAL_YEAR_VERSION")
    # supersede any prior DRAFT allocation for this fiscal year
    for alloc in store.allocations.values():
        if alloc["fiscal_year_id"] == fiscal_year_id and alloc["status"] == "DRAFT":
            alloc["status"] = "SUPERSEDED"
            touch(alloc)
    allocation = new_entity(store.allocations, {
        "fiscal_year_id": fiscal_year_id,
        "method": method,
        "declared_rate": declared_rate,
        "status": "DRAFT",
        "total_dividend_cents": 0,
        "total_retained_cents": 0,
        "member_count": 0,
    })
    # create advances the fiscal year's version by one
    fy["version"] += 1
    fy["updated_at"] = now_iso()
    return ok(serialize(allocation), 201)


@app.route("/coop/patronage-allocations", methods=["GET"])
def list_patronage_allocations():
    auth()
    items = list(store.allocations.values())
    fiscal_year_id = request.args.get("fiscal_year_id")
    if fiscal_year_id is not None:
        items = [a for a in items if a["fiscal_year_id"] == fiscal_year_id]
    items = by_seq(items)
    page, pag = paginate(items)
    return ok(serialize_list(page), is_array=True, pagination=pag)


@app.route("/coop/patronage-allocations/<aid>", methods=["GET"])
def get_patronage_allocation(aid):
    auth()
    allocation = find(store.allocations, aid, "ERR_ALLOCATION_NOT_FOUND")
    return ok(serialize(allocation))


@app.route("/coop/patronage-allocations/<aid>/finalize", methods=["POST"])
def finalize_patronage_allocation(aid):
    _, role = auth()
    require_role(role, {"FinanceManager"})
    allocation = find(store.allocations, aid, "ERR_ALLOCATION_NOT_FOUND")
    if allocation["status"] != "DRAFT":
        raise ApiError("ERR_ALLOCATION_NOT_DRAFT")
    fy = store.fiscal_years.get(allocation["fiscal_year_id"])
    if fy is None:
        raise ApiError("ERR_FISCAL_YEAR_NOT_FOUND")
    method = allocation["method"]
    # state (prio 4): year status gate
    if method == "ESTIMATED" and fy["status"] != "OPEN":
        raise ApiError("ERR_FISCAL_YEAR_NOT_OPEN")
    if method == "FINAL" and fy["status"] != "CLOSED":
        raise ApiError("ERR_FISCAL_YEAR_NOT_CLOSED")
    # fiscal (prio 9): FINAL requires declared_rate
    if method == "FINAL" and allocation["declared_rate"] is None:
        raise ApiError("ERR_DECLARED_RATE_REQUIRED")

    rate = fy["patronage_rate"] if method == "ESTIMATED" else allocation["declared_rate"]
    rate_dec = Decimal(str(rate))
    eligible = [m for m in store.members.values()
                if m["membership_status"] == "ACTIVE"
                and m["patronage_cents_ytd"] >= MIN_PATRONAGE_CENTS]
    total_dividend = 0
    total_retained = 0
    count = 0
    fy_changed = False
    for member in eligible:
        dividend = rhu(rate_dec * Decimal(member["patronage_cents_ytd"]))
        member["patronage_dividend_cents"] = dividend
        retained = rhu(Decimal(dividend) * RETENTION_PCT)
        member["equity_paid_in_cents"] += retained
        touch(member)
        fy["total_equity_cents"] += retained
        fy_changed = True
        total_dividend += dividend
        total_retained += retained
        count += 1
    if fy_changed:
        touch(fy)
    allocation["status"] = "FINALIZED"
    allocation["total_dividend_cents"] = total_dividend
    allocation["total_retained_cents"] = total_retained
    allocation["member_count"] = count
    touch(allocation)
    return ok(serialize(allocation))


# ---------------------------------------------------------------------------
# Store instance (created after helpers so parse_iso is available)
# ---------------------------------------------------------------------------
store = Store()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
