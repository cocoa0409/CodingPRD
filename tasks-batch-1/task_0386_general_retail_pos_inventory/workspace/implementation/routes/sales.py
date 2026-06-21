"""Sale, TenderLine endpoints (PRD §3.3 - §3.8)."""
from flask import Blueprint, request

from db import DB
from middleware import auth_context, require_role
from common import (
    stamp_create, touch, public_view, get_json_body, as_int, as_str,
    as_enum, parse_pagination, paginate,
)
from response import success, success_list
from errors import (
    err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_DRAWER_NOT_OPEN, ERR_OVERTENDER,
    ERR_FORBIDDEN_ROLE,
)
from services import sale_ops
from services.posture import open_session_for_store, posture_for_store

bp = Blueprint("sales", __name__)

SALE_KINDS = {"SALE", "RETURN", "EXCHANGE"}
TENDER_METHODS = {"CASH", "CARD", "STORE_CREDIT", "GIFT_CARD"}


def _sale_view(sale):
    out = public_view(sale)
    # _lines / _tenders / _line_net_alloc / _settle_tier are internal; expose a
    # clean lines projection for readers.
    out["lines"] = [
        {
            "line_no": ln["line_no"],
            "product_id": ln["product_id"],
            "quantity": ln["quantity"],
            "return_of_line_no": ln["return_of_line_no"],
        }
        for ln in sale["_lines"]
    ]
    out["tendered_cents"] = _tendered_cents(sale)
    return out


def _tendered_cents(sale):
    total = 0
    for tid in sale.get("_tenders", []):
        t = DB.tender_lines.get(tid)
        if t is not None:
            total += t["amount_cents"]
    return total


@bp.route("/sales", methods=["POST"])
def create_sale():
    _, role = auth_context()
    require_role(role, {"Cashier"})
    body = get_json_body()

    store_id = as_str(body, "store_id")
    kind = as_enum(body, "kind", SALE_KINDS)
    raw_lines = body.get("lines")
    loyalty_account_id = body.get("loyalty_account_id")
    promo_code = body.get("promo_code")
    redeem_points = as_int(body, "redeem_points", required=False, default=0, minimum=0)
    original_sale_id = body.get("original_sale_id")

    with DB.lock:
        # body FK resolution (priority 4)
        if store_id not in DB.stores:
            raise err(ERR_REFERENCE_NOT_FOUND, "store_id not found")
        if loyalty_account_id is not None:
            if not isinstance(loyalty_account_id, str) or loyalty_account_id not in DB.loyalty_accounts:
                raise err(ERR_REFERENCE_NOT_FOUND, "loyalty_account_id not found")
        if original_sale_id is not None:
            if not isinstance(original_sale_id, str) or original_sale_id not in DB.sales:
                raise err(ERR_REFERENCE_NOT_FOUND, "original_sale_id not found")

        # body well-formedness (priority 5): resolve & snapshot lines
        lines = sale_ops.resolve_lines(DB, raw_lines, kind)

        # return-reference check (priority 10)
        if kind in ("RETURN", "EXCHANGE"):
            return_lines = [ln for ln in lines if ln.get("return_of_line_no") is not None]
            original = sale_ops.validate_return_reference(DB, original_sale_id, return_lines)

        sale = {
            "store_id": store_id,
            "cash_session_id": None,
            "loyalty_account_id": loyalty_account_id,
            "kind": kind,
            "original_sale_id": original_sale_id,
            "promo_code": promo_code,
            "redeem_points": redeem_points,
            "merchandise_subtotal_cents": 0,
            "discount_cents": 0,
            "loyalty_redeemed_cents": 0,
            "tax_cents": 0,
            "total_due_cents": 0,
            "tendered_cents": 0,
            "points_earned": 0,
            "settlement_status": "DRAFT",
            "stock_status": "PENDING",
            "_lines": lines,
            "_tenders": [],
            "_line_net_alloc": [],
        }
        stamp_create(sale)
        # bind to the store's current OPEN session if one exists
        sess = open_session_for_store(DB, store_id)
        sale["cash_session_id"] = sess["id"] if sess else None

        # price the basket (priority 11/12/13 guards fire here for SALE)
        if kind == "SALE":
            sale_ops.price_sale(DB, sale, enforce_guards=True)
        else:
            _price_return_provisional(DB, sale, original)

        DB.sales[sale["id"]] = sale
        return success(_sale_view(sale), status=201)


