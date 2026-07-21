"""Rare & Used Bookstore / Book-Scout API — Flask reference implementation.

In-memory storage only. Boots clean on every process start (no seeding).
"""

import os
import math
import uuid
import random
import string
import itertools
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLE_PATRON = "Patron"
ROLE_APPRAISER = "Appraiser"
ROLE_CLERK = "StoreClerk"
ROLE_MANAGER = "Manager"
ALL_ROLES = {ROLE_PATRON, ROLE_APPRAISER, ROLE_CLERK, ROLE_MANAGER}

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
ACQUISITION_CHANNELS = {"BUYBACK", "CONSIGNMENT", "PURCHASE", "FAIR"}
CONDITION_GRADES = {"POOR", "GOOD", "VERY_GOOD", "FINE", "AS_NEW"}
BASES = {"FAIR_MARKET", "RETAIL_REPLACEMENT"}
FEE_MODELS = {"GROSS_COMMISSION", "NET_COMMISSION"}
SALE_CHANNELS = {"ONLINE", "SHOP"}
ONLINE_STATUSES = {"DRAFT", "LIVE", "SOLD", "DELISTED"}
SHOP_STATUSES = {"DRAFT", "ON_SHELF", "SOLD", "PULLED"}

# ---------------------------------------------------------------------------
# Calculation constants
# ---------------------------------------------------------------------------
CONDITION_MULT = {
    "POOR": Decimal("0.4"),
    "GOOD": Decimal("0.7"),
    "VERY_GOOD": Decimal("1.0"),
    "FINE": Decimal("1.4"),
    "AS_NEW": Decimal("1.8"),
}
FIRST_EDITION_PREMIUM = Decimal("0.5")
RETAIL_MARKUP = Decimal("1.6")
FIRST_EDITION_MAX_PRINTING = 1
AUTO_APPROVE_LIMIT_CENTS = 5000

BASE_CENTS = {1: 500, 2: 800, 3: 1200, 4: 1800}
FREE_WEIGHT_GRAMS = 500
WEIGHT_STEP_GRAMS = 250
PER_STEP_CENTS = 150
CARRIAGE_FLOOR_CENTS = 500
CARRIAGE_CAP_CENTS = 6000
INSURANCE_RATE = Decimal("0.02")
INSURANCE_MIN_CENTS = 200
INSURANCE_CAP_CENTS = 5000
PACK_BUFFER_MINUTES = 15

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
db = {
    "patrons": {},
    "intake_lots": {},
    "book_items": {},
    "appraisals": {},
    "agreements": {},
    "listings": {},
    "offers": {},
    "fairs": {},
    "booth_slots": {},
    "sale_orders": {},
    "shipments": {},
}
_seq = itertools.count(1)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def invalid(msg="Malformed request body"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


# ---------------------------------------------------------------------------
# Helpers: identity / timestamps / envelope
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta(extra=None):
    m = {"api_request_id": req_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok(data, status=200):
    body = {"meta": meta(), "response_type": "object", "data": public(data)}
    return jsonify(body), status


def ok_list(items, pagination=None):
    body = {
        "meta": meta(pagination),
        "response_type": "array",
        "data": [public(i) for i in items],
    }
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------
def create(store, data):
    ts = now_iso()
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq),
    }
    ent.update(data)
    store[ent["id"]] = ent
    return ent


