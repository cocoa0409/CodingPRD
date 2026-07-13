import os
import random
import string
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import Flask, request, make_response

app = Flask(__name__)

# =============================================================================
# Constants
# =============================================================================
ROLES = {"CatalogAdmin", "AccountManager", "ProductionManager", "Customer"}
DECORATION_METHODS = {"SCREEN_PRINT", "EMBROIDERY", "LASER_ENGRAVE"}
STATION_TYPES = {"SCREEN_PRESS", "EMBROIDERY_MACHINE", "LASER"}
ORDER_TYPES = {"STANDARD", "SAMPLE", "REORDER"}

METHOD = {
    "SCREEN_PRINT":  {"setup_first_color_cents": 2500, "setup_addl_color_cents": 1500, "run_addl_per_unit_cents": 40, "max_colors": 6},
    "EMBROIDERY":    {"setup_first_color_cents": 4000, "setup_addl_color_cents": 0,    "run_addl_per_unit_cents": 0,  "max_colors": 12},
    "LASER_ENGRAVE": {"setup_first_color_cents": 3000, "setup_addl_color_cents": 0,    "run_addl_per_unit_cents": 0,  "max_colors": 1},
}

RUSH_THRESHOLD_DAYS = 10
ABSOLUTE_MIN_LEAD_DAYS = 3
RUSH_SURCHARGE_PCT = Decimal("0.20")
DEPOSIT_PCT = Decimal("0.50")
UNDERRUN_TOL = Decimal("0.05")
OVERRUN_TOL = Decimal("0.05")
SAMPLE_MAX_QTY = 12  # PRD references SAMPLE_MAX_QTY but supplies no value; chosen default.

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_ORDER_OWNER": 403,
    "ERR_SUPPLIER_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_PRICE_TIER_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_STATION_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ORDER_LINE_NOT_FOUND": 404,
    "ERR_ART_PROOF_NOT_FOUND": 404,
    "ERR_PURCHASE_ORDER_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_ORDER_NOT_DRAFT": 409,
    "ERR_ORDER_NOT_QUOTED": 409,
    "ERR_ORDER_NOT_CONFIRMED": 409,
    "ERR_ORDER_NOT_IN_PRODUCTION": 409,
    "ERR_ORDER_NOT_SHIPPED": 409,
    "ERR_ORDER_NOT_CANCELLABLE": 409,
    "ERR_LINE_INVALID_STATE": 409,
    "ERR_ART_INVALID_STATE": 409,
    "ERR_PO_INVALID_STATE": 409,
    "ERR_STALE_ORDER_LINE_VERSION": 412,
    "ERR_ART_NOT_APPROVED": 409,
    "ERR_PO_NOT_RECEIVED": 409,
    "ERR_PO_ALREADY_EXISTS": 409,
    "ERR_LINE_PRODUCT_MISMATCH": 422,
    "ERR_REORDER_SOURCE_NOT_DELIVERED": 409,
    "ERR_INSUFFICIENT_LEAD_TIME": 422,
    "ERR_STATION_DOUBLE_BOOKED": 409,
    "ERR_BELOW_MIN_QUANTITY": 422,
    "ERR_TIER_NOT_FOUND": 422,
    "ERR_MAX_COLORS_EXCEEDED": 422,
    "ERR_SAMPLE_QTY_EXCEEDED": 422,
    "ERR_NO_ORDER_LINES": 409,
    "ERR_PRODUCED_QTY_INVALID": 422,
    "ERR_SPOILAGE_OUT_OF_TOLERANCE": 422,
    "ERR_SUPPLIER_CAPACITY_EXCEEDED": 409,
    "ERR_DEPOSIT_REQUIRED": 402,
    "ERR_INSUFFICIENT_CREDIT": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id
        super().__init__(self.message)


