"""
Pedorthic & Therapeutic Shoe Store API.

In-memory REST API (Flask). The store starts empty on every boot; the test
harness relaunches the process before every test, so no state carries over and
nothing is ever seeded here.
"""
import math
import os
import random
import string
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD §1.3 / PRD §3)
# ---------------------------------------------------------------------------
ROLES = {"StoreManager", "Fitter", "BillingSpecialist", "Customer"}
WIDTHS = {"AAA", "AA", "A", "B", "C", "D", "E", "2E", "4E", "6E"}
CATEGORIES = {"THERAPEUTIC", "DIABETIC", "ORTHOTIC", "REGULAR", "INSERT"}

PEDIATRIC_AGE_THRESHOLD_YEARS = 13
PEDIATRIC_TOE_ALLOWANCE_MM = 14
ADULT_TOE_ALLOWANCE_MM = 12
MONDO_STEP_MM = 5

MEDICARE_COINSURANCE_RATE = Decimal("0.20")
MEDICARE_ANNUAL_DEDUCTIBLE_CENTS = 25700
MEDICARE_ANNUAL_DIABETIC_SHOE_PAIR_LIMIT = 1
MEDICARE_ANNUAL_INSERT_LIMIT = 3

RETURN_WINDOW_DAYS = 30
RESTOCKING_FEE_RATE = Decimal("0.15")
FITTER_CLEANUP_BUFFER_MIN = 15
CERT_VISIT_WINDOW_MONTHS = 6

TIER_MULTIPLIER = {
    "BRONZE": Decimal("1.00"),
    "SILVER": Decimal("1.25"),
    "GOLD": Decimal("1.50"),
}

DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
db = {k: {} for k in [
    "products", "inventory_items", "customers", "measurements", "fitters",
    "gait_labs", "appointments", "sales", "sale_lines", "certifications",
    "claims", "returns", "special_orders", "recalls", "ledger",
]}
_state = {"clock": DEFAULT_CLOCK, "seq": 0}