def _price_return_provisional(db, sale, original):
    """Provisional refund at RETURN/EXCHANGE creation (PRD §3.7). The estimated
    total_due_cents is a NET REFUND (negative) for the returned units; an
    EXCHANGE's outbound lines are priced like a sale and net against the refund.
    """
    return_lines = [ln for ln in sale["_lines"] if ln.get("return_of_line_no") is not None]
    refund = sale_ops.compute_provisional_refund(db, original, return_lines)

    # outbound (newly-sold) lines on an EXCHANGE are priced as a fresh basket
    outbound = [ln for ln in sale["_lines"] if ln.get("return_of_line_no") is None]
    outbound_total = 0
    if outbound:
        store = db.stores[sale["store_id"]]
        promo = None
        if sale.get("promo_code"):
            for p in db.promotions.values():
                if p["code"] == sale["promo_code"]:
                    promo = p
                    break
        account = None
        if sale.get("loyalty_account_id"):
            account = db.loyalty_accounts.get(sale["loyalty_account_id"])
        ob_inputs = [
            {
                "list_price_cents": ln["list_price_cents"],
                "quantity": ln["quantity"],
                "tax_exempt": ln["tax_exempt"],
                "loyalty_eligible": ln["loyalty_eligible"],
            }
            for ln in outbound
        ]
        from services.pricing import price_basket
        ob = price_basket(ob_inputs, promo, sale.get("redeem_points", 0) or 0,
                          account, store["tax_rate_bps"], enforce_guards=True)
        outbound_total = ob["total_due_cents"]
        sale["merchandise_subtotal_cents"] = ob["merchandise_subtotal_cents"]
        sale["discount_cents"] = ob["discount_cents"]
        sale["loyalty_redeemed_cents"] = ob["loyalty_redeemed_cents"]
        sale["tax_cents"] = ob["tax_cents"]

    # net refund convention: returned value is owed back to the customer
    sale["total_due_cents"] = outbound_total - refund


@bp.route("/sales/<sale_id>", methods=["GET"])
def get_sale(sale_id):
    user_id, role = auth_context()
    require_role(role, {"StoreManager", "Cashier", "Customer"})
    with DB.lock:
        sale = DB.sales.get(sale_id)
        if sale is None:
            raise err(ERR_NOT_FOUND, "Sale not found")
        if role == "Customer" and sale.get("loyalty_account_id") != user_id:
            raise err(ERR_FORBIDDEN_ROLE, "Customers may only read their own sales")
        return success(_sale_view(sale))


@bp.route("/sales", methods=["GET"])
def list_sales():
    _, role = auth_context()
    require_role(role, {"StoreManager", "Cashier"})
    limit, offset = parse_pagination()
    f = request.args
    with DB.lock:
        recs = list(DB.sales.values())
        for key in ("store_id", "settlement_status", "cash_session_id",
                    "loyalty_account_id", "original_sale_id"):
            val = f.get(key)
            if val is not None:
                recs = [r for r in recs if r.get(key) == val]
        ordered = sorted(recs, key=lambda r: r["_seq"])
        total = len(ordered)
        window = ordered[offset:offset + limit]
        items = [_sale_view(r) for r in window]
        return success_list(items, limit, offset, total)


