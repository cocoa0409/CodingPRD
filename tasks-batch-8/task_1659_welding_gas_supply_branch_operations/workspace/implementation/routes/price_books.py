"""Contract price books: create (DRAFT), activate with window-exclusion, reads."""
from flask import Blueprint

import db
from db import store, new_common, new_id, touch, is_num, is_int, parse_dt
from errors import ApiError
from middleware import require_roles, body
from response import ok, created, list_response, filter_param

bp = Blueprint("price_books", __name__)


def get_book(bid):
    book = store.price_books.get(bid)
    if book is None:
        raise ApiError("ERR_NOT_FOUND", 404, "PriceBook not found")
    return book


@bp.route("/price-books", methods=["POST"])
@require_roles("BranchManager")
def create_book():
    b = body()
    # Priority 3: body-referenced customer must exist.
    cust_id = b.get("customer_id")
    if cust_id is not None and cust_id not in store.customers:
        raise ApiError("ERR_NOT_FOUND", 404, "Customer not found")
    # Priority 4: shape.
    name = b.get("name")
    scope = b.get("scope")
    discount = b.get("default_discount_pct")
    tiers = b.get("volume_tiers", [])
    if not isinstance(name, str) or not name:
        raise ApiError("ERR_VALIDATION", 400, "name is required")
    if scope not in ("RETAIL", "CONTRACT"):
        raise ApiError("ERR_VALIDATION", 400, "scope must be RETAIL or CONTRACT")
    if scope == "CONTRACT" and cust_id is None:
        raise ApiError("ERR_VALIDATION", 400, "customer_id is required for CONTRACT books")
    if scope == "RETAIL" and cust_id is not None:
        raise ApiError("ERR_VALIDATION", 400, "customer_id must be null for RETAIL books")
    if cust_id is not None and not isinstance(cust_id, str):
        raise ApiError("ERR_VALIDATION", 400, "customer_id must be a string or null")
    try:
        eff_from = parse_dt(b.get("effective_from"))
        eff_to = parse_dt(b.get("effective_to"))
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400,
                       "effective_from and effective_to must be ISO 8601 datetimes")
    if not eff_from < eff_to:
        raise ApiError("ERR_VALIDATION", 400, "effective_from must be earlier than effective_to")
    if not is_num(discount) or not (0 <= discount <= 0.90):
        raise ApiError("ERR_VALIDATION", 400,
                       "default_discount_pct must be a number in [0, 0.90]")
    if not isinstance(tiers, list):
        raise ApiError("ERR_VALIDATION", 400, "volume_tiers must be an array")
    clean_tiers = []
    for t in tiers:
        if not isinstance(t, dict) or not is_int(t.get("min_qty")) or t["min_qty"] < 1 \
                or not is_num(t.get("extra_discount_pct")):
            raise ApiError("ERR_VALIDATION", 400,
                           "each volume tier needs min_qty >= 1 and extra_discount_pct")
        clean_tiers.append({"min_qty": t["min_qty"],
                            "extra_discount_pct": t["extra_discount_pct"]})
    book = {
        "id": new_id(),
        "name": name,
        "scope": scope,
        "customer_id": cust_id,
        "effective_from": b.get("effective_from"),
        "effective_to": b.get("effective_to"),
        "default_discount_pct": discount,
        "volume_tiers": clean_tiers,
        "status": "DRAFT",
        "_from": eff_from,
        "_to": eff_to,
    }
    new_common(book)
    store.price_books[book["id"]] = book
    return created(book)


@bp.route("/price-books", methods=["GET"])
@require_roles("CounterRep", "BranchManager")
def list_books():
    rows = list(store.price_books.values())
    rows = filter_param(rows, "customer_id")
    rows = filter_param(rows, "scope")
    rows = filter_param(rows, "status")
    return list_response(rows)


@bp.route("/price-books/<bid>", methods=["GET"])
@require_roles("CounterRep", "BranchManager")
def get_one_book(bid):
    return ok(get_book(bid))


@bp.route("/price-books/<bid>/activate", methods=["POST"])
@require_roles("BranchManager")
def activate_book(bid):
    book = get_book(bid)
    # Priority 6: DRAFT only.
    if book["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DRAFT price book can be activated")
    # Priority 9: no overlapping ACTIVE window for the same scope + customer.
    # Windows are half-open [from, to): adjacency (to == other.from) is allowed.
    for other in store.price_books.values():
        if other["id"] == book["id"] or other["status"] != "ACTIVE":
            continue
        if other["scope"] != book["scope"] or other["customer_id"] != book["customer_id"]:
            continue
        if book["_from"] < other["_to"] and other["_from"] < book["_to"]:
            raise ApiError("ERR_PRICE_BOOK_OVERLAP", 409,
                           "Window overlaps another ACTIVE book with the same scope and customer")
    book["status"] = "ACTIVE"
    touch(book)
    return ok(book)


def sweep_expired_books():
    """ACTIVE -> EXPIRED for books whose effective_to has been reached or passed."""
    now = db.clock_now()
    for book in store.price_books.values():
        if book["status"] == "ACTIVE" and book["_to"] <= now:
            book["status"] = "EXPIRED"
            touch(book)