def clock_now():
    return _state["clock"]


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def fail(error_id, status, message=None):
    raise ApiError(error_id, status, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO-8601 datetime/date string to an aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("bad datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # bare date
        dt = datetime.fromisoformat(s + "T00:00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    return parse_dt(value).date()


def subtract_months(d, months):
    m = d.month - 1 - months
    y = d.year + m // 12
    m = m % 12 + 1
    # clamp day
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(y, m, day)


def customer_age_years(cust, at=None):
    at = (at or clock_now()).date()
    dob = parse_date(cust["date_of_birth"])
    years = at.year - dob.year - ((at.month, at.day) < (dob.month, dob.day))
    return years


def rhu(dec):
    """round-half-up to nearest integer."""
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_entity(fields, immutable=False):
    now = clock_now()
    ent = dict(fields)
    ent["id"] = str(uuid.uuid4())
    ent["created_at"] = now
    ent["_seq"] = next_seq()
    if not immutable:
        ent["updated_at"] = now
        ent["version"] = 1
    return ent


def touch(ent):
    if ent is None:
        return
    if "version" in ent:
        ent["version"] += 1
        ent["updated_at"] = clock_now()


def base_common(ent):
    out = {
        "id": ent["id"],
        "created_at": fmt_ts(ent["created_at"]),
    }
    if "version" in ent:
        out["updated_at"] = fmt_ts(ent["updated_at"])
        out["version"] = ent["version"]
    return out


# ---------------------------------------------------------------------------
# Computed field helpers
# ---------------------------------------------------------------------------
def product_is_recalled(product):
    pid = product["id"]
    for r in db["recalls"].values():
        if r["status"] == "ISSUED" and r["product_id"] == pid and r["lot_number"] is None:
            return True
    return False


def item_available(item):
    return item["quantity_on_hand"] - item["quantity_reserved"]


def customer_ledger(cust_id):
    return [l for l in db["ledger"].values() if l["customer_id"] == cust_id]


def loyalty_balance(cust_id):
    return sum(l["points_delta"] for l in customer_ledger(cust_id))


def loyalty_tier_from_balance(bal):
    if bal < 500:
        return "BRONZE"
    if bal < 2000:
        return "SILVER"
    return "GOLD"


def customer_paid_claims_year(cust_id, year):
    return [c for c in db["claims"].values()
            if c["customer_id"] == cust_id and c["status"] == "PAID"
            and c["calendar_year"] == year]


def medicare_pairs_ytd(cust_id, year):
    return sum(1 for c in customer_paid_claims_year(cust_id, year)
               if c["hcpcs_code"] == "A5500")


def medicare_inserts_ytd(cust_id, year):
    return sum(1 for c in customer_paid_claims_year(cust_id, year)
               if c["hcpcs_code"] in ("A5512", "A5513"))


def medicare_deductible_remaining(cust_id, year):
    used = sum(c["deductible_applied_cents"] for c in customer_paid_claims_year(cust_id, year))
    return MEDICARE_ANNUAL_DEDUCTIBLE_CENTS - used


def sale_lines_of(sale_id):
    return sorted((l for l in db["sale_lines"].values() if l["sale_id"] == sale_id),
                  key=lambda l: (l["created_at"], l["_seq"]))


def sale_subtotal(sale_id):
    return sum(l["unit_price_cents"] * l["quantity"]
               for l in sale_lines_of(sale_id) if l["status"] == "ACTIVE")


def recommended_mondo(measurement, cust):
    pediatric = customer_age_years(cust) < PEDIATRIC_AGE_THRESHOLD_YEARS
    toe = PEDIATRIC_TOE_ALLOWANCE_MM if pediatric else ADULT_TOE_ALLOWANCE_MM
    max_len = max(measurement["foot_length_mm_left"], measurement["foot_length_mm_right"])
    fitting = max_len + toe
    return int(math.ceil(fitting / MONDO_STEP_MM)) * MONDO_STEP_MM


def size_to_mondo_mm(size):
    # US-size -> Mondopoint-mm mapping (see README note): Brannock foot-length
    # relation, foot_length_mm = (US_size + 22) / 3 * 25.4, rounded half up.
    return rhu((Decimal(str(size)) + Decimal("22")) / Decimal("3") * Decimal("25.4"))


def latest_measurement(cust_id):
    ms = sorted((m for m in db["measurements"].values() if m["customer_id"] == cust_id),
                key=lambda m: (m["created_at"], m["_seq"]))
    return ms[-1] if ms else None


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_product(p):
    d = base_common(p)
    d.update({
        "name": p["name"], "brand": p["brand"], "category": p["category"],
        "base_price_cents": p["base_price_cents"],
        "medicare_allowable_cents": p["medicare_allowable_cents"],
        "hcpcs_code": p["hcpcs_code"],
        "is_recalled": product_is_recalled(p),
    })
    return d


def ser_inventory(i):
    d = base_common(i)
    d.update({
        "product_id": i["product_id"], "size": i["size"], "width": i["width"],
        "lot_number": i["lot_number"], "quantity_on_hand": i["quantity_on_hand"],
        "quantity_reserved": i["quantity_reserved"],
        "quantity_available": item_available(i), "status": i["status"],
    })
    return d


def ser_customer(c):
    d = base_common(c)
    bal = loyalty_balance(c["id"])
    year = clock_now().year
    d.update({
        "full_name": c["full_name"], "date_of_birth": c["date_of_birth"],
        "medicare_beneficiary_id": c["medicare_beneficiary_id"],
        "is_pediatric": customer_age_years(c) < PEDIATRIC_AGE_THRESHOLD_YEARS,
        "loyalty_points_balance": bal,
        "loyalty_tier": loyalty_tier_from_balance(bal),
        "medicare_deductible_remaining_cents": medicare_deductible_remaining(c["id"], year),
        "medicare_pairs_claimed_ytd": medicare_pairs_ytd(c["id"], year),
        "medicare_inserts_claimed_ytd": medicare_inserts_ytd(c["id"], year),
    })
    return d


def ser_measurement(m):
    d = base_common(m)
    cust = db["customers"][m["customer_id"]]
    d.update({
        "customer_id": m["customer_id"], "measured_at": fmt_ts(m["measured_at"]),
        "foot_length_mm_left": m["foot_length_mm_left"],
        "foot_length_mm_right": m["foot_length_mm_right"],
        "foot_width_mm_left": m["foot_width_mm_left"],
        "foot_width_mm_right": m["foot_width_mm_right"],
        "recommended_mondo_mm": recommended_mondo(m, cust),
        "length_change_mm_from_prior": m["length_change_mm_from_prior"],
    })
    return d


def ser_fitter(f):
    d = base_common(f)
    d.update({"full_name": f["full_name"], "credential": f["credential"]})
    return d


def ser_gait_lab(g):
    d = base_common(g)
    d.update({"name": g["name"], "concurrent_capacity": g["concurrent_capacity"]})
    return d


def ser_appointment(a):
    d = base_common(a)
    d.update({
        "customer_id": a["customer_id"], "fitter_id": a["fitter_id"],
        "gait_lab_id": a["gait_lab_id"], "appointment_type": a["appointment_type"],
        "start_time": fmt_ts(a["start_time"]), "end_time": fmt_ts(a["end_time"]),
        "status": a["status"], "recommended_mondo_mm": a["recommended_mondo_mm"],
        "recommended_width": a["recommended_width"], "gait_findings": a["gait_findings"],
        "recommended_orthotic": a["recommended_orthotic"],
    })
    return d


def ser_sale(s):
    d = base_common(s)
    d.update({
        "customer_id": s["customer_id"], "fitter_id": s["fitter_id"],
        "appointment_id": s["appointment_id"], "payment_status": s["payment_status"],
        "fulfillment_status": s["fulfillment_status"],
        "subtotal_cents": sale_subtotal(s["id"]),
        "loyalty_tier_at_fulfill": s["loyalty_tier_at_fulfill"],
        "loyalty_points_earned": s["loyalty_points_earned"],
    })
    return d


def ser_sale_line(l):
    d = base_common(l)
    d.update({
        "sale_id": l["sale_id"], "inventory_item_id": l["inventory_item_id"],
        "quantity": l["quantity"], "unit_price_cents": l["unit_price_cents"],
        "line_total_cents": l["unit_price_cents"] * l["quantity"],
        "requires_medicare": l["requires_medicare"], "status": l["status"],
    })
    return d


def ser_certification(c):
    d = base_common(c)
    d.update({
        "customer_id": c["customer_id"],
        "certifying_physician_npi": c["certifying_physician_npi"],
        "prescribing_practitioner_npi": c["prescribing_practitioner_npi"],
        "statement_date": c["statement_date"],
        "in_person_visit_date": c["in_person_visit_date"],
        "status": c["status"],
    })
    return d


def ser_claim(c):
    d = base_common(c)
    d.update({
        "customer_id": c["customer_id"], "sale_id": c["sale_id"],
        "certification_id": c["certification_id"], "hcpcs_code": c["hcpcs_code"],
        "billed_amount_cents": c["billed_amount_cents"],
        "calendar_year": c["calendar_year"],
        "allowed_amount_cents": c["allowed_amount_cents"],
        "provisional_reimbursement_cents": c["provisional_reimbursement_cents"],
        "deductible_applied_cents": c["deductible_applied_cents"],
        "medicare_paid_cents": c["medicare_paid_cents"],
        "patient_responsibility_cents": c["patient_responsibility_cents"],
        "status": c["status"],
    })
    return d


def ser_return(r):
    d = base_common(r)
    d.update({
        "sale_id": r["sale_id"], "sale_line_id": r["sale_line_id"],
        "replacement_inventory_item_id": r["replacement_inventory_item_id"],
        "return_type": r["return_type"], "reason": r["reason"],
        "refund_amount_cents": r["refund_amount_cents"],
        "restocking_fee_cents": r["restocking_fee_cents"],
        "price_difference_cents": r["price_difference_cents"], "status": r["status"],
    })
    return d


def ser_special_order(o):
    d = base_common(o)
    d.update({
        "customer_id": o["customer_id"], "product_id": o["product_id"],
        "fulfilled_inventory_item_id": o["fulfilled_inventory_item_id"],
        "requested_size": o["requested_size"], "requested_width": o["requested_width"],
        "deposit_cents": o["deposit_cents"], "status": o["status"],
    })
    return d


def ser_recall(r):
    d = base_common(r)
    d.update({
        "product_id": r["product_id"], "lot_number": r["lot_number"],
        "reason": r["reason"], "status": r["status"],
    })
    return d


def ser_ledger(l):
    d = base_common(l)
    d.update({
        "customer_id": l["customer_id"], "sale_id": l["sale_id"],
        "points_delta": l["points_delta"], "reason": l["reason"],
    })
    return d


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, serialize):
    limit, offset = get_pagination()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta_extra = {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": offset + limit < total}
    body = {"meta": _meta(meta_extra), "response_type": "array",
            "data": [serialize(e) for e in page]}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Not found."}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed."}}
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(e)}}
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
def authorize(*roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers.")
    if role not in roles:
        fail("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")
    return uid, role


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", 422, "Body must be a JSON object.")
    return data


def get_pagination():
    q = request.args
    try:
        limit = int(q.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    try:
        offset = int(q.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    return limit, offset


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        fail("ERR_VALIDATION", 422, f"Missing or invalid field: {field}")
    return v


def require_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_VALIDATION", 422, f"Missing or invalid integer: {field}")
    if minimum is not None and v < minimum:
        fail("ERR_VALIDATION", 422, f"Field {field} must be >= {minimum}")
    return v


def require_number(body, field, minimum=None, exclusive=False):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail("ERR_VALIDATION", 422, f"Missing or invalid number: {field}")
    if minimum is not None:
        if exclusive and not v > minimum:
            fail("ERR_VALIDATION", 422, f"Field {field} must be > {minimum}")
        if not exclusive and v < minimum:
            fail("ERR_VALIDATION", 422, f"Field {field} must be >= {minimum}")
    return v


def optional_bool(body, field, default=False):
    v = body.get(field, default)
    if v is None:
        return default
    if not isinstance(v, bool):
        fail("ERR_VALIDATION", 422, f"Field {field} must be a boolean")
    return v


def get_or_404(store, key, error_id):
    if key is None:
        fail("ERR_VALIDATION", 422, "Missing identifier.")
    ent = db[store].get(key)
    if ent is None:
        fail(error_id, 404, f"{error_id}")
    return ent


def valid_npi(v):
    return isinstance(v, str) and len(v) == 10 and v.isdigit()


# ===========================================================================
# PRODUCTS
# ===========================================================================
@app.post("/products")
def create_product():
    authorize("StoreManager")
    b = body_json()
    name = require_str(b, "name")
    brand = require_str(b, "brand")
    category = require_str(b, "category")
    if category not in CATEGORIES:
        fail("ERR_VALIDATION", 422, "Invalid category")
    base_price = require_int(b, "base_price_cents", 0)
    allowable = b.get("medicare_allowable_cents", 0)
    if allowable is None:
        allowable = 0
    if isinstance(allowable, bool) or not isinstance(allowable, int) or allowable < 0:
        fail("ERR_VALIDATION", 422, "Invalid medicare_allowable_cents")
    hcpcs = b.get("hcpcs_code", None)
    if hcpcs is not None and not isinstance(hcpcs, str):
        fail("ERR_VALIDATION", 422, "Invalid hcpcs_code")
    p = new_entity({
        "name": name, "brand": brand, "category": category,
        "base_price_cents": base_price, "medicare_allowable_cents": allowable,
        "hcpcs_code": hcpcs,
    })
    db["products"][p["id"]] = p
    return ok(ser_product(p), 201)


@app.get("/products")
def list_products():
    authorize("StoreManager", "BillingSpecialist", "Fitter")
    items = list(db["products"].values())
    q = request.args
    if "category" in q:
        items = [p for p in items if p["category"] == q["category"]]
    if "is_recalled" in q:
        want = q["is_recalled"].lower() == "true"
        items = [p for p in items if product_is_recalled(p) == want]
    return ok_list(items, ser_product)


@app.get("/products/<pid>")
def get_product(pid):
    authorize("StoreManager", "BillingSpecialist", "Fitter")
    return ok(ser_product(get_or_404("products", pid, "ERR_PRODUCT_NOT_FOUND")))


# ===========================================================================
# INVENTORY ITEMS
# ===========================================================================
@app.post("/inventory-items")
def create_inventory():
    authorize("StoreManager")
    b = body_json()
    product_id = require_str(b, "product_id")
    size = require_number(b, "size", 0, exclusive=True)
    width = require_str(b, "width")
    if width not in WIDTHS:
        fail("ERR_VALIDATION", 422, "Invalid width")
    lot = require_str(b, "lot_number")
    qoh = require_int(b, "quantity_on_hand", 0)
    get_or_404("products", product_id, "ERR_PRODUCT_NOT_FOUND")
    i = new_entity({
        "product_id": product_id, "size": size, "width": width, "lot_number": lot,
        "quantity_on_hand": qoh, "quantity_reserved": 0, "status": "AVAILABLE",
    })
    db["inventory_items"][i["id"]] = i
    return ok(ser_inventory(i), 201)


@app.get("/inventory-items")
def list_inventory():
    authorize("StoreManager", "Fitter")
    items = list(db["inventory_items"].values())
    q = request.args
    if "product_id" in q:
        items = [i for i in items if i["product_id"] == q["product_id"]]
    if "status" in q:
        items = [i for i in items if i["status"] == q["status"]]
    if "size" in q:
        try:
            sz = float(q["size"])
            items = [i for i in items if float(i["size"]) == sz]
        except ValueError:
            items = []
    if "width" in q:
        items = [i for i in items if i["width"] == q["width"]]
    return ok_list(items, ser_inventory)


@app.get("/inventory-items/<iid>")
def get_inventory(iid):
    authorize("StoreManager", "Fitter")
    return ok(ser_inventory(get_or_404("inventory_items", iid, "ERR_INVENTORY_ITEM_NOT_FOUND")))


# ===========================================================================
# CUSTOMERS
# ===========================================================================
@app.post("/customers")
def create_customer():
    authorize("Fitter", "StoreManager")
    b = body_json()
    full_name = require_str(b, "full_name")
    dob = require_str(b, "date_of_birth")
    try:
        parse_date(dob)
    except ValueError:
        fail("ERR_VALIDATION", 422, "Invalid date_of_birth")
    mbi = b.get("medicare_beneficiary_id", None)
    if mbi is not None and not isinstance(mbi, str):
        fail("ERR_VALIDATION", 422, "Invalid medicare_beneficiary_id")
    c = new_entity({
        "full_name": full_name, "date_of_birth": dob,
        "medicare_beneficiary_id": mbi,
    })
    db["customers"][c["id"]] = c
    return ok(ser_customer(c), 201)


@app.get("/customers")
def list_customers():
    authorize("Fitter", "StoreManager", "BillingSpecialist")
    items = list(db["customers"].values())
    q = request.args
    if "medicare_beneficiary_id" in q:
        items = [c for c in items if c["medicare_beneficiary_id"] == q["medicare_beneficiary_id"]]
    if "is_pediatric" in q:
        want = q["is_pediatric"].lower() == "true"
        items = [c for c in items
                 if (customer_age_years(c) < PEDIATRIC_AGE_THRESHOLD_YEARS) == want]
    return ok_list(items, ser_customer)


@app.get("/customers/<cid>")
def get_customer(cid):
    uid, role = authorize("Fitter", "StoreManager", "BillingSpecialist", "Customer")
    c = get_or_404("customers", cid, "ERR_CUSTOMER_NOT_FOUND")
    if role == "Customer" and cid != uid:
        fail("ERR_UNAUTHORIZED", 403, "Customers may only read their own record.")
    return ok(ser_customer(c))


# ===========================================================================
# FOOT MEASUREMENTS
# ===========================================================================
@app.post("/customers/<cid>/measurements")
def create_measurement(cid):
    authorize("Fitter")
    b = body_json()
    ll = require_number(b, "foot_length_mm_left", 0, exclusive=True)
    lr = require_number(b, "foot_length_mm_right", 0, exclusive=True)
    wl = require_number(b, "foot_width_mm_left", 0, exclusive=True)
    wr = require_number(b, "foot_width_mm_right", 0, exclusive=True)
    get_or_404("customers", cid, "ERR_CUSTOMER_NOT_FOUND")
    prior = latest_measurement(cid)
    if prior is None:
        delta = 0
    else:
        delta = rhu(Decimal(str(max(ll, lr))) - Decimal(str(max(
            prior["foot_length_mm_left"], prior["foot_length_mm_right"]))))
    m = new_entity({
        "customer_id": cid, "measured_at": clock_now(),
        "foot_length_mm_left": ll, "foot_length_mm_right": lr,
        "foot_width_mm_left": wl, "foot_width_mm_right": wr,
        "length_change_mm_from_prior": delta,
    }, immutable=True)
    db["measurements"][m["id"]] = m
    return ok(ser_measurement(m), 201)


@app.get("/customers/<cid>/measurements")
def list_measurements(cid):
    authorize("Fitter", "StoreManager")
    get_or_404("customers", cid, "ERR_CUSTOMER_NOT_FOUND")
    items = [m for m in db["measurements"].values() if m["customer_id"] == cid]
    return ok_list(items, ser_measurement)


# ===========================================================================
# FITTERS
# ===========================================================================
@app.post("/fitters")
def create_fitter():
    authorize("StoreManager")
    b = body_json()
    full_name = require_str(b, "full_name")
    credential = b.get("credential", None)
    if credential is not None and not isinstance(credential, str):
        fail("ERR_VALIDATION", 422, "Invalid credential")
    f = new_entity({"full_name": full_name, "credential": credential})
    db["fitters"][f["id"]] = f
    return ok(ser_fitter(f), 201)


@app.get("/fitters/<fid>")
def get_fitter(fid):
    authorize("StoreManager", "Fitter")
    return ok(ser_fitter(get_or_404("fitters", fid, "ERR_FITTER_NOT_FOUND")))


# ===========================================================================
# GAIT LABS
# ===========================================================================
@app.post("/gait-labs")
def create_gait_lab():
    authorize("StoreManager")
    b = body_json()
    name = require_str(b, "name")
    cap = require_int(b, "concurrent_capacity", 1)
    g = new_entity({"name": name, "concurrent_capacity": cap})
    db["gait_labs"][g["id"]] = g
    return ok(ser_gait_lab(g), 201)


@app.get("/gait-labs/<gid>")
def get_gait_lab(gid):
    authorize("StoreManager", "Fitter")
    return ok(ser_gait_lab(get_or_404("gait_labs", gid, "ERR_GAIT_LAB_NOT_FOUND")))


# ===========================================================================
# APPOINTMENTS
# ===========================================================================
def intervals_overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


@app.post("/appointments")
def create_appointment():
    authorize("Fitter", "StoreManager")
    b = body_json()
    # (3) body well-formedness
    customer_id = require_str(b, "customer_id")
    fitter_id = require_str(b, "fitter_id")
    appt_type = require_str(b, "appointment_type")
    if appt_type not in ("FITTING", "GAIT", "DIABETIC_FITTING"):
        fail("ERR_VALIDATION", 422, "Invalid appointment_type")
    gait_lab_id = b.get("gait_lab_id", None)
    if appt_type == "GAIT":
        if not gait_lab_id or not isinstance(gait_lab_id, str):
            fail("ERR_VALIDATION", 422, "gait_lab_id required for GAIT")
    else:
        if gait_lab_id is not None:
            fail("ERR_VALIDATION", 422, "gait_lab_id must be null unless GAIT")
    st_raw = require_str(b, "start_time")
    et_raw = require_str(b, "end_time")
    try:
        start = parse_dt(st_raw)
        end = parse_dt(et_raw)
    except ValueError:
        fail("ERR_VALIDATION", 422, "Invalid start_time/end_time")
    # (4) time range
    if not end > start:
        fail("ERR_INVALID_TIME_RANGE", 422, "end_time must be after start_time")
    # (5) existence
    get_or_404("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")
    get_or_404("fitters", fitter_id, "ERR_FITTER_NOT_FOUND")
    if gait_lab_id is not None:
        get_or_404("gait_labs", gait_lab_id, "ERR_GAIT_LAB_NOT_FOUND")
    # (14) fitter double-booked: existing occupies [start, end + buffer)
    buf = FITTER_CLEANUP_BUFFER_MIN * 60
    from datetime import timedelta
    for a in db["appointments"].values():
        if a["fitter_id"] == fitter_id and a["status"] in ("SCHEDULED", "CHECKED_IN"):
            occ_end = a["end_time"] + timedelta(seconds=buf)
            if intervals_overlap(start, end, a["start_time"], occ_end):
                fail("ERR_FITTER_DOUBLE_BOOKED", 409, "Fitter is double booked")
    # (17) gait lab capacity
    if appt_type == "GAIT":
        lab = db["gait_labs"][gait_lab_id]
        overlapping = 0
        for a in db["appointments"].values():
            if (a["gait_lab_id"] == gait_lab_id and a["appointment_type"] == "GAIT"
                    and a["status"] in ("SCHEDULED", "CHECKED_IN")
                    and intervals_overlap(start, end, a["start_time"], a["end_time"])):
                overlapping += 1
        if overlapping >= lab["concurrent_capacity"]:
            fail("ERR_GAIT_LAB_AT_CAPACITY", 409, "Gait lab at capacity")
    a = new_entity({
        "customer_id": customer_id, "fitter_id": fitter_id, "gait_lab_id": gait_lab_id,
        "appointment_type": appt_type, "start_time": start, "end_time": end,
        "status": "SCHEDULED", "recommended_mondo_mm": None, "recommended_width": None,
        "gait_findings": None, "recommended_orthotic": None,
    })
    db["appointments"][a["id"]] = a
    return ok(ser_appointment(a), 201)


@app.get("/appointments")
def list_appointments():
    authorize("Fitter", "StoreManager")
    items = list(db["appointments"].values())
    q = request.args
    for key in ("customer_id", "fitter_id", "gait_lab_id", "status"):
        if key in q:
            items = [a for a in items if a[key] == q[key]]
    return ok_list(items, ser_appointment)


@app.get("/appointments/<aid>")
def get_appointment(aid):
    uid, role = authorize("Fitter", "StoreManager", "Customer")
    a = get_or_404("appointments", aid, "ERR_APPOINTMENT_NOT_FOUND")
    if role == "Customer" and a["customer_id"] != uid:
        fail("ERR_UNAUTHORIZED", 403, "Customers may only read their own appointments.")
    return ok(ser_appointment(a))


@app.post("/appointments/<aid>/check-in")
def checkin_appointment(aid):
    authorize("Fitter")
    a = get_or_404("appointments", aid, "ERR_APPOINTMENT_NOT_FOUND")
    if a["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", 409, "Appointment not SCHEDULED")
    a["status"] = "CHECKED_IN"
    touch(a)
    return ok(ser_appointment(a))


@app.post("/appointments/<aid>/complete")
def complete_appointment(aid):
    authorize("Fitter")
    b = body_json()
    a = get_or_404("appointments", aid, "ERR_APPOINTMENT_NOT_FOUND")
    if a["status"] not in ("SCHEDULED", "CHECKED_IN"):
        fail("ERR_INVALID_STATE", 409, "Appointment not completable")
    rw = b.get("recommended_width", None)
    if rw is not None and rw not in WIDTHS:
        fail("ERR_VALIDATION", 422, "Invalid recommended_width")
    if "recommended_mondo_mm" in b and b["recommended_mondo_mm"] is not None:
        a["recommended_mondo_mm"] = b["recommended_mondo_mm"]
    if rw is not None:
        a["recommended_width"] = rw
    if "gait_findings" in b:
        a["gait_findings"] = b["gait_findings"]
    if "recommended_orthotic" in b:
        a["recommended_orthotic"] = b["recommended_orthotic"]
    a["status"] = "COMPLETED"
    touch(a)
    return ok(ser_appointment(a))


@app.post("/appointments/<aid>/cancel")
def cancel_appointment(aid):
    uid, role = authorize("Fitter", "StoreManager", "Customer")
    a = get_or_404("appointments", aid, "ERR_APPOINTMENT_NOT_FOUND")
    if role == "Customer" and a["customer_id"] != uid:
        fail("ERR_UNAUTHORIZED", 403, "Customers may only cancel their own appointments.")
    if a["status"] not in ("SCHEDULED", "CHECKED_IN"):
        fail("ERR_INVALID_STATE", 409, "Appointment not cancellable")
    a["status"] = "CANCELLED"
    touch(a)
    return ok(ser_appointment(a))


@app.post("/appointments/<aid>/no-show")
def noshow_appointment(aid):
    authorize("Fitter", "StoreManager")
    a = get_or_404("appointments", aid, "ERR_APPOINTMENT_NOT_FOUND")
    if a["status"] not in ("SCHEDULED", "CHECKED_IN"):
        fail("ERR_INVALID_STATE", 409, "Appointment not markable no-show")
    a["status"] = "NO_SHOW"
    touch(a)
    return ok(ser_appointment(a))


# ===========================================================================
# SALES
# ===========================================================================
@app.post("/sales")
def create_sale():
    authorize("Fitter", "StoreManager")
    b = body_json()
    customer_id = require_str(b, "customer_id")
    fitter_id = require_str(b, "fitter_id")
    appointment_id = b.get("appointment_id", None)
    if appointment_id is not None and not isinstance(appointment_id, str):
        fail("ERR_VALIDATION", 422, "Invalid appointment_id")
    get_or_404("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")
    get_or_404("fitters", fitter_id, "ERR_FITTER_NOT_FOUND")
    if appointment_id is not None:
        get_or_404("appointments", appointment_id, "ERR_APPOINTMENT_NOT_FOUND")
    s = new_entity({
        "customer_id": customer_id, "fitter_id": fitter_id,
        "appointment_id": appointment_id, "payment_status": "UNPAID",
        "fulfillment_status": "PENDING", "loyalty_tier_at_fulfill": None,
        "loyalty_points_earned": 0,
    })
    db["sales"][s["id"]] = s
    return ok(ser_sale(s), 201)


@app.get("/sales")
def list_sales():
    authorize("Fitter", "StoreManager")
    items = list(db["sales"].values())
    q = request.args
    for key in ("customer_id", "fitter_id", "appointment_id",
                "payment_status", "fulfillment_status"):
        if key in q:
            items = [s for s in items if s[key] == q[key]]
    return ok_list(items, ser_sale)


@app.get("/sales/<sid>")
def get_sale(sid):
    uid, role = authorize("Fitter", "StoreManager", "Customer")
    s = get_or_404("sales", sid, "ERR_SALE_NOT_FOUND")
    if role == "Customer" and s["customer_id"] != uid:
        fail("ERR_UNAUTHORIZED", 403, "Customers may only read their own sales.")
    return ok(ser_sale(s))


@app.post("/sales/<sid>/lines")
def add_sale_line(sid):
    authorize("Fitter", "StoreManager")
    b = body_json()
    # (3) body
    inventory_item_id = require_str(b, "inventory_item_id")
    quantity = require_int(b, "quantity", 1)
    requires_medicare = optional_bool(b, "requires_medicare", False)
    # (5) existence (path first, then body FK)
    sale = get_or_404("sales", sid, "ERR_SALE_NOT_FOUND")
    item = get_or_404("inventory_items", inventory_item_id, "ERR_INVENTORY_ITEM_NOT_FOUND")
    product = db["products"][item["product_id"]]
    customer = db["customers"][sale["customer_id"]]
    # (11) quarantine / recall (only for requires_medicare lines)
    if requires_medicare:
        if product_is_recalled(product) or item["status"] == "QUARANTINED":
            fail("ERR_ITEM_QUARANTINED", 409, "Recalled product or quarantined item")
    # (12) pediatric size
    if customer_age_years(customer) < PEDIATRIC_AGE_THRESHOLD_YEARS:
        lm = latest_measurement(customer["id"])
        if lm is not None:
            equiv = size_to_mondo_mm(item["size"])
            if equiv < recommended_mondo(lm, customer):
                fail("ERR_PEDIATRIC_SIZE_TOO_SMALL", 422, "Size below recommended pediatric fit")
    # (13) missing measurement (requires COMPLETED DIABETIC_FITTING appt)
    if requires_medicare:
        appt = None
        if sale["appointment_id"] is not None:
            appt = db["appointments"].get(sale["appointment_id"])
        ok_appt = (appt is not None and appt["appointment_type"] == "DIABETIC_FITTING"
                   and appt["status"] == "COMPLETED"
                   and appt["customer_id"] == sale["customer_id"])
        if not ok_appt:
            fail("ERR_MISSING_MEASUREMENT", 409, "No completed DIABETIC_FITTING appointment")
    # (16) out of stock
    if item_available(item) < quantity:
        fail("ERR_OUT_OF_STOCK", 409, "Insufficient available stock")
    line = new_entity({
        "sale_id": sid, "inventory_item_id": inventory_item_id, "quantity": quantity,
        "unit_price_cents": product["base_price_cents"],
        "requires_medicare": requires_medicare, "status": "ACTIVE",
    })
    db["sale_lines"][line["id"]] = line
    item["quantity_reserved"] += quantity
    touch(item)
    touch(sale)  # subtotal changed
    return ok(ser_sale_line(line), 201)


@app.get("/sale-lines")
def list_sale_lines():
    authorize("Fitter", "StoreManager")
    items = list(db["sale_lines"].values())
    q = request.args
    if "sale_id" in q:
        items = [l for l in items if l["sale_id"] == q["sale_id"]]
    if "inventory_item_id" in q:
        items = [l for l in items if l["inventory_item_id"] == q["inventory_item_id"]]
    return ok_list(items, ser_sale_line)


@app.get("/sale-lines/<lid>")
def get_sale_line(lid):
    authorize("Fitter", "StoreManager")
    return ok(ser_sale_line(get_or_404("sale_lines", lid, "ERR_SALE_LINE_NOT_FOUND")))


@app.post("/sales/<sid>/fulfill")
def fulfill_sale(sid):
    authorize("Fitter", "StoreManager")
    sale = get_or_404("sales", sid, "ERR_SALE_NOT_FOUND")
    if sale["fulfillment_status"] != "PENDING":
        fail("ERR_INVALID_STATE", 409, "Sale not PENDING")
    active = [l for l in sale_lines_of(sid) if l["status"] == "ACTIVE"]
    if not active:
        fail("ERR_INVALID_STATE", 409, "Sale has no active lines")
    # (11) quarantine check
    for l in active:
        item = db["inventory_items"][l["inventory_item_id"]]
        if item["status"] != "AVAILABLE":
            fail("ERR_ITEM_QUARANTINED", 409, "Line item not AVAILABLE")
    customer = db["customers"][sale["customer_id"]]
    tier = loyalty_tier_from_balance(loyalty_balance(customer["id"]))
    # decrement stock
    for l in active:
        item = db["inventory_items"][l["inventory_item_id"]]
        item["quantity_on_hand"] -= l["quantity"]
        item["quantity_reserved"] -= l["quantity"]
        touch(item)
    # accrual: round per line then sum
    mult = TIER_MULTIPLIER[tier]
    points = 0
    for l in active:
        line_total = l["unit_price_cents"] * l["quantity"]
        points += rhu(Decimal(line_total) / Decimal("100") * mult)
    sale["loyalty_tier_at_fulfill"] = tier
    sale["loyalty_points_earned"] = points
    sale["fulfillment_status"] = "FULFILLED"
    ledger = new_entity({
        "customer_id": customer["id"], "sale_id": sid,
        "points_delta": points, "reason": "EARN",
    }, immutable=True)
    db["ledger"][ledger["id"]] = ledger
    touch(sale)
    touch(customer)  # loyalty balance changed
    return ok(ser_sale(sale))


@app.post("/sales/<sid>/pay")
def pay_sale(sid):
    authorize("Fitter", "StoreManager")
    b = body_json()
    amount = require_int(b, "amount_tendered_cents", 0)
    sale = get_or_404("sales", sid, "ERR_SALE_NOT_FOUND")
    if sale["payment_status"] != "UNPAID":
        fail("ERR_INVALID_STATE", 409, "Sale not UNPAID")
    if amount < sale_subtotal(sid):
        fail("ERR_VALIDATION", 422, "amount_tendered_cents below subtotal")
    sale["payment_status"] = "PAID"
    touch(sale)
    return ok(ser_sale(sale))


@app.post("/sales/<sid>/cancel")
def cancel_sale(sid):
    authorize("Fitter", "StoreManager")
    sale = get_or_404("sales", sid, "ERR_SALE_NOT_FOUND")
    if sale["fulfillment_status"] != "PENDING":
        fail("ERR_INVALID_STATE", 409, "Sale not PENDING")
    for l in sale_lines_of(sid):
        if l["status"] == "ACTIVE":
            item = db["inventory_items"][l["inventory_item_id"]]
            item["quantity_reserved"] -= l["quantity"]
            touch(item)
    sale["fulfillment_status"] = "CANCELLED"
    touch(sale)
    return ok(ser_sale(sale))


# ===========================================================================
# CERTIFICATIONS
# ===========================================================================
@app.post("/customers/<cid>/certifications")
def create_certification(cid):
    authorize("BillingSpecialist")
    b = body_json()
    # (3) body well-formedness
    cnpi = b.get("certifying_physician_npi")
    pnpi = b.get("prescribing_practitioner_npi")
    if not valid_npi(cnpi):
        fail("ERR_VALIDATION", 422, "certifying_physician_npi must be 10 digits")
    if not valid_npi(pnpi):
        fail("ERR_VALIDATION", 422, "prescribing_practitioner_npi must be 10 digits")
    stmt = require_str(b, "statement_date")
    visit = require_str(b, "in_person_visit_date")
    try:
        parse_date(stmt)
        visit_date = parse_date(visit)
    except ValueError:
        fail("ERR_VALIDATION", 422, "Invalid statement_date/in_person_visit_date")
    if "expected_customer_version" not in b:
        fail("ERR_VALIDATION", 422, "expected_customer_version is required")
    expected = b.get("expected_customer_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        fail("ERR_VALIDATION", 422, "expected_customer_version must be an integer")
    # (5) existence
    customer = get_or_404("customers", cid, "ERR_CUSTOMER_NOT_FOUND")
    # (15) certification-visit-expired
    threshold = subtract_months(clock_now().date(), CERT_VISIT_WINDOW_MONTHS)
    if visit_date < threshold:
        fail("ERR_CERTIFICATION_VISIT_EXPIRED", 422, "in_person_visit_date too old")
    # (20) OCC (last)
    if expected != customer["version"]:
        fail("ERR_STALE_VERSION", 412, "expected_customer_version mismatch")
    # supersede prior COMPLETE certifications
    for cert in db["certifications"].values():
        if cert["customer_id"] == cid and cert["status"] == "COMPLETE":
            cert["status"] = "SUPERSEDED"
            touch(cert)
    cert = new_entity({
        "customer_id": cid, "certifying_physician_npi": cnpi,
        "prescribing_practitioner_npi": pnpi, "statement_date": stmt,
        "in_person_visit_date": visit, "status": "COMPLETE",
    })
    db["certifications"][cert["id"]] = cert
    touch(customer)  # increments Customer.version by 1
    return ok(ser_certification(cert), 201)


@app.get("/customers/<cid>/certifications")
def list_certifications(cid):
    authorize("BillingSpecialist", "Fitter")
    get_or_404("customers", cid, "ERR_CUSTOMER_NOT_FOUND")
    items = [c for c in db["certifications"].values() if c["customer_id"] == cid]
    return ok_list(items, ser_certification)


# ===========================================================================
# MEDICARE CLAIMS
# ===========================================================================
def claim_product_allowable(claim):
    sale = db["sales"].get(claim["sale_id"])
    if sale is None:
        return 0
    lines = sale_lines_of(sale["id"])
    match = None
    fallback = None
    for l in lines:
        item = db["inventory_items"].get(l["inventory_item_id"])
        if item is None:
            continue
        prod = db["products"].get(item["product_id"])
        if prod is None:
            continue
        if fallback is None:
            fallback = prod
        if prod.get("hcpcs_code") == claim["hcpcs_code"]:
            match = prod
            break
    prod = match or fallback
    return prod["medicare_allowable_cents"] if prod else 0


@app.post("/medicare-claims")
def create_claim():
    authorize("BillingSpecialist")
    b = body_json()
    customer_id = require_str(b, "customer_id")
    sale_id = require_str(b, "sale_id")
    certification_id = require_str(b, "certification_id")
    hcpcs = require_str(b, "hcpcs_code")
    billed = require_int(b, "billed_amount_cents", 0)
    get_or_404("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")
    get_or_404("sales", sale_id, "ERR_SALE_NOT_FOUND")
    get_or_404("certifications", certification_id, "ERR_CERTIFICATION_NOT_FOUND")
    c = new_entity({
        "customer_id": customer_id, "sale_id": sale_id,
        "certification_id": certification_id, "hcpcs_code": hcpcs,
        "billed_amount_cents": billed, "calendar_year": None,
        "allowed_amount_cents": None, "provisional_reimbursement_cents": None,
        "deductible_applied_cents": 0, "medicare_paid_cents": 0,
        "patient_responsibility_cents": 0, "status": "DRAFT",
    })
    db["claims"][c["id"]] = c
    return ok(ser_claim(c), 201)


@app.get("/medicare-claims")
def list_claims():
    authorize("BillingSpecialist")
    items = list(db["claims"].values())
    q = request.args
    for key in ("customer_id", "sale_id", "certification_id", "status"):
        if key in q:
            items = [c for c in items if c[key] == q[key]]
    if "calendar_year" in q:
        try:
            yr = int(q["calendar_year"])
            items = [c for c in items if c["calendar_year"] == yr]
        except ValueError:
            items = []
    return ok_list(items, ser_claim)


@app.get("/medicare-claims/<clid>")
def get_claim(clid):
    authorize("BillingSpecialist")
    return ok(ser_claim(get_or_404("claims", clid, "ERR_CLAIM_NOT_FOUND")))


def _check_annual_limits(claim):
    year = clock_now().year
    customer_id = claim["customer_id"]
    if claim["hcpcs_code"] == "A5500":
        if medicare_pairs_ytd(customer_id, year) >= MEDICARE_ANNUAL_DIABETIC_SHOE_PAIR_LIMIT:
            fail("ERR_ANNUAL_PAIR_LIMIT_EXCEEDED", 409, "Annual pair limit exceeded")
    if claim["hcpcs_code"] in ("A5512", "A5513"):
        if medicare_inserts_ytd(customer_id, year) >= MEDICARE_ANNUAL_INSERT_LIMIT:
            fail("ERR_ANNUAL_INSERT_LIMIT_EXCEEDED", 409, "Annual insert limit exceeded")


def _set_submit_fields(claim):
    claim["calendar_year"] = clock_now().year
    allowable = claim_product_allowable(claim)
    allowed = min(claim["billed_amount_cents"], allowable)
    claim["allowed_amount_cents"] = allowed
    claim["provisional_reimbursement_cents"] = rhu(
        Decimal(allowed) * (Decimal("1") - MEDICARE_COINSURANCE_RATE))


@app.post("/medicare-claims/<clid>/submit")
def submit_claim(clid):
    authorize("BillingSpecialist")
    claim = get_or_404("claims", clid, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409, "Claim not DRAFT")
    cert = db["certifications"].get(claim["certification_id"])
    if cert is None or cert["status"] != "COMPLETE":
        fail("ERR_CERTIFICATION_INCOMPLETE", 409, "Certification not COMPLETE")
    sale = db["sales"].get(claim["sale_id"])
    if sale is None or sale["fulfillment_status"] not in ("FULFILLED", "PARTIALLY_RETURNED"):
        fail("ERR_SALE_NOT_FULFILLED", 409, "Sale not fulfilled")
    _check_annual_limits(claim)
    _set_submit_fields(claim)
    claim["status"] = "SUBMITTED"
    touch(claim)
    return ok(ser_claim(claim))


@app.post("/medicare-claims/<clid>/adjudicate")
def adjudicate_claim(clid):
    authorize("BillingSpecialist")
    b = body_json()
    decision = b.get("payer_decision")
    if decision not in ("PAID", "DENIED"):
        fail("ERR_VALIDATION", 422, "payer_decision must be PAID or DENIED")
    claim = get_or_404("claims", clid, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", 409, "Claim not SUBMITTED")
    if decision == "DENIED":
        claim["status"] = "DENIED"
        touch(claim)
        return ok(ser_claim(claim))
    # PAID
    allowed = claim["allowed_amount_cents"]
    year = claim["calendar_year"]
    used = sum(c["deductible_applied_cents"] for c in db["claims"].values()
               if c["customer_id"] == claim["customer_id"] and c["status"] == "PAID"
               and c["calendar_year"] == year)
    remaining = MEDICARE_ANNUAL_DEDUCTIBLE_CENTS - used
    deductible_applied = min(allowed, remaining)
    after = allowed - deductible_applied
    coinsurance = rhu(Decimal(after) * MEDICARE_COINSURANCE_RATE)
    claim["deductible_applied_cents"] = deductible_applied
    claim["medicare_paid_cents"] = after - coinsurance
    claim["patient_responsibility_cents"] = deductible_applied + coinsurance
    claim["status"] = "PAID"
    touch(claim)
    touch(db["customers"][claim["customer_id"]])  # medicare fields changed
    return ok(ser_claim(claim))


@app.post("/medicare-claims/<clid>/resubmit")
def resubmit_claim(clid):
    authorize("BillingSpecialist")
    claim = get_or_404("claims", clid, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "DENIED":
        fail("ERR_INVALID_STATE", 409, "Claim not DENIED")
    _check_annual_limits(claim)
    _set_submit_fields(claim)
    claim["status"] = "SUBMITTED"
    touch(claim)
    return ok(ser_claim(claim))


@app.post("/medicare-claims/<clid>/void")
def void_claim(clid):
    authorize("BillingSpecialist")
    claim = get_or_404("claims", clid, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "PAID":
        fail("ERR_INVALID_STATE", 409, "Claim not PAID")
    claim["status"] = "VOIDED"
    touch(claim)
    touch(db["customers"][claim["customer_id"]])  # medicare fields restored
    return ok(ser_claim(claim))


# ===========================================================================
# RETURNS
# ===========================================================================
@app.post("/returns")
def create_return():
    uid, role = authorize("Customer", "Fitter", "StoreManager")
    b = body_json()
    sale_id = require_str(b, "sale_id")
    sale_line_id = require_str(b, "sale_line_id")
    return_type = require_str(b, "return_type")
    if return_type not in ("RETURN", "EXCHANGE"):
        fail("ERR_VALIDATION", 422, "Invalid return_type")
    reason = b.get("reason", None)
    if reason is not None and not isinstance(reason, str):
        fail("ERR_VALIDATION", 422, "Invalid reason")
    sale = get_or_404("sales", sale_id, "ERR_SALE_NOT_FOUND")
    line = get_or_404("sale_lines", sale_line_id, "ERR_SALE_LINE_NOT_FOUND")
    if line["sale_id"] != sale_id:
        fail("ERR_SALE_LINE_NOT_FOUND", 404, "Sale line not on sale")
    if role == "Customer" and sale["customer_id"] != uid:
        fail("ERR_UNAUTHORIZED", 403, "Customers may only return their own sales.")
    r = new_entity({
        "sale_id": sale_id, "sale_line_id": sale_line_id,
        "replacement_inventory_item_id": None, "return_type": return_type,
        "reason": reason, "refund_amount_cents": 0, "restocking_fee_cents": 0,
        "price_difference_cents": 0, "status": "REQUESTED",
    })
    db["returns"][r["id"]] = r
    return ok(ser_return(r), 201)


@app.get("/returns")
def list_returns():
    uid, role = authorize("Fitter", "StoreManager", "Customer")
    items = list(db["returns"].values())
    q = request.args
    for key in ("sale_id", "sale_line_id", "replacement_inventory_item_id", "status"):
        if key in q:
            items = [r for r in items if r[key] == q[key]]
    if role == "Customer":
        items = [r for r in items
                 if db["sales"].get(r["sale_id"], {}).get("customer_id") == uid]
    return ok_list(items, ser_return)


@app.get("/returns/<rid>")
def get_return(rid):
    uid, role = authorize("Fitter", "StoreManager", "Customer")
    r = get_or_404("returns", rid, "ERR_RETURN_NOT_FOUND")
    if role == "Customer":
        sale = db["sales"].get(r["sale_id"])
        if not sale or sale["customer_id"] != uid:
            fail("ERR_UNAUTHORIZED", 403, "Customers may only read their own returns.")
    return ok(ser_return(r))


@app.post("/returns/<rid>/approve")
def approve_return(rid):
    authorize("StoreManager")
    r = get_or_404("returns", rid, "ERR_RETURN_NOT_FOUND")
    if r["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", 409, "Return not REQUESTED")
    sale = db["sales"][r["sale_id"]]
    if sale["fulfillment_status"] not in ("FULFILLED", "PARTIALLY_RETURNED"):
        fail("ERR_SALE_NOT_FULFILLED", 409, "Sale not fulfilled")
    line = db["sale_lines"][r["sale_line_id"]]
    if line["status"] != "ACTIVE":
        fail("ERR_LINE_ALREADY_RETURNED", 409, "Sale line no longer ACTIVE")
    r["status"] = "APPROVED"
    touch(r)
    return ok(ser_return(r))


@app.post("/returns/<rid>/reject")
def reject_return(rid):
    authorize("StoreManager")
    b = body_json()
    r = get_or_404("returns", rid, "ERR_RETURN_NOT_FOUND")
    if r["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", 409, "Return not REQUESTED")
    reason = b.get("reason", None)
    if reason is not None:
        if not isinstance(reason, str):
            fail("ERR_VALIDATION", 422, "Invalid reason")
        r["reason"] = reason
    r["status"] = "REJECTED"
    touch(r)
    return ok(ser_return(r))


def _recompute_sale_fulfillment(sale):
    active = [l for l in sale_lines_of(sale["id"]) if l["status"] == "ACTIVE"]
    if active:
        sale["fulfillment_status"] = "PARTIALLY_RETURNED"
    else:
        sale["fulfillment_status"] = "RETURNED"
        if sale["payment_status"] == "PAID":
            sale["payment_status"] = "REFUNDED"


@app.post("/returns/<rid>/refund")
def refund_return(rid):
    authorize("StoreManager")
    r = get_or_404("returns", rid, "ERR_RETURN_NOT_FOUND")
    if r["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", 409, "Return not APPROVED")
    if r["return_type"] != "RETURN":
        fail("ERR_EXCHANGE_TYPE_MISMATCH", 409, "Refund requires return_type RETURN")
    sale = db["sales"][r["sale_id"]]
    line = db["sale_lines"][r["sale_line_id"]]
    line_total = line["unit_price_cents"] * line["quantity"]
    days = (clock_now().date() - sale["created_at"].date()).days
    if days <= RETURN_WINDOW_DAYS:
        fee = 0
    else:
        fee = rhu(Decimal(line_total) * RESTOCKING_FEE_RATE)
    r["restocking_fee_cents"] = fee
    r["refund_amount_cents"] = line_total - fee
    # flip line, restock
    line["status"] = "RETURNED"
    touch(line)
    item = db["inventory_items"][line["inventory_item_id"]]
    item["quantity_on_hand"] += line["quantity"]
    touch(item)
    # loyalty reversal
    tier = sale["loyalty_tier_at_fulfill"] or "BRONZE"
    mult = TIER_MULTIPLIER[tier]
    reversal = -rhu(Decimal(line_total) / Decimal("100") * mult)
    entry = new_entity({
        "customer_id": sale["customer_id"], "sale_id": sale["id"],
        "points_delta": reversal, "reason": "REVERSAL",
    }, immutable=True)
    db["ledger"][entry["id"]] = entry
    touch(db["customers"][sale["customer_id"]])
    _recompute_sale_fulfillment(sale)
    touch(sale)
    r["status"] = "REFUNDED"
    touch(r)
    return ok(ser_return(r))


@app.post("/returns/<rid>/exchange")
def exchange_return(rid):
    authorize("StoreManager")
    b = body_json()
    replacement_id = require_str(b, "replacement_inventory_item_id")
    r = get_or_404("returns", rid, "ERR_RETURN_NOT_FOUND")
    replacement = get_or_404("inventory_items", replacement_id, "ERR_INVENTORY_ITEM_NOT_FOUND")
    if r["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", 409, "Return not APPROVED")
    if r["return_type"] != "EXCHANGE":
        fail("ERR_EXCHANGE_TYPE_MISMATCH", 409, "Exchange requires return_type EXCHANGE")
    if replacement["status"] != "AVAILABLE" or item_available(replacement) < 1:
        fail("ERR_OUT_OF_STOCK", 409, "Replacement item unavailable")
    sale = db["sales"][r["sale_id"]]
    line = db["sale_lines"][r["sale_line_id"]]
    repl_product = db["products"][replacement["product_id"]]
    r["price_difference_cents"] = repl_product["base_price_cents"] - line["unit_price_cents"]
    r["replacement_inventory_item_id"] = replacement_id
    line["status"] = "EXCHANGED"
    touch(line)
    orig_item = db["inventory_items"][line["inventory_item_id"]]
    orig_item["quantity_on_hand"] += line["quantity"]
    touch(orig_item)
    replacement["quantity_on_hand"] -= line["quantity"]
    touch(replacement)
    touch(sale)  # subtotal changed
    r["status"] = "EXCHANGED"
    touch(r)
    return ok(ser_return(r))


# ===========================================================================
# SPECIAL ORDERS
# ===========================================================================
def _credit_deposit(order):
    if order["deposit_cents"] > 0:
        entry = new_entity({
            "customer_id": order["customer_id"], "sale_id": None,
            "points_delta": order["deposit_cents"] // 100, "reason": "ADJUST",
        }, immutable=True)
        db["ledger"][entry["id"]] = entry
        touch(db["customers"][order["customer_id"]])


@app.post("/special-orders")
def create_special_order():
    authorize("Fitter", "StoreManager")
    b = body_json()
    customer_id = require_str(b, "customer_id")
    product_id = require_str(b, "product_id")
    size = require_number(b, "requested_size", 0, exclusive=True)
    width = require_str(b, "requested_width")
    if width not in WIDTHS:
        fail("ERR_VALIDATION", 422, "Invalid requested_width")
    deposit = require_int(b, "deposit_cents", 0)
    get_or_404("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")
    get_or_404("products", product_id, "ERR_PRODUCT_NOT_FOUND")
    o = new_entity({
        "customer_id": customer_id, "product_id": product_id,
        "fulfilled_inventory_item_id": None, "requested_size": size,
        "requested_width": width, "deposit_cents": deposit, "status": "DRAFT",
    })
    db["special_orders"][o["id"]] = o
    return ok(ser_special_order(o), 201)


@app.get("/special-orders")
def list_special_orders():
    authorize("Fitter", "StoreManager")
    items = list(db["special_orders"].values())
    q = request.args
    for key in ("customer_id", "product_id", "fulfilled_inventory_item_id", "status"):
        if key in q:
            items = [o for o in items if o[key] == q[key]]
    return ok_list(items, ser_special_order)


@app.get("/special-orders/<oid>")
def get_special_order(oid):
    uid, role = authorize("Fitter", "StoreManager", "Customer")
    o = get_or_404("special_orders", oid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    if role == "Customer" and o["customer_id"] != uid:
        fail("ERR_UNAUTHORIZED", 403, "Customers may only read their own special orders.")
    return ok(ser_special_order(o))


@app.post("/special-orders/<oid>/place")
def place_special_order(oid):
    authorize("StoreManager")
    o = get_or_404("special_orders", oid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    if o["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409, "Special order not DRAFT")
    product = db["products"][o["product_id"]]
    if product_is_recalled(product):
        fail("ERR_ITEM_QUARANTINED", 409, "Product is recalled")
    o["status"] = "ORDERED"
    touch(o)
    return ok(ser_special_order(o))


@app.post("/special-orders/<oid>/receive")
def receive_special_order(oid):
    authorize("StoreManager")
    b = body_json()
    lot = require_str(b, "lot_number")
    qoh = require_int(b, "quantity_on_hand", 0)
    o = get_or_404("special_orders", oid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    if o["status"] != "ORDERED":
        fail("ERR_INVALID_STATE", 409, "Special order not ORDERED")
    item = new_entity({
        "product_id": o["product_id"], "size": o["requested_size"],
        "width": o["requested_width"], "lot_number": lot,
        "quantity_on_hand": qoh, "quantity_reserved": 0, "status": "AVAILABLE",
    })
    db["inventory_items"][item["id"]] = item
    o["fulfilled_inventory_item_id"] = item["id"]
    o["status"] = "RECEIVED"
    touch(o)
    return ok(ser_special_order(o))


@app.post("/special-orders/<oid>/fulfill")
def fulfill_special_order(oid):
    authorize("Fitter", "StoreManager")
    o = get_or_404("special_orders", oid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    if o["status"] != "RECEIVED":
        fail("ERR_INVALID_STATE", 409, "Special order not RECEIVED")
    o["status"] = "FULFILLED"
    touch(o)
    return ok(ser_special_order(o))


@app.post("/special-orders/<oid>/cancel")
def cancel_special_order(oid):
    authorize("StoreManager", "Fitter")
    o = get_or_404("special_orders", oid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    if o["status"] not in ("DRAFT", "ORDERED", "RECEIVED"):
        fail("ERR_INVALID_STATE", 409, "Special order not cancellable")
    _credit_deposit(o)
    o["status"] = "CANCELLED"
    touch(o)
    return ok(ser_special_order(o))


# ===========================================================================
# RECALLS
# ===========================================================================
@app.post("/recalls")
def create_recall():
    authorize("StoreManager")
    b = body_json()
    product_id = require_str(b, "product_id")
    reason = require_str(b, "reason")
    lot = b.get("lot_number", None)
    if lot is not None and not isinstance(lot, str):
        fail("ERR_VALIDATION", 422, "Invalid lot_number")
    get_or_404("products", product_id, "ERR_PRODUCT_NOT_FOUND")
    r = new_entity({
        "product_id": product_id, "lot_number": lot, "reason": reason, "status": "DRAFT",
    })
    db["recalls"][r["id"]] = r
    return ok(ser_recall(r), 201)


@app.get("/recalls")
def list_recalls():
    authorize("StoreManager", "Fitter")
    items = list(db["recalls"].values())
    q = request.args
    if "product_id" in q:
        items = [r for r in items if r["product_id"] == q["product_id"]]
    if "status" in q:
        items = [r for r in items if r["status"] == q["status"]]
    return ok_list(items, ser_recall)


@app.get("/recalls/<rid>")
def get_recall(rid):
    authorize("StoreManager", "Fitter")
    return ok(ser_recall(get_or_404("recalls", rid, "ERR_RECALL_NOT_FOUND")))


@app.post("/recalls/<rid>/issue")
def issue_recall(rid):
    authorize("StoreManager")
    r = get_or_404("recalls", rid, "ERR_RECALL_NOT_FOUND")
    if r["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409, "Recall not DRAFT")
    pid = r["product_id"]
    lot = r["lot_number"]
    # cascade 1: quarantine matching AVAILABLE inventory
    for item in db["inventory_items"].values():
        if item["product_id"] == pid and item["status"] == "AVAILABLE" \
                and (lot is None or item["lot_number"] == lot):
            item["status"] = "QUARANTINED"
            touch(item)
    # cascade 2 + 3 + 4: cancel matching special orders, credit deposit
    for o in db["special_orders"].values():
        if o["product_id"] == pid and o["status"] in ("ORDERED", "RECEIVED"):
            _credit_deposit(o)
            o["status"] = "CANCELLED"
            touch(o)
    r["status"] = "ISSUED"
    touch(r)
    return ok(ser_recall(r))


@app.post("/recalls/<rid>/close")
def close_recall(rid):
    authorize("StoreManager")
    r = get_or_404("recalls", rid, "ERR_RECALL_NOT_FOUND")
    if r["status"] != "ISSUED":
        fail("ERR_INVALID_STATE", 409, "Recall not ISSUED")
    r["status"] = "CLOSED"
    touch(r)
    return ok(ser_recall(r))


# ===========================================================================
# LOYALTY LEDGER
# ===========================================================================
@app.post("/loyalty-ledger")
def create_ledger():
    authorize("StoreManager")
    b = body_json()
    customer_id = require_str(b, "customer_id")
    points_delta = require_int(b, "points_delta")
    reason = require_str(b, "reason")
    if reason not in ("EARN", "REVERSAL", "REDEEM", "ADJUST"):
        fail("ERR_VALIDATION", 422, "Invalid reason")
    sale_id = b.get("sale_id", None)
    if sale_id is not None and not isinstance(sale_id, str):
        fail("ERR_VALIDATION", 422, "Invalid sale_id")
    customer = get_or_404("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")
    if sale_id is not None:
        get_or_404("sales", sale_id, "ERR_SALE_NOT_FOUND")
    entry = new_entity({
        "customer_id": customer_id, "sale_id": sale_id,
        "points_delta": points_delta, "reason": reason,
    }, immutable=True)
    db["ledger"][entry["id"]] = entry
    touch(customer)
    return ok(ser_ledger(entry), 201)


@app.get("/loyalty-ledger")
def list_ledger():
    uid, role = authorize("StoreManager", "Fitter", "Customer")
    items = list(db["ledger"].values())
    q = request.args
    if "customer_id" in q:
        items = [l for l in items if l["customer_id"] == q["customer_id"]]
    if "sale_id" in q:
        items = [l for l in items if l["sale_id"] == q["sale_id"]]
    if "reason" in q:
        items = [l for l in items if l["reason"] == q["reason"]]
    if role == "Customer":
        items = [l for l in items if l["customer_id"] == uid]
    return ok_list(items, ser_ledger)


@app.get("/loyalty-ledger/<lid>")
def get_ledger(lid):
    uid, role = authorize("StoreManager", "Fitter", "Customer")
    entry = get_or_404("ledger", lid, "ERR_LEDGER_ENTRY_NOT_FOUND")
    if role == "Customer" and entry["customer_id"] != uid:
        fail("ERR_UNAUTHORIZED", 403, "Customers may only read their own ledger.")
    return ok(ser_ledger(entry))


# ===========================================================================
# CLOCK
# ===========================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    authorize("StoreManager", "BillingSpecialist", "Fitter")
    b = body_json()
    raw = require_str(b, "to_iso8601")
    try:
        _state["clock"] = parse_dt(raw)
    except ValueError:
        fail("ERR_VALIDATION", 422, "Invalid to_iso8601")
    return ok({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