@bp.route("/sales/<sale_id>/lines", methods=["PUT"])
def replace_lines(sale_id):
    _, role = auth_context()
    require_role(role, {"Cashier"})
    body = get_json_body()
    with DB.lock:
        sale = DB.sales.get(sale_id)
        if sale is None:
            raise err(ERR_NOT_FOUND, "Sale not found")
        # only a DRAFT sale may be re-lined (PRD §3.3)
        if sale["settlement_status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "Only DRAFT sales may be re-lined")

        raw_lines = body.get("lines")
        lines = sale_ops.resolve_lines(DB, raw_lines, sale["kind"])
        # promo_code / redeem_points may be re-supplied
        if "promo_code" in body:
            sale["promo_code"] = body.get("promo_code")
        if "redeem_points" in body:
            sale["redeem_points"] = as_int(body, "redeem_points", required=False,
                                           default=0, minimum=0)
        sale["_lines"] = lines

        if sale["kind"] == "SALE":
            sale_ops.price_sale(DB, sale, enforce_guards=True)
        else:
            return_lines = [ln for ln in lines if ln.get("return_of_line_no") is not None]
            original = sale_ops.validate_return_reference(
                DB, sale.get("original_sale_id"), return_lines)
            _price_return_provisional(DB, sale, original)

        touch(sale)
        return success(_sale_view(sale))


@bp.route("/sales/<sale_id>/tenders", methods=["POST"])
def append_tender(sale_id):
    _, role = auth_context()
    require_role(role, {"Cashier"})
    body = get_json_body()
    method = as_enum(body, "method", TENDER_METHODS)
    amount_cents = as_int(body, "amount_cents")
    expected = as_int(body, "expected_sale_version")

    with DB.lock:
        sale = DB.sales.get(sale_id)
        if sale is None:
            raise err(ERR_NOT_FOUND, "Sale not found")
        # OCC (priority 7) precedes state (priority 8) and drawer (priority 9)
        if expected != sale["version"]:
            raise err(ERR_STALE_VERSION, "Stale sale version")
        # state: tender only from DRAFT or TENDERING
        if sale["settlement_status"] not in ("DRAFT", "TENDERING"):
            raise err(ERR_INVALID_STATE, "Sale cannot be tendered in its current state")
        # drawer posture gate (priority 9)
        if posture_for_store(DB, sale["store_id"]) != "DRAWER_OPEN":
            raise err(ERR_DRAWER_NOT_OPEN, "Selling store has no open drawer")
        # rebind to the current OPEN session (the gate guarantees one exists)
        sess = open_session_for_store(DB, sale["store_id"])
        if sale.get("cash_session_id") is None:
            sale["cash_session_id"] = sess["id"]

        is_sale = sale["kind"] == "SALE"
        total_due = sale["total_due_cents"]
        current = _tendered_cents(sale)
        new_total = current + amount_cents

        change_due = 0
        if is_sale:
            # overtender guard (priority 15): only CASH may exceed total_due
            if new_total > total_due:
                if method != "CASH":
                    raise err(ERR_OVERTENDER, "Non-cash tender over-collects on a SALE")
                change_due = new_total - total_due

        # Decide whether this tender settles the sale.
        if is_sale:
            settled = new_total >= total_due
        elif total_due <= 0:
            # net-refund RETURN/EXCHANGE: settle when tendered reaches at most
            # total_due (both zero or negative).
            settled = new_total <= total_due
        else:
            settled = new_total >= total_due

        # Atomicity (PRD §2.10): validate the settlement preconditions (stock)
        # BEFORE any mutation lands. If finalizing the return total or checking
        # stock fails, no tender is appended and no status change persists.
        if settled and not is_sale:
            _finalize_return_total(DB, sale)
        if settled:
            sale_ops.check_settlement_stock(DB, sale)

        # All preconditions passed — now commit the tender and effects.
        tender = sale_ops._make_tender(DB, sale, method, amount_cents, change_due)
        sale["_tenders"].append(tender["id"])
        sale["settlement_status"] = "TENDERING"

        if settled:
            sale_ops.settle_sale(DB, sale)

        sale["tendered_cents"] = _tendered_cents(sale)
        touch(sale)
        return success(public_view(tender), status=201)


def _finalize_return_total(db, sale):
    """At settlement, replace the provisional refund with the FINAL basket-delta
    refund (PRD §3.7). For an EXCHANGE, net the outbound total against it."""
    original = db.sales.get(sale.get("original_sale_id"))
    if original is None:
        return
    return_lines = [ln for ln in sale["_lines"] if ln.get("return_of_line_no") is not None]
    final_refund = sale_ops.compute_final_refund(db, original, return_lines)
    outbound = [ln for ln in sale["_lines"] if ln.get("return_of_line_no") is None]
    outbound_total = 0
    if outbound:
        from services.pricing import price_basket as _pb
        store = db.stores[sale["store_id"]]
        promo = None
        if sale.get("promo_code"):
            for p in db.promotions.values():
                if p["code"] == sale["promo_code"]:
                    promo = p
                    break
        account = None
        if sale.get("loyalty_account_id"):
            account = db.loyalty_accounts.get(sale["loyalty_account_id"])
        ob_inputs = [
            {
                "list_price_cents": ln["list_price_cents"],
                "quantity": ln["quantity"],
                "tax_exempt": ln["tax_exempt"],
                "loyalty_eligible": ln["loyalty_eligible"],
            }
            for ln in outbound
        ]
        ob = _pb(ob_inputs, promo, sale.get("redeem_points", 0) or 0,
                 account, store["tax_rate_bps"], enforce_guards=False)
        outbound_total = ob["total_due_cents"]
    sale["total_due_cents"] = outbound_total - final_refund


@bp.route("/sales/<sale_id>/tenders", methods=["GET"])
def list_tenders(sale_id):
    _, role = auth_context()
    require_role(role, {"StoreManager", "Cashier"})
    limit, offset = parse_pagination()
    with DB.lock:
        sale = DB.sales.get(sale_id)
        if sale is None:
            raise err(ERR_NOT_FOUND, "Sale not found")
        tenders = [DB.tender_lines[tid] for tid in sale.get("_tenders", [])
                   if tid in DB.tender_lines]
        ordered = sorted(tenders, key=lambda t: t["_seq"])
        total = len(ordered)
        window = ordered[offset:offset + limit]
        items = [public_view(t) for t in window]
        return success_list(items, limit, offset, total)


@bp.route("/sales/<sale_id>/void", methods=["POST"])
def void_sale(sale_id):
    _, role = auth_context()
    require_role(role, {"Cashier"})
    with DB.lock:
        sale = DB.sales.get(sale_id)
        if sale is None:
            raise err(ERR_NOT_FOUND, "Sale not found")
        # void allowed from DRAFT or TENDERING (anything but SETTLED) (PRD §3.5)
        if sale["settlement_status"] == "SETTLED" or sale["settlement_status"] == "VOIDED":
            raise err(ERR_INVALID_STATE, "Only non-settled sales may be voided")
        sale_ops.void_sale(DB, sale)
        sale["tendered_cents"] = _tendered_cents(sale)
        touch(sale)
        return success(_sale_view(sale))