# =============================================================================
# In-memory store
# =============================================================================
class Store:
    def __init__(self):
        self.suppliers = {}
        self.products = {}
        self.price_tiers = {}
        self.stations = {}
        self.customers = {}
        self.orders = {}
        self.order_lines = {}
        self.art_proofs = {}
        self.purchase_orders = {}
        self.shipments = {}
        self.seq = 0
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def dt_to_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(value):
    """Parse ISO 8601; returns aware datetime (UTC). Raises ValueError on failure."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(e):
    e["updated_at"] = now_iso()
    e["version"] = e.get("version", 0) + 1


# =============================================================================
# Response envelope
# =============================================================================
def meta_base(pagination=None):
    m = {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def ok(data, status=200, pagination=None, response_type=None):
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": meta_base(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = make_response(_json(body), status)
    resp.headers["Content-Type"] = "application/json"
    return resp


def error_response(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = make_response(_json(body), err.http)
    resp.headers["Content-Type"] = "application/json"
    return resp


def _json(obj):
    import json
    return json.dumps(obj)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError("ERR_VALIDATION", "Not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError("ERR_VALIDATION", "Method not allowed"))


# =============================================================================
# Auth / body helpers
# =============================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return uid, role


def require(allowed_roles):
    uid, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return uid, role


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Body must be a JSON object")
    return data


def v_str(data, field, required=True, default=None):
    if field not in data or data[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", "Missing field: " + field)
        return default
    v = data[field]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", "Field must be a string: " + field)
    return v


def v_int(data, field, required=True, default=None, min_value=None):
    if field not in data or data[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", "Missing field: " + field)
        return default
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "Field must be an integer: " + field)
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", "Field below minimum: " + field)
    return v


def v_enum(data, field, allowed, required=True, default=None):
    if field not in data or data[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", "Missing field: " + field)
        return default
    v = data[field]
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", "Invalid enum for: " + field)
    return v


# =============================================================================
# Existence helpers
# =============================================================================
def get_supplier(sid):
    e = db.suppliers.get(sid)
    if e is None:
        raise ApiError("ERR_SUPPLIER_NOT_FOUND")
    return e


def get_product(pid):
    e = db.products.get(pid)
    if e is None:
        raise ApiError("ERR_PRODUCT_NOT_FOUND")
    return e


def get_station(sid):
    e = db.stations.get(sid)
    if e is None:
        raise ApiError("ERR_STATION_NOT_FOUND")
    return e


def get_customer(cid):
    e = db.customers.get(cid)
    if e is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND")
    return e


def get_order(oid):
    e = db.orders.get(oid)
    if e is None:
        raise ApiError("ERR_ORDER_NOT_FOUND")
    return e


def get_line(lid):
    e = db.order_lines.get(lid)
    if e is None:
        raise ApiError("ERR_ORDER_LINE_NOT_FOUND")
    return e


def get_proof(pid):
    e = db.art_proofs.get(pid)
    if e is None:
        raise ApiError("ERR_ART_PROOF_NOT_FOUND")
    return e


def get_po(pid):
    e = db.purchase_orders.get(pid)
    if e is None:
        raise ApiError("ERR_PURCHASE_ORDER_NOT_FOUND")
    return e


def get_shipment(sid):
    e = db.shipments.get(sid)
    if e is None:
        raise ApiError("ERR_SHIPMENT_NOT_FOUND")
    return e


# =============================================================================
# Ownership helpers
# =============================================================================
def owner_of_order(order):
    return order["customer_id"]


def enforce_owner(role, uid, customer_id):
    if role == "Customer" and uid != customer_id:
        raise ApiError("ERR_NOT_ORDER_OWNER")


# =============================================================================
# Serialization
# =============================================================================
def serialize(entity, kind=None):
    out = {k: v for k, v in entity.items() if not k.startswith("_")}
    if kind == "customer":
        out["credit_balance_cents"] = customer_credit_balance(entity["id"])
    return out


def customer_credit_balance(customer_id):
    cust = db.customers[customer_id]
    escrowed = 0
    for o in db.orders.values():
        if o["customer_id"] == customer_id:
            escrowed += o.get("escrow_cents", 0)
    return cust["total_funded_cents"] - escrowed


# =============================================================================
# Pagination
# =============================================================================
def pagination_params():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit_v < 1:
            limit_v = 1
        if limit_v > 100:
            limit_v = 100
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset_v < 0:
            offset_v = 0
    return limit_v, offset_v


def paginate(items, kind=None):
    items = sorted(items, key=lambda e: e["_seq"])
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    pag = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    data = [serialize(e, kind) for e in page]
    return ok(data, 200, pagination=pag, response_type="array")


# =============================================================================
# Business calculations
# =============================================================================
def round_half_up_int(dec_value):
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def select_tier(product_id, method, quantity):
    candidates = [
        t for t in db.price_tiers.values()
        if t["product_id"] == product_id and t["decoration_method"] == method
        and t["min_quantity"] <= quantity
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda t: t["min_quantity"])


def compute_line_pricing(line, order):
    """Sets unit_price_cents, line_setup_cents, line_subtotal_cents on the line.
    Raises ApiError on tier not found."""
    method = line["decoration_method"]
    quantity = line["quantity"]
    colors = line["imprint_color_count"]
    tier = select_tier(line["product_id"], method, quantity)
    if tier is None:
        raise ApiError("ERR_TIER_NOT_FOUND")
    unit_price = tier["unit_price_cents"]
    extra_colors = colors - 1
    run_per_unit = extra_colors * METHOD[method]["run_addl_per_unit_cents"]
    per_unit = unit_price + run_per_unit
    goods = per_unit * quantity
    if order["order_type"] == "SAMPLE":
        setup = 0
    else:
        setup = METHOD[method]["setup_first_color_cents"] + extra_colors * METHOD[method]["setup_addl_color_cents"]
    line["unit_price_cents"] = unit_price
    line["line_setup_cents"] = setup
    line["line_subtotal_cents"] = goods + setup


def extra_color_run_per_unit(line):
    method = line["decoration_method"]
    extra_colors = line["imprint_color_count"] - 1
    return extra_colors * METHOD[method]["run_addl_per_unit_cents"]


def lead_days(order):
    ihd = parse_dt(order["in_hands_date"]).date()
    clock_date = db.clock.date()
    return (ihd - clock_date).days


def non_cancelled_lines(order_id):
    return [l for l in db.order_lines.values()
            if l["order_id"] == order_id and l["status"] != "CANCELLED"]


def has_approved_proof(line_id):
    for p in db.art_proofs.values():
        if p["order_line_id"] == line_id and p["status"] == "APPROVED":
            return True
    return False


def recompute_art_complete(order):
    lines = non_cancelled_lines(order["id"])
    new_val = len(lines) > 0 and all(has_approved_proof(l["id"]) for l in lines)
    changed = order.get("art_complete") != new_val
    order["art_complete"] = new_val
    return changed


def active_po_for_line(line_id):
    for po in db.purchase_orders.values():
        if po["order_line_id"] == line_id and po["status"] != "CANCELLED":
            return po
    return None


# =============================================================================
# Suppliers
# =============================================================================
@app.route("/suppliers", methods=["POST"])
def create_supplier():
    require(["CatalogAdmin"])
    data = body()
    name = v_str(data, "name")
    cost = v_int(data, "blank_unit_cost_cents", min_value=0)
    cap = v_int(data, "concurrent_capacity_units", min_value=0)
    ts = now_iso()
    e = {
        "id": new_id(), "name": name, "blank_unit_cost_cents": cost,
        "concurrent_capacity_units": cap, "reserved_blank_qty": 0,
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    db.suppliers[e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/suppliers/<supplier_id>", methods=["GET"])
def read_supplier(supplier_id):
    require(["CatalogAdmin", "AccountManager", "ProductionManager"])
    return ok(serialize(get_supplier(supplier_id)), 200)


# =============================================================================
# Products & PriceTiers
# =============================================================================
@app.route("/products", methods=["POST"])
def create_product():
    require(["CatalogAdmin"])
    data = body()
    supplier_id = v_str(data, "supplier_id")
    sku = v_str(data, "sku")
    name = v_str(data, "name")
    min_order_qty = v_int(data, "min_order_qty", min_value=0)
    get_supplier(supplier_id)
    ts = now_iso()
    e = {
        "id": new_id(), "supplier_id": supplier_id, "sku": sku, "name": name,
        "min_order_qty": min_order_qty,
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    db.products[e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/products/<product_id>", methods=["GET"])
def read_product(product_id):
    require(["CatalogAdmin", "AccountManager", "ProductionManager", "Customer"])
    return ok(serialize(get_product(product_id)), 200)


@app.route("/products", methods=["GET"])
def list_products():
    require(["CatalogAdmin", "AccountManager", "ProductionManager", "Customer"])
    supplier_id = request.args.get("supplier_id")
    items = list(db.products.values())
    if supplier_id is not None:
        items = [p for p in items if p["supplier_id"] == supplier_id]
    return paginate(items)


@app.route("/products/<product_id>/price-tiers", methods=["POST"])
def create_price_tier(product_id):
    require(["CatalogAdmin"])
    get_product(product_id)
    data = body()
    method = v_enum(data, "decoration_method", DECORATION_METHODS)
    min_quantity = v_int(data, "min_quantity", min_value=0)
    unit_price = v_int(data, "unit_price_cents", min_value=0)
    ts = now_iso()
    e = {
        "id": new_id(), "product_id": product_id, "decoration_method": method,
        "min_quantity": min_quantity, "unit_price_cents": unit_price,
        "created_at": ts, "_seq": next_seq(),
    }
    db.price_tiers[e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/products/<product_id>/price-tiers", methods=["GET"])
def list_price_tiers(product_id):
    require(["CatalogAdmin", "AccountManager", "ProductionManager", "Customer"])
    get_product(product_id)
    items = [t for t in db.price_tiers.values() if t["product_id"] == product_id]
    return paginate(items)


# =============================================================================
# Decoration stations
# =============================================================================
@app.route("/decoration-stations", methods=["POST"])
def create_station():
    require(["CatalogAdmin"])
    data = body()
    name = v_str(data, "name")
    station_type = v_enum(data, "station_type", STATION_TYPES)
    ts = now_iso()
    e = {
        "id": new_id(), "name": name, "station_type": station_type,
        "created_at": ts, "_seq": next_seq(),
    }
    db.stations[e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/decoration-stations/<station_id>", methods=["GET"])
def read_station(station_id):
    require(["CatalogAdmin", "AccountManager", "ProductionManager"])
    return ok(serialize(get_station(station_id)), 200)


# =============================================================================
# Customers
# =============================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    require(["CatalogAdmin"])
    data = body()
    name = v_str(data, "name")
    credit = v_int(data, "initial_credit_cents", min_value=0)
    ts = now_iso()
    e = {
        "id": new_id(), "name": name, "initial_credit_cents": credit,
        "total_funded_cents": credit,
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    db.customers[e["id"]] = e
    return ok(serialize(e, "customer"), 201)


@app.route("/customers/<customer_id>", methods=["GET"])
def read_customer(customer_id):
    uid, role = require(["CatalogAdmin", "AccountManager", "Customer"])
    cust = get_customer(customer_id)
    enforce_owner(role, uid, customer_id)
    return ok(serialize(cust, "customer"), 200)


# =============================================================================
# Orders
# =============================================================================
def serialize_order(order):
    return serialize(order)


@app.route("/orders", methods=["POST"])
def create_order():
    uid, role = require(["Customer", "AccountManager"])
    data = body()
    customer_id = v_str(data, "customer_id")
    order_type = v_enum(data, "order_type", ORDER_TYPES, required=False, default="STANDARD")
    reorder_source = v_str(data, "reorder_source_order_id", required=False, default=None)
    if "in_hands_date" not in data or data["in_hands_date"] is None:
        raise ApiError("ERR_VALIDATION", "Missing field: in_hands_date")
    in_hands_raw = data["in_hands_date"]
    if not isinstance(in_hands_raw, str):
        raise ApiError("ERR_VALIDATION", "in_hands_date must be a string")
    # existence
    get_customer(customer_id)
    # ownership
    enforce_owner(role, uid, customer_id)
    # time-window format (priority 9)
    try:
        parse_dt(in_hands_raw)
    except ValueError:
        raise ApiError("ERR_INVALID_TIME_WINDOW", "Unparseable in_hands_date")
    ts = now_iso()
    e = {
        "id": new_id(), "customer_id": customer_id, "order_type": order_type,
        "reorder_source_order_id": reorder_source, "in_hands_date": in_hands_raw,
        "is_rush": False, "fulfillment_status": "DRAFT", "payment_status": "UNPAID",
        "escrow_cents": 0, "deposit_required_cents": 0, "art_complete": False,
        "quoted_subtotal_cents": 0, "quoted_rush_cents": 0, "quoted_total_cents": 0,
        "final_subtotal_cents": None, "final_rush_cents": None, "final_total_cents": None,
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    db.orders[e["id"]] = e
    return ok(serialize_order(e), 201)


@app.route("/orders/<order_id>", methods=["GET"])
def read_order(order_id):
    uid, role = require(["Customer", "AccountManager", "ProductionManager", "CatalogAdmin"])
    order = get_order(order_id)
    enforce_owner(role, uid, owner_of_order(order))
    return ok(serialize_order(order), 200)


@app.route("/orders", methods=["GET"])
def list_orders():
    require(["Customer", "AccountManager", "ProductionManager", "CatalogAdmin"])
    customer_id = request.args.get("customer_id")
    reorder_source = request.args.get("reorder_source_order_id")
    items = list(db.orders.values())
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    if reorder_source is not None:
        items = [o for o in items if o.get("reorder_source_order_id") == reorder_source]
    return paginate(items)


@app.route("/orders/<order_id>/lines", methods=["POST"])
def add_line(order_id):
    uid, role = require(["Customer", "AccountManager"])
    order = get_order(order_id)
    enforce_owner(role, uid, owner_of_order(order))
    data = body()
    product_id = v_str(data, "product_id")
    method = v_enum(data, "decoration_method", DECORATION_METHODS)
    quantity = v_int(data, "quantity", min_value=1)
    colors = v_int(data, "imprint_color_count", required=False, default=1, min_value=1)
    product = get_product(product_id)
    # priority 7 business constraints
    if quantity < product["min_order_qty"]:
        raise ApiError("ERR_BELOW_MIN_QUANTITY")
    if select_tier(product_id, method, quantity) is None:
        raise ApiError("ERR_TIER_NOT_FOUND")
    if colors > METHOD[method]["max_colors"]:
        raise ApiError("ERR_MAX_COLORS_EXCEEDED")
    if order["order_type"] == "SAMPLE" and quantity > SAMPLE_MAX_QTY:
        raise ApiError("ERR_SAMPLE_QTY_EXCEEDED")
    ts = now_iso()
    line = {
        "id": new_id(), "order_id": order_id, "product_id": product_id,
        "station_id": None, "decoration_method": method, "quantity": quantity,
        "imprint_color_count": colors, "scheduled_start": None, "scheduled_end": None,
        "unit_price_cents": 0, "line_setup_cents": 0, "line_subtotal_cents": 0,
        "locked_unit_price_cents": None, "produced_qty": None, "spoiled_qty": None,
        "good_qty": None, "final_line_subtotal_cents": None, "status": "PENDING_ART",
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    compute_line_pricing(line, order)
    db.order_lines[line["id"]] = line
    recompute_art_complete(order)
    return ok(serialize(line), 201)


@app.route("/orders/<order_id>/quote", methods=["POST"])
def quote_order(order_id):
    require(["AccountManager"])
    order = get_order(order_id)
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT")
    lines = non_cancelled_lines(order_id)
    if len(lines) == 0:
        raise ApiError("ERR_NO_ORDER_LINES")
    order["is_rush"] = lead_days(order) < RUSH_THRESHOLD_DAYS
    subtotal = sum(l["line_subtotal_cents"] for l in lines)
    rush = round_half_up_int(Decimal(subtotal) * RUSH_SURCHARGE_PCT) if order["is_rush"] else 0
    total = subtotal + rush
    order["quoted_subtotal_cents"] = subtotal
    order["quoted_rush_cents"] = rush
    order["quoted_total_cents"] = total
    order["deposit_required_cents"] = int((Decimal(total) * DEPOSIT_PCT).quantize(Decimal("1"), rounding=ROUND_CEILING))
    order["fulfillment_status"] = "QUOTED"
    touch(order)
    return ok(serialize_order(order), 200)


@app.route("/orders/<order_id>/confirm", methods=["POST"])
def confirm_order(order_id):
    require(["AccountManager"])
    order = get_order(order_id)
    if order["fulfillment_status"] != "QUOTED":
        raise ApiError("ERR_ORDER_NOT_QUOTED")
    recompute_art_complete(order)
    if not order["art_complete"]:
        raise ApiError("ERR_ART_NOT_APPROVED")
    if lead_days(order) < ABSOLUTE_MIN_LEAD_DAYS:
        raise ApiError("ERR_INSUFFICIENT_LEAD_TIME")
    if order["escrow_cents"] < order["deposit_required_cents"]:
        raise ApiError("ERR_DEPOSIT_REQUIRED")
    order["fulfillment_status"] = "CONFIRMED"
    for line in non_cancelled_lines(order_id):
        line["status"] = "CONFIRMED"
        line["locked_unit_price_cents"] = line["unit_price_cents"]
        touch(line)
    touch(order)
    return ok(serialize_order(order), 200)


@app.route("/orders/<order_id>/start-production", methods=["POST"])
def start_production(order_id):
    require(["ProductionManager"])
    order = get_order(order_id)
    if order["fulfillment_status"] != "CONFIRMED":
        raise ApiError("ERR_ORDER_NOT_CONFIRMED")
    for line in non_cancelled_lines(order_id):
        if line["status"] != "CONFIRMED":
            raise ApiError("ERR_LINE_INVALID_STATE")
    order["fulfillment_status"] = "IN_PRODUCTION"
    touch(order)
    return ok(serialize_order(order), 200)


@app.route("/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    require(["AccountManager"])
    order = get_order(order_id)
    if order["fulfillment_status"] not in ("DRAFT", "QUOTED", "CONFIRMED"):
        raise ApiError("ERR_ORDER_NOT_CANCELLABLE")
    # cascade
    for line in non_cancelled_lines(order_id):
        line["status"] = "CANCELLED"
        touch(line)
        po = active_po_for_line(line["id"])
        if po is not None and po["status"] == "ISSUED":
            po["status"] = "CANCELLED"
            touch(po)
            supplier = db.suppliers.get(po["supplier_id"])
            if supplier is not None:
                supplier["reserved_blank_qty"] -= po["ordered_blank_qty"]
                touch(supplier)
    # refund escrow
    order["escrow_cents"] = 0
    order["payment_status"] = "REFUNDED"
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return ok(serialize_order(order), 200)


@app.route("/orders/<order_id>/deliver", methods=["POST"])
def deliver_order(order_id):
    require(["ProductionManager"])
    order = get_order(order_id)
    if order["fulfillment_status"] != "SHIPPED":
        raise ApiError("ERR_ORDER_NOT_SHIPPED")
    order["fulfillment_status"] = "DELIVERED"
    touch(order)
    return ok(serialize_order(order), 200)


@app.route("/orders/<order_id>/payments", methods=["POST"])
def pay_order(order_id):
    uid, role = require(["Customer"])
    order = get_order(order_id)
    enforce_owner(role, uid, owner_of_order(order))
    data = body()
    amount = v_int(data, "amount_cents", min_value=1)
    if customer_credit_balance(order["customer_id"]) < amount:
        raise ApiError("ERR_INSUFFICIENT_CREDIT")
    order["escrow_cents"] += amount
    escrow = order["escrow_cents"]
    if escrow >= order["quoted_total_cents"]:
        order["payment_status"] = "PAID_IN_FULL"
    elif escrow >= order["deposit_required_cents"]:
        order["payment_status"] = "DEPOSIT_PAID"
    touch(order)
    return ok(serialize_order(order), 200)


@app.route("/orders/<source_order_id>/reorder", methods=["POST"])
def reorder(source_order_id):
    uid, role = require(["Customer", "AccountManager"])
    source = get_order(source_order_id)
    enforce_owner(role, uid, owner_of_order(source))
    data = body()
    if "in_hands_date" not in data or data["in_hands_date"] is None:
        raise ApiError("ERR_VALIDATION", "Missing field: in_hands_date")
    in_hands_raw = data["in_hands_date"]
    if not isinstance(in_hands_raw, str):
        raise ApiError("ERR_VALIDATION", "in_hands_date must be a string")
    if source["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_REORDER_SOURCE_NOT_DELIVERED")
    try:
        parse_dt(in_hands_raw)
    except ValueError:
        raise ApiError("ERR_INVALID_TIME_WINDOW", "Unparseable in_hands_date")
    ts = now_iso()
    new_order = {
        "id": new_id(), "customer_id": source["customer_id"], "order_type": "REORDER",
        "reorder_source_order_id": source_order_id, "in_hands_date": in_hands_raw,
        "is_rush": False, "fulfillment_status": "DRAFT", "payment_status": "UNPAID",
        "escrow_cents": 0, "deposit_required_cents": 0, "art_complete": False,
        "quoted_subtotal_cents": 0, "quoted_rush_cents": 0, "quoted_total_cents": 0,
        "final_subtotal_cents": None, "final_rush_cents": None, "final_total_cents": None,
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    db.orders[new_order["id"]] = new_order
    # copy source lines
    src_lines = sorted(
        [l for l in db.order_lines.values() if l["order_id"] == source_order_id and l["status"] != "CANCELLED"],
        key=lambda l: l["_seq"],
    )
    for sl in src_lines:
        lts = now_iso()
        line = {
            "id": new_id(), "order_id": new_order["id"], "product_id": sl["product_id"],
            "station_id": None, "decoration_method": sl["decoration_method"],
            "quantity": sl["quantity"], "imprint_color_count": sl["imprint_color_count"],
            "scheduled_start": None, "scheduled_end": None,
            "unit_price_cents": 0, "line_setup_cents": 0, "line_subtotal_cents": 0,
            "locked_unit_price_cents": None, "produced_qty": None, "spoiled_qty": None,
            "good_qty": None, "final_line_subtotal_cents": None, "status": "PENDING_ART",
            "created_at": lts, "updated_at": lts, "version": 1, "_seq": next_seq(),
        }
        compute_line_pricing(line, new_order)
        db.order_lines[line["id"]] = line
    recompute_art_complete(new_order)
    return ok(serialize_order(new_order), 201)


# =============================================================================
# Order lines
# =============================================================================
@app.route("/order-lines/<line_id>", methods=["GET"])
def read_line(line_id):
    uid, role = require(["Customer", "AccountManager", "ProductionManager", "CatalogAdmin"])
    line = get_line(line_id)
    order = db.orders[line["order_id"]]
    enforce_owner(role, uid, owner_of_order(order))
    return ok(serialize(line), 200)


@app.route("/order-lines", methods=["GET"])
def list_lines():
    require(["Customer", "AccountManager", "ProductionManager", "CatalogAdmin"])
    order_id = request.args.get("order_id")
    product_id = request.args.get("product_id")
    station_id = request.args.get("station_id")
    items = list(db.order_lines.values())
    if order_id is not None:
        items = [l for l in items if l["order_id"] == order_id]
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    if station_id is not None:
        items = [l for l in items if l.get("station_id") == station_id]
    return paginate(items)


@app.route("/order-lines/<line_id>/schedule", methods=["POST"])
def schedule_line(line_id):
    require(["ProductionManager"])
    line = get_line(line_id)
    order = db.orders[line["order_id"]]
    data = body()
    station_id = v_str(data, "station_id")
    start_raw = v_str(data, "scheduled_start")
    end_raw = v_str(data, "scheduled_end")
    get_station(station_id)
    # state (priority 4): line then order
    if line["status"] != "CONFIRMED":
        raise ApiError("ERR_LINE_INVALID_STATE")
    if order["fulfillment_status"] != "IN_PRODUCTION":
        raise ApiError("ERR_ORDER_NOT_IN_PRODUCTION")
    # referential (priority 5): active PO received
    po = active_po_for_line(line_id)
    if po is None or po["status"] != "RECEIVED":
        raise ApiError("ERR_PO_NOT_RECEIVED")
    # parse window
    try:
        start_dt = parse_dt(start_raw)
        end_dt = parse_dt(end_raw)
    except ValueError:
        raise ApiError("ERR_INVALID_TIME_WINDOW", "Unparseable schedule window")
    # temporal (priority 6): overlap
    for other in db.order_lines.values():
        if other["id"] == line_id:
            continue
        if other["status"] == "CANCELLED":
            continue
        if other.get("station_id") != station_id:
            continue
        if other.get("scheduled_start") is None or other.get("scheduled_end") is None:
            continue
        o_start = parse_dt(other["scheduled_start"])
        o_end = parse_dt(other["scheduled_end"])
        if start_dt < o_end and o_start < end_dt:
            raise ApiError("ERR_STATION_DOUBLE_BOOKED")
    # time-window format (priority 9)
    if end_dt <= start_dt:
        raise ApiError("ERR_INVALID_TIME_WINDOW")
    line["station_id"] = station_id
    line["scheduled_start"] = start_raw
    line["scheduled_end"] = end_raw
    line["status"] = "SCHEDULED"
    touch(line)
    return ok(serialize(line), 200)


@app.route("/order-lines/<line_id>/start-print", methods=["POST"])
def start_print(line_id):
    require(["ProductionManager"])
    line = get_line(line_id)
    if line["status"] != "SCHEDULED":
        raise ApiError("ERR_LINE_INVALID_STATE")
    line["status"] = "PRINTING"
    touch(line)
    return ok(serialize(line), 200)


@app.route("/order-lines/<line_id>/complete-run", methods=["POST"])
def complete_run(line_id):
    require(["ProductionManager"])
    line = get_line(line_id)
    data = body()
    produced = v_int(data, "produced_qty", min_value=0)
    spoiled = v_int(data, "spoiled_qty")
    if line["status"] != "PRINTING":
        raise ApiError("ERR_LINE_INVALID_STATE")
    if spoiled < 0 or spoiled > produced:
        raise ApiError("ERR_PRODUCED_QTY_INVALID")
    line["produced_qty"] = produced
    line["spoiled_qty"] = spoiled
    line["good_qty"] = produced - spoiled
    line["status"] = "QC_HOLD"
    touch(line)
    return ok(serialize(line), 200)


@app.route("/order-lines/<line_id>/qc", methods=["POST"])
def qc_line(line_id):
    require(["ProductionManager"])
    line = get_line(line_id)
    data = body()
    result = v_enum(data, "result", {"PASS", "REJECT"})
    if line["status"] != "QC_HOLD":
        raise ApiError("ERR_LINE_INVALID_STATE")
    order = db.orders[line["order_id"]]
    if result == "REJECT":
        line["produced_qty"] = None
        line["spoiled_qty"] = None
        line["good_qty"] = None
        line["status"] = "PRINTING"
        touch(line)
        return ok(serialize(line), 200)
    # PASS: spoilage tolerance band
    quantity = line["quantity"]
    if order["order_type"] == "SAMPLE":
        min_good = quantity
        max_good = quantity
    else:
        min_good = quantity - floor_pct(quantity, UNDERRUN_TOL)
        max_good = quantity + floor_pct(quantity, OVERRUN_TOL)
    good = line["good_qty"]
    if good < min_good or good > max_good:
        raise ApiError("ERR_SPOILAGE_OUT_OF_TOLERANCE")
    per_unit = line["locked_unit_price_cents"] + extra_color_run_per_unit(line)
    line["final_line_subtotal_cents"] = per_unit * good + line["line_setup_cents"]
    line["status"] = "COMPLETED"
    touch(line)
    return ok(serialize(line), 200)


def floor_pct(quantity, pct):
    import math
    return int(math.floor(quantity * float(pct)))


# =============================================================================
# Art proofs
# =============================================================================
@app.route("/order-lines/<line_id>/art-proofs", methods=["POST"])
def create_art_proof(line_id):
    require(["AccountManager"])
    line = get_line(line_id)
    data = body()
    proof_url = v_str(data, "proof_url")
    notes = v_str(data, "notes", required=False, default=None)
    expected_version = v_int(data, "expected_order_line_version")
    # OCC (priority 412)
    if expected_version != line["version"]:
        raise ApiError("ERR_STALE_ORDER_LINE_VERSION")
    order = db.orders[line["order_id"]]
    # supersede prior active proof
    existing = [p for p in db.art_proofs.values() if p["order_line_id"] == line_id]
    prior_active = [p for p in existing if p["status"] != "SUPERSEDED"]
    revision = len(existing) + 1
    reverted = False
    for p in prior_active:
        was_approved = p["status"] == "APPROVED"
        p["status"] = "SUPERSEDED"
        touch(p)
        if was_approved and line["status"] == "ART_READY":
            line["status"] = "PENDING_ART"
            reverted = True
    ts = now_iso()
    proof = {
        "id": new_id(), "order_line_id": line_id, "proof_url": proof_url,
        "notes": notes, "revision_number": revision, "approved_version": None,
        "status": "DRAFT",
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    db.art_proofs[proof["id"]] = proof
    # creating a proof increments the owning line's version by one
    touch(line)
    if reverted:
        if recompute_art_complete(order):
            touch(order)
    return ok(serialize(proof), 201)


@app.route("/order-lines/<line_id>/art-proofs", methods=["GET"])
def list_art_proofs(line_id):
    uid, role = require(["Customer", "AccountManager", "ProductionManager", "CatalogAdmin"])
    line = get_line(line_id)
    order = db.orders[line["order_id"]]
    enforce_owner(role, uid, owner_of_order(order))
    items = [p for p in db.art_proofs.values() if p["order_line_id"] == line_id]
    return paginate(items)


@app.route("/art-proofs/<proof_id>", methods=["GET"])
def read_art_proof(proof_id):
    uid, role = require(["Customer", "AccountManager", "ProductionManager", "CatalogAdmin"])
    proof = get_proof(proof_id)
    line = db.order_lines[proof["order_line_id"]]
    order = db.orders[line["order_id"]]
    enforce_owner(role, uid, owner_of_order(order))
    return ok(serialize(proof), 200)


@app.route("/art-proofs/<proof_id>/submit", methods=["POST"])
def submit_art_proof(proof_id):
    require(["AccountManager"])
    proof = get_proof(proof_id)
    if proof["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_ART_INVALID_STATE")
    proof["status"] = "PENDING_APPROVAL"
    touch(proof)
    return ok(serialize(proof), 200)


@app.route("/art-proofs/<proof_id>/approve", methods=["POST"])
def approve_art_proof(proof_id):
    uid, role = require(["Customer"])
    proof = get_proof(proof_id)
    line = db.order_lines[proof["order_line_id"]]
    order = db.orders[line["order_id"]]
    enforce_owner(role, uid, owner_of_order(order))
    if proof["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_ART_INVALID_STATE")
    proof["status"] = "APPROVED"
    proof["approved_version"] = line["version"]
    touch(proof)
    if line["status"] == "PENDING_ART":
        line["status"] = "ART_READY"
        touch(line)
    if recompute_art_complete(order):
        touch(order)
    return ok(serialize(proof), 200)


@app.route("/art-proofs/<proof_id>/request-changes", methods=["POST"])
def request_changes_art_proof(proof_id):
    uid, role = require(["Customer"])
    proof = get_proof(proof_id)
    line = db.order_lines[proof["order_line_id"]]
    order = db.orders[line["order_id"]]
    enforce_owner(role, uid, owner_of_order(order))
    if proof["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_ART_INVALID_STATE")
    data = body()
    notes = v_str(data, "notes", required=False, default=None)
    if notes is not None:
        proof["notes"] = notes
    proof["status"] = "CHANGES_REQUESTED"
    touch(proof)
    return ok(serialize(proof), 200)


# =============================================================================
# Purchase orders
# =============================================================================
@app.route("/purchase-orders", methods=["POST"])
def create_po():
    require(["AccountManager"])
    data = body()
    order_line_id = v_str(data, "order_line_id")
    supplier_id = v_str(data, "supplier_id")
    ordered_qty = v_int(data, "ordered_blank_qty", min_value=1)
    if "production_start" not in data or data["production_start"] is None:
        raise ApiError("ERR_VALIDATION", "Missing field: production_start")
    if "production_end" not in data or data["production_end"] is None:
        raise ApiError("ERR_VALIDATION", "Missing field: production_end")
    start_raw = data["production_start"]
    end_raw = data["production_end"]
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        raise ApiError("ERR_VALIDATION", "production window must be strings")
    # existence
    line = get_line(order_line_id)
    supplier = get_supplier(supplier_id)
    # referential (priority 5)
    if active_po_for_line(order_line_id) is not None:
        raise ApiError("ERR_PO_ALREADY_EXISTS")
    product = db.products[line["product_id"]]
    if product["supplier_id"] != supplier_id:
        raise ApiError("ERR_LINE_PRODUCT_MISMATCH")
    # time-window format (priority 9)
    try:
        start_dt = parse_dt(start_raw)
        end_dt = parse_dt(end_raw)
    except ValueError:
        raise ApiError("ERR_INVALID_TIME_WINDOW", "Unparseable production window")
    if end_dt <= start_dt:
        raise ApiError("ERR_INVALID_TIME_WINDOW")
    ts = now_iso()
    po = {
        "id": new_id(), "order_line_id": order_line_id, "order_id": line["order_id"],
        "product_id": line["product_id"], "supplier_id": supplier_id,
        "ordered_blank_qty": ordered_qty, "received_blank_qty": None,
        "production_start": start_raw, "production_end": end_raw,
        "estimated_blank_cost_cents": None, "actual_blank_cost_cents": None,
        "status": "DRAFT",
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    db.purchase_orders[po["id"]] = po
    return ok(serialize(po), 201)


@app.route("/purchase-orders/<po_id>", methods=["GET"])
def read_po(po_id):
    require(["AccountManager", "ProductionManager", "CatalogAdmin"])
    return ok(serialize(get_po(po_id)), 200)


@app.route("/purchase-orders", methods=["GET"])
def list_pos():
    require(["AccountManager", "ProductionManager", "CatalogAdmin"])
    order_line_id = request.args.get("order_line_id")
    order_id = request.args.get("order_id")
    product_id = request.args.get("product_id")
    supplier_id = request.args.get("supplier_id")
    items = list(db.purchase_orders.values())
    if order_line_id is not None:
        items = [p for p in items if p["order_line_id"] == order_line_id]
    if order_id is not None:
        items = [p for p in items if p["order_id"] == order_id]
    if product_id is not None:
        items = [p for p in items if p["product_id"] == product_id]
    if supplier_id is not None:
        items = [p for p in items if p["supplier_id"] == supplier_id]
    return paginate(items)


@app.route("/purchase-orders/<po_id>/issue", methods=["POST"])
def issue_po(po_id):
    require(["AccountManager"])
    po = get_po(po_id)
    if po["status"] != "DRAFT":
        raise ApiError("ERR_PO_INVALID_STATE")
    supplier = db.suppliers[po["supplier_id"]]
    # capacity check via interval stabbing
    new_start = parse_dt(po["production_start"])
    new_end = parse_dt(po["production_end"])
    issued = [p for p in db.purchase_orders.values()
              if p["supplier_id"] == supplier["id"] and p["status"] == "ISSUED"]
    candidate_points = [new_start]
    for p in issued:
        s = parse_dt(p["production_start"])
        if new_start <= s < new_end:
            candidate_points.append(s)
    peak = 0
    for t in candidate_points:
        load = po["ordered_blank_qty"]
        for p in issued:
            s = parse_dt(p["production_start"])
            e = parse_dt(p["production_end"])
            if s <= t < e:
                load += p["ordered_blank_qty"]
        if load > peak:
            peak = load
    if peak > supplier["concurrent_capacity_units"]:
        raise ApiError("ERR_SUPPLIER_CAPACITY_EXCEEDED")
    po["estimated_blank_cost_cents"] = po["ordered_blank_qty"] * supplier["blank_unit_cost_cents"]
    po["status"] = "ISSUED"
    touch(po)
    supplier["reserved_blank_qty"] += po["ordered_blank_qty"]
    touch(supplier)
    return ok(serialize(po), 200)


@app.route("/purchase-orders/<po_id>/receive", methods=["POST"])
def receive_po(po_id):
    require(["ProductionManager"])
    po = get_po(po_id)
    data = body()
    received = v_int(data, "received_blank_qty", min_value=0)
    if po["status"] != "ISSUED":
        raise ApiError("ERR_PO_INVALID_STATE")
    supplier = db.suppliers[po["supplier_id"]]
    po["received_blank_qty"] = received
    po["actual_blank_cost_cents"] = received * supplier["blank_unit_cost_cents"]
    po["status"] = "RECEIVED"
    touch(po)
    supplier["reserved_blank_qty"] -= po["ordered_blank_qty"]
    touch(supplier)
    return ok(serialize(po), 200)


@app.route("/purchase-orders/<po_id>/cancel", methods=["POST"])
def cancel_po(po_id):
    require(["AccountManager"])
    po = get_po(po_id)
    if po["status"] not in ("DRAFT", "ISSUED"):
        raise ApiError("ERR_PO_INVALID_STATE")
    was_issued = po["status"] == "ISSUED"
    po["status"] = "CANCELLED"
    touch(po)
    if was_issued:
        supplier = db.suppliers[po["supplier_id"]]
        supplier["reserved_blank_qty"] -= po["ordered_blank_qty"]
        touch(supplier)
    return ok(serialize(po), 200)


# =============================================================================
# Shipments
# =============================================================================
@app.route("/shipments", methods=["POST"])
def create_shipment():
    require(["ProductionManager"])
    data = body()
    order_id = v_str(data, "order_id")
    carrier = v_str(data, "carrier")
    tracking = v_str(data, "tracking_number", required=False, default=None)
    order = get_order(order_id)
    if order["fulfillment_status"] != "IN_PRODUCTION":
        raise ApiError("ERR_ORDER_NOT_IN_PRODUCTION")
    lines = non_cancelled_lines(order_id)
    for line in lines:
        if line["status"] != "COMPLETED":
            raise ApiError("ERR_LINE_INVALID_STATE")
    # final totals
    final_subtotal = sum(l["final_line_subtotal_cents"] for l in lines)
    final_rush = round_half_up_int(Decimal(final_subtotal) * RUSH_SURCHARGE_PCT) if order["is_rush"] else 0
    final_total = final_subtotal + final_rush
    order["final_subtotal_cents"] = final_subtotal
    order["final_rush_cents"] = final_rush
    order["final_total_cents"] = final_total
    order["fulfillment_status"] = "SHIPPED"
    touch(order)
    total_good = sum(l["good_qty"] for l in lines)
    ts = now_iso()
    shipment = {
        "id": new_id(), "order_id": order_id, "carrier": carrier,
        "tracking_number": tracking, "shipped_at": dt_to_iso(db.clock),
        "total_good_qty": total_good, "final_total_cents": final_total,
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    db.shipments[shipment["id"]] = shipment
    return ok(serialize(shipment), 201)


@app.route("/shipments/<shipment_id>", methods=["GET"])
def read_shipment(shipment_id):
    uid, role = require(["Customer", "AccountManager", "ProductionManager", "CatalogAdmin"])
    shipment = get_shipment(shipment_id)
    order = db.orders[shipment["order_id"]]
    enforce_owner(role, uid, owner_of_order(order))
    return ok(serialize(shipment), 200)


@app.route("/shipments", methods=["GET"])
def list_shipments():
    require(["Customer", "AccountManager", "ProductionManager", "CatalogAdmin"])
    order_id = request.args.get("order_id")
    items = list(db.shipments.values())
    if order_id is not None:
        items = [s for s in items if s["order_id"] == order_id]
    return paginate(items)


# =============================================================================
# Logical clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require(["CatalogAdmin", "AccountManager", "ProductionManager"])
    data = body()
    to_iso = v_str(data, "to_iso8601")
    try:
        db.clock = parse_dt(to_iso)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "Unparseable to_iso8601")
    return ok({}, 200, response_type="object")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