def touch(ent, bump=False):
    ent["updated_at"] = now_iso()
    if bump:
        ent["version"] += 1


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require_auth(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "Missing or invalid user-context headers",
        )
    if role not in allowed_roles:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            403,
            "Role not permitted for this operation",
        )
    g.user_id = user_id
    g.role = role
    return role


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PATCH", "PUT"):
        data = request.get_json(silent=True)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise invalid("Body must be a JSON object")
        return data
    return {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def f_str(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise invalid(f"Missing field: {name}")
        return default
    v = body[name]
    if not isinstance(v, str) or v == "":
        raise invalid(f"Field {name} must be a non-empty string")
    return v


def f_int(body, name, required=True, default=None, min_val=0):
    if name not in body or body[name] is None:
        if required:
            raise invalid(f"Missing field: {name}")
        return default
    v = body[name]
    if not is_int(v) or v < min_val:
        raise invalid(f"Field {name} must be an integer >= {min_val}")
    return v


def f_num(body, name, required=True, default=None, min_val=0):
    if name not in body or body[name] is None:
        if required:
            raise invalid(f"Missing field: {name}")
        return default
    v = body[name]
    if not is_num(v) or v < min_val:
        raise invalid(f"Field {name} must be a number >= {min_val}")
    return v


def f_bool(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise invalid(f"Missing field: {name}")
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise invalid(f"Field {name} must be a boolean")
    return v


def f_enum(body, name, allowed, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise invalid(f"Missing field: {name}")
        return default
    v = body[name]
    if v not in allowed:
        raise invalid(f"Field {name} not in allowed set")
    return v


# ---------------------------------------------------------------------------
# Lookup helpers (path / FK existence)
# ---------------------------------------------------------------------------
def lookup(store, ident, err_id):
    ent = store.get(ident)
    if ent is None:
        raise ApiError(err_id, 404, "Resource not found")
    return ent


def fk_exists(store, ident, err_id):
    """Validate a body FK reference (non-null) exists; return the entity."""
    if not isinstance(ident, str) or ident not in store:
        raise ApiError(err_id, 404, "Referenced resource not found")
    return store[ident]


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def rhu(dec_value):
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def D(x):
    return Decimal(str(x))


def parse_dt(s, err=None):
    if not isinstance(s, str):
        raise err or invalid("datetime must be a string")
    t = s.strip()
    try:
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
    except (ValueError, TypeError):
        raise err or invalid("Invalid datetime")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (ValueError, TypeError):
            raise invalid("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid("limit out of range")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (ValueError, TypeError):
            raise invalid("offset must be an integer")
        if offset < 0:
            raise invalid("offset out of range")
    return limit, offset


def page_and_meta(items):
    """items: already-filtered list. Sorts by creation order, paginates."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    window = ordered[offset:offset + limit]
    pg = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return window, pg


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
def push_provenance(book, event_type, note=None):
    book["provenance"].append(
        {
            "event_type": event_type,
            "note": note,
            "actor_role": getattr(g, "role", None),
            "at": now_iso(),
        }
    )


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def compute_appraisal_values(book):
    cm = D(book["comp_median_cents"])
    cmult = CONDITION_MULT[book["condition_grade"]]
    prem = FIRST_EDITION_PREMIUM if book["is_first_edition"] else Decimal("0")
    factor = cmult * (Decimal("1") + prem)
    fair = rhu(cm * factor)
    retail = rhu(cm * RETAIL_MARKUP * factor)
    return fair, retail


def compute_consignment_payout(agreement, sale_price_cents):
    sp = D(sale_price_cents)
    cp = D(agreement["commission_pct"])
    if agreement["fee_model"] == "NET_COMMISSION":
        ff = D(agreement["flat_fee_cents"])
        return rhu((sp - ff) * (Decimal("1") - cp))
    return rhu(sp * (Decimal("1") - cp))


def compute_order_totals(line_items, tax_pct, store_credit_applied):
    tax = D(tax_pct)
    subtotal = 0
    for li in line_items:
        sp = D(li["sale_price_cents"])
        disc = D(li.get("discount_pct", 0))
        net = sp * (Decimal("1") - disc)
        taxed = net * (Decimal("1") + tax)
        subtotal += rhu(taxed)
    total = max(0, subtotal - store_credit_applied)
    return subtotal, total


def compute_shipping_cost(weight_grams, zone, declared_value_cents, insured):
    base = BASE_CENTS[zone]
    billable_over = max(0, weight_grams - FREE_WEIGHT_GRAMS)
    steps = math.ceil(billable_over / WEIGHT_STEP_GRAMS)
    carriage = base + steps * PER_STEP_CENTS
    carriage = min(CARRIAGE_CAP_CENTS, max(CARRIAGE_FLOOR_CENTS, carriage))
    if insured:
        insurance = rhu(D(declared_value_cents) * INSURANCE_RATE)
        insurance = min(INSURANCE_CAP_CENTS, max(INSURANCE_MIN_CENTS, insurance))
    else:
        insurance = 0
    return carriage + insurance


def agreement_for_book(book_id):
    for a in db["agreements"].values():
        if a["book_item_id"] == book_id:
            return a
    return None


def listing_for_book(book_id):
    for l in db["listings"].values():
        if l["book_item_id"] == book_id:
            return l
    return None


# ===========================================================================
# PATRONS
# ===========================================================================
@app.route("/patrons", methods=["POST"])
def create_patron():
    require_auth({ROLE_CLERK, ROLE_MANAGER})
    body = get_body()
    display_name = f_str(body, "display_name")
    email = f_str(body, "email")
    commission = f_num(body, "default_commission_pct", required=False, default=0.30)
    # duplicate email (priority 13)
    for p in db["patrons"].values():
        if p["email"] == email:
            raise ApiError("ERR_DUPLICATE_EMAIL", 409, "Email already registered")
    patron = create(
        db["patrons"],
        {
            "display_name": display_name,
            "email": email,
            "default_commission_pct": commission,
            "store_credit_cents": 0,
            "consignor_payable_cents": 0,
            "status": "ACTIVE",
        },
    )
    return ok(patron, 201)


@app.route("/patrons/<pid>", methods=["GET"])
def get_patron(pid):
    require_auth(ALL_ROLES)
    patron = lookup(db["patrons"], pid, "ERR_PATRON_NOT_FOUND")
    return ok(patron)


# ===========================================================================
# INTAKE LOTS
# ===========================================================================
@app.route("/intake-lots", methods=["POST"])
def create_intake_lot():
    require_auth({ROLE_CLERK, ROLE_MANAGER})
    body = get_body()
    consignor_id = body.get("consignor_id")
    if consignor_id is not None:
        fk_exists(db["patrons"], consignor_id, "ERR_PATRON_NOT_FOUND")
    channel = f_enum(body, "acquisition_channel", ACQUISITION_CHANNELS)
    lot = create(
        db["intake_lots"],
        {
            "consignor_id": consignor_id,
            "acquisition_channel": channel,
            "item_count": 0,
            "status": "DRAFT",
        },
    )
    return ok(lot, 201)


@app.route("/intake-lots/<lid>", methods=["GET"])
def get_intake_lot(lid):
    require_auth(ALL_ROLES)
    lot = lookup(db["intake_lots"], lid, "ERR_INTAKE_LOT_NOT_FOUND")
    return ok(lot)


@app.route("/intake-lots/<lid>/book-items", methods=["POST"])
def intake_book_item(lid):
    require_auth({ROLE_CLERK})
    lot = lookup(db["intake_lots"], lid, "ERR_INTAKE_LOT_NOT_FOUND")
    body = get_body()
    title = f_str(body, "title")
    author = f_str(body, "author")
    comp_median = f_int(body, "comp_median_cents")
    printing = f_int(body, "printing_number", required=False, default=1)
    stated_fe = f_bool(body, "stated_first_edition", required=False, default=False)
    if lot["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Lot is not in DRAFT")
    book = create(
        db["book_items"],
        {
            "intake_lot_id": lid,
            "consignor_id": lot["consignor_id"],
            "title": title,
            "author": author,
            "printing_number": printing,
            "stated_first_edition": stated_fe,
            "comp_median_cents": comp_median,
            "condition_grade": None,
            "is_first_edition": False,
            "appraised_value_cents": None,
            "provenance": [],
            "status": "INTAKE",
        },
    )
    push_provenance(book, "INTAKE")
    lot["item_count"] += 1
    touch(lot)
    return ok(book, 201)


@app.route("/intake-lots/<lid>/settle", methods=["POST"])
def settle_intake_lot(lid):
    require_auth({ROLE_MANAGER})
    lot = lookup(db["intake_lots"], lid, "ERR_INTAKE_LOT_NOT_FOUND")
    if lot["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Lot is not in DRAFT")
    items = [b for b in db["book_items"].values() if b["intake_lot_id"] == lid]
    if len(items) < 1:
        raise ApiError("ERR_EMPTY_LOT", 409, "Lot has no book items")
    if any(b["status"] != "APPRAISED" for b in items):
        raise ApiError(
            "ERR_LOT_ITEMS_NOT_APPRAISED", 409, "All items must be APPRAISED"
        )
    lot["status"] = "SETTLED"
    touch(lot)
    return ok(lot)


@app.route("/intake-lots/<lid>/reject", methods=["POST"])
def reject_intake_lot(lid):
    require_auth({ROLE_MANAGER})
    lot = lookup(db["intake_lots"], lid, "ERR_INTAKE_LOT_NOT_FOUND")
    if lot["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Lot is not in DRAFT")
    lot["status"] = "REJECTED"
    touch(lot)
    # cascade hop 1: non-SOLD book items -> WITHDRAWN
    items = [b for b in db["book_items"].values() if b["intake_lot_id"] == lid]
    for book in items:
        if book["status"] == "SOLD":
            continue
        book["status"] = "WITHDRAWN"
        # cascade hop 2: void ISSUED appraisals + clear appraised value
        for ap in db["appraisals"].values():
            if ap["book_item_id"] == book["id"] and ap["status"] == "ISSUED":
                ap["status"] = "VOIDED"
                touch(ap)
        book["appraised_value_cents"] = None
        push_provenance(book, "WITHDRAWN")
        touch(book)
    return ok(lot)


# ===========================================================================
# BOOK ITEMS
# ===========================================================================
@app.route("/book-items/<bid>", methods=["GET"])
def get_book_item(bid):
    require_auth(ALL_ROLES)
    book = lookup(db["book_items"], bid, "ERR_BOOK_ITEM_NOT_FOUND")
    return ok(book)


@app.route("/book-items", methods=["GET"])
def list_book_items():
    require_auth(ALL_ROLES)
    items = list(db["book_items"].values())
    lot = request.args.get("intake_lot_id")
    consignor = request.args.get("consignor_id")
    status = request.args.get("status")
    if lot is not None:
        items = [b for b in items if b["intake_lot_id"] == lot]
    if consignor is not None:
        items = [b for b in items if b["consignor_id"] == consignor]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    window, pg = page_and_meta(items)
    return ok_list(window, pg)


@app.route("/book-items/<bid>/grade", methods=["POST"])
def grade_book_item(bid):
    require_auth({ROLE_APPRAISER})
    book = lookup(db["book_items"], bid, "ERR_BOOK_ITEM_NOT_FOUND")
    body = get_body()
    grade = f_enum(body, "condition_grade", CONDITION_GRADES)
    if book["status"] != "INTAKE":
        raise ApiError("ERR_ITEM_NOT_GRADED", 409, "Item is not in INTAKE")
    book["condition_grade"] = grade
    book["is_first_edition"] = bool(
        book["stated_first_edition"]
        and book["printing_number"] <= FIRST_EDITION_MAX_PRINTING
    )
    book["status"] = "GRADED"
    push_provenance(book, "GRADED")
    touch(book)
    return ok(book)


@app.route("/book-items/<bid>/appraisals", methods=["POST"])
def create_appraisal(bid):
    require_auth({ROLE_APPRAISER})
    book = lookup(db["book_items"], bid, "ERR_BOOK_ITEM_NOT_FOUND")
    body = get_body()
    basis = f_enum(body, "basis", BASES)
    expected = f_int(body, "expected_book_item_version")
    # state (priority 6)
    if book["status"] not in ("GRADED", "APPRAISED"):
        raise ApiError("ERR_ITEM_NOT_GRADED", 409, "Item is not GRADED")
    # OCC (priority 15)
    if expected != book["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale book item version")

    fair, retail = compute_appraisal_values(book)
    final = fair if basis == "FAIR_MARKET" else retail
    # supersede prior ISSUED appraisal
    for ap in db["appraisals"].values():
        if ap["book_item_id"] == bid and ap["status"] == "ISSUED":
            ap["status"] = "SUPERSEDED"
            touch(ap)
    appraisal = create(
        db["appraisals"],
        {
            "book_item_id": bid,
            "basis": basis,
            "fair_market_value_cents": fair,
            "retail_replacement_value_cents": retail,
            "final_value_cents": final,
            "status": "ISSUED",
        },
    )
    first_issue = book["status"] == "GRADED"
    book["status"] = "APPRAISED"
    book["appraised_value_cents"] = final
    if first_issue:
        push_provenance(book, "APPRAISED")
    touch(book, bump=True)
    return ok(appraisal, 201)


@app.route("/book-items/<bid>/appraisals", methods=["GET"])
def list_appraisals(bid):
    require_auth(ALL_ROLES)
    lookup(db["book_items"], bid, "ERR_BOOK_ITEM_NOT_FOUND")
    items = [a for a in db["appraisals"].values() if a["book_item_id"] == bid]
    window, pg = page_and_meta(items)
    return ok_list(window, pg)


@app.route("/book-items/<bid>/listing", methods=["POST"])
def create_listing(bid):
    require_auth({ROLE_CLERK})
    book = lookup(db["book_items"], bid, "ERR_BOOK_ITEM_NOT_FOUND")
    body = get_body()
    list_price = f_int(body, "list_price_cents")
    if listing_for_book(bid) is not None:
        raise ApiError("ERR_DUPLICATE_LISTING", 409, "Book already has a listing")
    if book["status"] != "APPRAISED":
        raise ApiError("ERR_ITEM_NOT_APPRAISED", 409, "Item is not APPRAISED")
    listing = create(
        db["listings"],
        {
            "book_item_id": bid,
            "list_price_cents": list_price,
            "online_status": "DRAFT",
            "shop_status": "DRAFT",
            "sold_channel": None,
        },
    )
    book["status"] = "LISTED"
    push_provenance(book, "LISTED")
    touch(book)
    return ok(listing, 201)


@app.route("/book-items/<bid>/listing", methods=["GET"])
def get_listing(bid):
    require_auth(ALL_ROLES)
    lookup(db["book_items"], bid, "ERR_BOOK_ITEM_NOT_FOUND")
    listing = listing_for_book(bid)
    items = [listing] if listing is not None else []
    return ok_list(items)


# ===========================================================================
# CONSIGNMENT AGREEMENTS
# ===========================================================================
@app.route("/consignment-agreements", methods=["POST"])
def create_agreement():
    require_auth({ROLE_MANAGER})
    body = get_body()
    patron_id = body.get("patron_id")
    book_item_id = body.get("book_item_id")
    # FK existence (priority 4)
    if patron_id is None:
        raise invalid("Missing field: patron_id")
    patron = fk_exists(db["patrons"], patron_id, "ERR_PATRON_NOT_FOUND")
    if book_item_id is None:
        raise invalid("Missing field: book_item_id")
    fk_exists(db["book_items"], book_item_id, "ERR_BOOK_ITEM_NOT_FOUND")
    # body wellformed (priority 5)
    commission = f_num(body, "commission_pct", required=False, default=None)
    if commission is None:
        commission = patron["default_commission_pct"]
    fee_model = f_enum(body, "fee_model", FEE_MODELS, required=False,
                       default="GROSS_COMMISSION")
    flat_fee = f_int(body, "flat_fee_cents", required=False, default=0)
    # duplicate (priority 14)
    if agreement_for_book(book_item_id) is not None:
        raise ApiError("ERR_DUPLICATE_LISTING", 409, "Book already has an agreement")
    agreement = create(
        db["agreements"],
        {
            "patron_id": patron_id,
            "book_item_id": book_item_id,
            "commission_pct": commission,
            "fee_model": fee_model,
            "flat_fee_cents": flat_fee,
            "amendment_no": 0,
            "status": "PROPOSED",
        },
    )
    return ok(agreement, 201)


@app.route("/consignment-agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    require_auth(ALL_ROLES)
    agreement = lookup(db["agreements"], aid, "ERR_AGREEMENT_NOT_FOUND")
    return ok(agreement)


@app.route("/consignment-agreements", methods=["GET"])
def list_agreements():
    require_auth(ALL_ROLES)
    items = list(db["agreements"].values())
    patron_id = request.args.get("patron_id")
    book_item_id = request.args.get("book_item_id")
    status = request.args.get("status")
    if patron_id is not None:
        items = [a for a in items if a["patron_id"] == patron_id]
    if book_item_id is not None:
        items = [a for a in items if a["book_item_id"] == book_item_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    window, pg = page_and_meta(items)
    return ok_list(window, pg)


@app.route("/consignment-agreements/<aid>/amend", methods=["POST"])
def amend_agreement(aid):
    require_auth({ROLE_MANAGER})
    agreement = lookup(db["agreements"], aid, "ERR_AGREEMENT_NOT_FOUND")
    body = get_body()
    expected = f_int(body, "expected_consignment_agreement_version")
    commission = f_num(body, "commission_pct", required=False, default=None)
    fee_model = f_enum(body, "fee_model", FEE_MODELS, required=False, default=None)
    flat_fee = f_int(body, "flat_fee_cents", required=False, default=None)
    # state (priority 6)
    if agreement["status"] not in ("PROPOSED", "AMENDED"):
        raise ApiError(
            "ERR_AGREEMENT_NOT_AMENDABLE", 409, "Agreement is not amendable"
        )
    # OCC (priority 15)
    if expected != agreement["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale agreement version")
    if commission is not None:
        agreement["commission_pct"] = commission
    if fee_model is not None:
        agreement["fee_model"] = fee_model
    if flat_fee is not None:
        agreement["flat_fee_cents"] = flat_fee
    agreement["status"] = "AMENDED"
    agreement["amendment_no"] += 1
    touch(agreement, bump=True)
    return ok(agreement)


@app.route("/consignment-agreements/<aid>/activate", methods=["POST"])
def activate_agreement(aid):
    require_auth({ROLE_MANAGER})
    agreement = lookup(db["agreements"], aid, "ERR_AGREEMENT_NOT_FOUND")
    if agreement["status"] not in ("PROPOSED", "AMENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement cannot be activated")
    book = db["book_items"].get(agreement["book_item_id"])
    if book is None or book["status"] not in ("APPRAISED", "LISTED"):
        raise ApiError(
            "ERR_ITEM_NOT_APPRAISED", 409, "Book is not APPRAISED/LISTED"
        )
    agreement["status"] = "ACTIVE"
    touch(agreement)
    push_provenance(book, "CONSIGNED")
    touch(book)
    return ok(agreement)


# ===========================================================================
# CATALOG LISTINGS
# ===========================================================================
@app.route("/catalog-listings/<cid>", methods=["PATCH"])
def patch_listing(cid):
    require_auth({ROLE_CLERK})
    listing = lookup(db["listings"], cid, "ERR_LISTING_NOT_FOUND")
    body = get_body()
    expected = f_int(body, "expected_catalog_listing_version")
    list_price = f_int(body, "list_price_cents", required=False, default=None)
    online = f_enum(body, "online_status", ONLINE_STATUSES, required=False, default=None)
    shop = f_enum(body, "shop_status", SHOP_STATUSES, required=False, default=None)
    # state legality (priority 6): only clerk-driven axis advances are allowed
    if online is not None and online != listing["online_status"]:
        if not (listing["online_status"] == "DRAFT" and online == "LIVE"):
            raise ApiError("ERR_INVALID_STATE", 409, "Illegal online_status change")
    if shop is not None and shop != listing["shop_status"]:
        if not (listing["shop_status"] == "DRAFT" and shop == "ON_SHELF"):
            raise ApiError("ERR_INVALID_STATE", 409, "Illegal shop_status change")
    # OCC (priority 15)
    if expected != listing["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale listing version")
    if list_price is not None:
        listing["list_price_cents"] = list_price
    if online is not None:
        listing["online_status"] = online
    if shop is not None:
        listing["shop_status"] = shop
    touch(listing, bump=True)
    return ok(listing)


# ===========================================================================
# BUYBACK OFFERS
# ===========================================================================
@app.route("/buyback-offers", methods=["POST"])
def create_offer():
    require_auth({ROLE_CLERK, ROLE_MANAGER})
    body = get_body()
    patron_id = body.get("patron_id")
    book_item_id = body.get("book_item_id")
    # FK existence (priority 4)
    if patron_id is None:
        raise invalid("Missing field: patron_id")
    fk_exists(db["patrons"], patron_id, "ERR_PATRON_NOT_FOUND")
    if book_item_id is not None:
        fk_exists(db["book_items"], book_item_id, "ERR_BOOK_ITEM_NOT_FOUND")
    # body wellformed (priority 5)
    offer_value = f_int(body, "offer_value_cents")
    auto = offer_value <= AUTO_APPROVE_LIMIT_CENTS
    offer = create(
        db["offers"],
        {
            "patron_id": patron_id,
            "book_item_id": book_item_id,
            "offer_value_cents": offer_value,
            "credit_amount_cents": 0,
            "auto_approved": auto,
            "status": "AUTO_APPROVED" if auto else "PENDING",
        },
    )
    return ok(offer, 201)


@app.route("/buyback-offers/<oid>", methods=["GET"])
def get_offer(oid):
    require_auth(ALL_ROLES)
    offer = lookup(db["offers"], oid, "ERR_OFFER_NOT_FOUND")
    return ok(offer)


@app.route("/buyback-offers", methods=["GET"])
def list_offers():
    require_auth(ALL_ROLES)
    items = list(db["offers"].values())
    patron_id = request.args.get("patron_id")
    book_item_id = request.args.get("book_item_id")
    status = request.args.get("status")
    if patron_id is not None:
        items = [o for o in items if o["patron_id"] == patron_id]
    if book_item_id is not None:
        items = [o for o in items if o["book_item_id"] == book_item_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    window, pg = page_and_meta(items)
    return ok_list(window, pg)


@app.route("/buyback-offers/<oid>/accept", methods=["POST"])
def accept_offer(oid):
    require_auth({ROLE_MANAGER})
    offer = lookup(db["offers"], oid, "ERR_OFFER_NOT_FOUND")
    if offer["status"] not in ("PENDING", "AUTO_APPROVED"):
        raise ApiError("ERR_OFFER_NOT_ACCEPTABLE", 409, "Offer is not acceptable")
    offer["status"] = "ACCEPTED"
    offer["credit_amount_cents"] = offer["offer_value_cents"]
    patron = db["patrons"].get(offer["patron_id"])
    if patron is not None:
        patron["store_credit_cents"] += offer["credit_amount_cents"]
        touch(patron)
    if offer["book_item_id"] is not None:
        book = db["book_items"].get(offer["book_item_id"])
        if book is not None:
            push_provenance(book, "BUYBACK")
            touch(book)
    touch(offer)
    return ok(offer)


@app.route("/buyback-offers/<oid>/void", methods=["POST"])
def void_offer(oid):
    require_auth({ROLE_MANAGER})
    offer = lookup(db["offers"], oid, "ERR_OFFER_NOT_FOUND")
    if offer["status"] != "ACCEPTED":
        raise ApiError("ERR_OFFER_NOT_VOIDABLE", 409, "Offer is not voidable")
    patron = db["patrons"].get(offer["patron_id"])
    available = patron["store_credit_cents"] if patron is not None else 0
    if available < offer["credit_amount_cents"]:
        raise ApiError("ERR_CREDIT_ALREADY_SPENT", 402, "Credit already spent")
    offer["status"] = "VOIDED"
    if patron is not None:
        patron["store_credit_cents"] -= offer["credit_amount_cents"]
        touch(patron)
    touch(offer)
    return ok(offer)


# ===========================================================================
# FAIR EVENTS / BOOTH SLOTS
# ===========================================================================
@app.route("/fair-events", methods=["POST"])
def create_fair():
    require_auth({ROLE_MANAGER})
    body = get_body()
    name = f_str(body, "name")
    capacity = f_int(body, "table_capacity")
    fair = create(
        db["fairs"],
        {"name": name, "table_capacity": capacity, "reserved_display_count": 0},
    )
    return ok(fair, 201)


@app.route("/fair-events/<fid>", methods=["GET"])
def get_fair(fid):
    require_auth(ALL_ROLES)
    fair = lookup(db["fairs"], fid, "ERR_FAIR_NOT_FOUND")
    return ok(fair)


@app.route("/fair-events/<fid>/booth-slots", methods=["POST"])
def create_booth_slot(fid):
    require_auth({ROLE_CLERK, ROLE_MANAGER})
    fair = lookup(db["fairs"], fid, "ERR_FAIR_NOT_FOUND")
    body = get_body()
    booth_table = f_str(body, "booth_table")
    ws_raw = body.get("window_start")
    we_raw = body.get("window_end")
    if ws_raw is None or we_raw is None:
        raise invalid("window_start and window_end are required")
    display_count = f_int(body, "display_item_count", required=False, default=1)
    win_err = ApiError("ERR_INVALID_WINDOW", 400, "Invalid window")
    ws = parse_dt(ws_raw, win_err)
    we = parse_dt(we_raw, win_err)
    if not (we > ws):
        raise win_err
    existing = [b for b in db["booth_slots"].values() if b["fair_event_id"] == fid]
    # overlap on same booth_table (priority 8)
    for e in existing:
        if e["booth_table"] != booth_table:
            continue
        if e["_ws"] < we and ws < e["_we"]:
            raise ApiError("ERR_BOOTH_SLOT_CONFLICT", 409, "Booth slot overlap")
    # aggregate capacity over overlapping windows (priority 9)
    overlap_sum = 0
    for e in existing:
        if e["_ws"] < we and ws < e["_we"]:
            overlap_sum += e["display_item_count"]
    if overlap_sum + display_count > fair["table_capacity"]:
        raise ApiError("ERR_FAIR_CAPACITY_EXCEEDED", 409, "Fair capacity exceeded")
    slot = create(
        db["booth_slots"],
        {
            "fair_event_id": fid,
            "booth_table": booth_table,
            "window_start": ws_raw,
            "window_end": we_raw,
            "display_item_count": display_count,
            "status": "RESERVED",
            "_ws": ws,
            "_we": we,
        },
    )
    fair["reserved_display_count"] = sum(
        b["display_item_count"]
        for b in db["booth_slots"].values()
        if b["fair_event_id"] == fid
    )
    touch(fair)
    return ok(slot, 201)


@app.route("/fair-events/<fid>/booth-slots", methods=["GET"])
def list_booth_slots(fid):
    require_auth(ALL_ROLES)
    lookup(db["fairs"], fid, "ERR_FAIR_NOT_FOUND")
    items = [b for b in db["booth_slots"].values() if b["fair_event_id"] == fid]
    window, pg = page_and_meta(items)
    return ok_list(window, pg)


# ===========================================================================
# SALE ORDERS / SHIPMENTS
# ===========================================================================
def validate_line_items(raw):
    if not isinstance(raw, list):
        raise invalid("line_items must be an array")
    normalized = []
    for li in raw:
        if not isinstance(li, dict):
            raise invalid("line_item must be an object")
        book_id = li.get("book_item_id")
        # FK existence (priority 4)
        fk_exists(db["book_items"], book_id, "ERR_BOOK_ITEM_NOT_FOUND")
        sale_price = li.get("sale_price_cents")
        if not is_int(sale_price) or sale_price < 0:
            raise invalid("sale_price_cents must be a non-negative integer")
        discount = li.get("discount_pct", 0)
        if not is_num(discount) or discount < 0:
            raise invalid("discount_pct must be a non-negative number")
        normalized.append(
            {
                "book_item_id": book_id,
                "sale_price_cents": sale_price,
                "discount_pct": discount,
            }
        )
    return normalized


@app.route("/sale-orders", methods=["POST"])
def create_sale_order():
    require_auth({ROLE_CLERK, ROLE_MANAGER})
    body = get_body()
    buyer_id = body.get("buyer_patron_id")
    # FK existence (priority 4)
    if buyer_id is not None:
        fk_exists(db["patrons"], buyer_id, "ERR_PATRON_NOT_FOUND")
    if "line_items" not in body or body["line_items"] is None:
        raise invalid("line_items is required")
    line_items = validate_line_items(body["line_items"])
    # body wellformed (priority 5)
    channel = f_enum(body, "channel", SALE_CHANNELS)
    tax_pct = f_num(body, "tax_pct", required=False, default=0.08)
    store_credit_applied = f_int(
        body, "store_credit_applied_cents", required=False, default=0
    )
    subtotal, total = compute_order_totals(line_items, tax_pct, store_credit_applied)
    order = create(
        db["sale_orders"],
        {
            "buyer_patron_id": buyer_id,
            "channel": channel,
            "line_items": line_items,
            "tax_pct": tax_pct,
            "store_credit_applied_cents": store_credit_applied,
            "subtotal_cents": subtotal,
            "total_cents": total,
            "status": "DRAFT",
        },
    )
    return ok(order, 201)


@app.route("/sale-orders/<sid>", methods=["GET"])
def get_sale_order(sid):
    require_auth(ALL_ROLES)
    order = lookup(db["sale_orders"], sid, "ERR_ORDER_NOT_FOUND")
    return ok(order)


@app.route("/sale-orders/<sid>/confirm", methods=["POST"])
def confirm_sale_order(sid):
    require_auth({ROLE_MANAGER})
    order = lookup(db["sale_orders"], sid, "ERR_ORDER_NOT_FOUND")
    # state (priority 6)
    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not in DRAFT")
    line_items = order["line_items"]
    if not line_items:
        raise ApiError("ERR_EMPTY_ORDER", 409, "Order has no line items")
    books = []
    for li in line_items:
        book = db["book_items"].get(li["book_item_id"])
        if book is None or book["status"] != "LISTED":
            raise ApiError("ERR_ITEM_NOT_LISTED", 409, "Item is not LISTED")
        books.append(book)
    # business_referential (priority 7): consigned items' agreement must be ACTIVE
    for li in line_items:
        agreement = agreement_for_book(li["book_item_id"])
        if agreement is not None and agreement["status"] != "ACTIVE":
            raise ApiError(
                "ERR_CONSIGNMENT_NOT_ACTIVE", 409, "Consignment not ACTIVE"
            )
    # fiscal (priority 11): store credit sufficiency
    applied = order["store_credit_applied_cents"]
    buyer = db["patrons"].get(order["buyer_patron_id"]) if order["buyer_patron_id"] else None
    available = buyer["store_credit_cents"] if buyer is not None else 0
    if applied > available:
        raise ApiError(
            "ERR_INSUFFICIENT_STORE_CREDIT", 402, "Insufficient store credit"
        )

    # --- all checks passed: recompute totals + apply cascade atomically ---
    subtotal, total = compute_order_totals(
        line_items, order["tax_pct"], applied
    )
    order["subtotal_cents"] = subtotal
    order["total_cents"] = total

    cascade = []
    channel = order["channel"]
    for li in line_items:
        book = db["book_items"][li["book_item_id"]]
        book["status"] = "SOLD"
        push_provenance(book, "SOLD")
        listing = listing_for_book(book["id"])
        rec = {
            "book_id": book["id"],
            "listing_id": listing["id"] if listing else None,
            "prev_online": None,
            "prev_shop": None,
            "prev_sold_channel": None,
            "agreement_id": None,
            "payout": 0,
            "consignor_patron_id": None,
        }
        if listing is not None:
            rec["prev_online"] = listing["online_status"]
            rec["prev_shop"] = listing["shop_status"]
            rec["prev_sold_channel"] = listing["sold_channel"]
            if channel == "ONLINE":
                listing["online_status"] = "SOLD"
                listing["sold_channel"] = "ONLINE"
                listing["shop_status"] = "PULLED"
            else:
                listing["shop_status"] = "SOLD"
                listing["sold_channel"] = "SHOP"
                listing["online_status"] = "DELISTED"
            touch(listing)
        agreement = agreement_for_book(book["id"])
        if agreement is not None and agreement["status"] == "ACTIVE":
            payout = compute_consignment_payout(agreement, li["sale_price_cents"])
            agreement["status"] = "SETTLED"
            touch(agreement)
            consignor = db["patrons"].get(agreement["patron_id"])
            if consignor is not None:
                consignor["consignor_payable_cents"] += payout
                touch(consignor)
            rec["agreement_id"] = agreement["id"]
            rec["payout"] = payout
            rec["consignor_patron_id"] = agreement["patron_id"]
        touch(book)
        cascade.append(rec)

    if buyer is not None and applied:
        buyer["store_credit_cents"] -= applied
        touch(buyer)

    order["_cascade"] = cascade
    order["status"] = "CONFIRMED"
    touch(order)
    return ok(order)


@app.route("/sale-orders/<sid>/refund", methods=["POST"])
def refund_sale_order(sid):
    require_auth({ROLE_MANAGER})
    order = lookup(db["sale_orders"], sid, "ERR_ORDER_NOT_FOUND")
    if order["status"] != "CONFIRMED":
        raise ApiError("ERR_ORDER_NOT_CONFIRMED", 409, "Order is not CONFIRMED")

    for rec in order.get("_cascade", []):
        book = db["book_items"].get(rec["book_id"])
        if book is not None:
            book["status"] = "LISTED"
            touch(book)
        if rec["listing_id"] is not None:
            listing = db["listings"].get(rec["listing_id"])
            if listing is not None:
                listing["online_status"] = rec["prev_online"]
                listing["shop_status"] = rec["prev_shop"]
                listing["sold_channel"] = rec["prev_sold_channel"]
                touch(listing)
        if rec["agreement_id"] is not None:
            agreement = db["agreements"].get(rec["agreement_id"])
            if agreement is not None:
                agreement["status"] = "ACTIVE"
                touch(agreement)
            consignor = db["patrons"].get(rec["consignor_patron_id"])
            if consignor is not None:
                consignor["consignor_payable_cents"] -= rec["payout"]
                touch(consignor)

    applied = order["store_credit_applied_cents"]
    buyer = db["patrons"].get(order["buyer_patron_id"]) if order["buyer_patron_id"] else None
    if buyer is not None and applied:
        buyer["store_credit_cents"] += applied
        touch(buyer)

    order["status"] = "REFUNDED"
    order["_cascade"] = []
    touch(order)
    return ok(order)


@app.route("/sale-orders/<sid>/shipment", methods=["POST"])
def create_shipment(sid):
    require_auth({ROLE_CLERK})
    order = lookup(db["sale_orders"], sid, "ERR_ORDER_NOT_FOUND")
    body = get_body()
    station = f_str(body, "packing_station_label")
    weight = f_int(body, "weight_grams")
    zone = body.get("zone")
    if not is_int(zone) or zone not in BASE_CENTS:
        raise invalid("zone must be an integer 1..4")
    declared = f_int(body, "declared_value_cents", required=False, default=0)
    insured = f_bool(body, "insured", required=False, default=False)
    ps_raw = body.get("pack_start")
    pe_raw = body.get("pack_end")
    if ps_raw is None or pe_raw is None:
        raise invalid("pack_start and pack_end are required")
    win_err = ApiError("ERR_INVALID_WINDOW", 400, "Invalid window")
    ps = parse_dt(ps_raw, win_err)
    pe = parse_dt(pe_raw, win_err)
    if not (pe > ps):
        raise win_err
    # packing buffer (priority 10)
    buffer = _minutes(PACK_BUFFER_MINUTES)
    for e in db["shipments"].values():
        if e["packing_station_label"] != station:
            continue
        clear = (ps >= _add_min(e["_pe"], PACK_BUFFER_MINUTES)) or (
            e["_ps"] >= _add_min(pe, PACK_BUFFER_MINUTES)
        )
        if not clear:
            raise ApiError("ERR_PACKING_SLOT_CONFLICT", 409, "Packing slot conflict")
    cost = compute_shipping_cost(weight, zone, declared, insured)
    shipment = create(
        db["shipments"],
        {
            "sale_order_id": sid,
            "packing_station_label": station,
            "weight_grams": weight,
            "zone": zone,
            "declared_value_cents": declared,
            "insured": insured,
            "pack_start": ps_raw,
            "pack_end": pe_raw,
            "shipping_cost_cents": cost,
            "status": "PACKED",
            "_ps": ps,
            "_pe": pe,
        },
    )
    return ok(shipment, 201)


@app.route("/sale-orders/<sid>/shipment", methods=["GET"])
def get_shipment(sid):
    require_auth(ALL_ROLES)
    lookup(db["sale_orders"], sid, "ERR_ORDER_NOT_FOUND")
    items = [s for s in db["shipments"].values() if s["sale_order_id"] == sid]
    items = sorted(items, key=lambda e: e["_seq"])
    return ok_list(items)


# ---------------------------------------------------------------------------
# datetime buffer helpers
# ---------------------------------------------------------------------------
def _add_min(dt, minutes):
    return dt + timedelta(minutes=minutes)


def _minutes(minutes):
    return timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
