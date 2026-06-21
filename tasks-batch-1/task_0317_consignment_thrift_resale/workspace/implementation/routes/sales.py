from flask import Blueprint, request

from db import store
from errors import err
from middleware import require
from response import success, paginated
from services.common import (
    base_record, ledger_record, touch, require_body, require_enum,
    parse_pagination, page, now,
)
from services import serialize, calc

bp = Blueprint("sales", __name__)

PAYMENT_METHODS = {"CASH", "CARD", "STORE_CREDIT"}


@bp.post("/sales")
@require("CashierClerk")
def create_sale():
    body = require_body()
    payment_method = require_enum(body, "payment_method", PAYMENT_METHODS, default="CARD")

    if "lines" not in body or not isinstance(body["lines"], list) or len(body["lines"]) == 0:
        raise err("ERR_INVALID_REQUEST", "lines must be a non-empty array")

    # Parse and type-check each line first (priority: request well-formedness).
    parsed = []
    for ln in body["lines"]:
        if not isinstance(ln, dict):
            raise err("ERR_INVALID_REQUEST", "each line must be an object")
        if "item_id" not in ln or not isinstance(ln["item_id"], str):
            raise err("ERR_INVALID_REQUEST", "line item_id required")
        sp = ln.get("sold_price_cents")
        if sp is not None and (isinstance(sp, bool) or not isinstance(sp, int)):
            raise err("ERR_INVALID_REQUEST", "sold_price_cents must be an integer")
        parsed.append({"item_id": ln["item_id"], "sold_price_cents": sp})

    # Body FK existence (priority 4, ERR_REFERENCE_NOT_FOUND).
    for p in parsed:
        if p["item_id"] not in store.items:
            raise err("ERR_REFERENCE_NOT_FOUND", "Item not found")

    # Duplicate line check (priority 10). Checked before/after on-floor? PRD §3.5
    # lists ERR_ITEM_NOT_ON_FLOOR (priority 9) before ERR_DUPLICATE_SALE_LINE (10).
    # On-floor check first:
    for p in parsed:
        if store.items[p["item_id"]]["listing_status"] != "ON_FLOOR":
            raise err("ERR_ITEM_NOT_ON_FLOOR", "Item is not ON_FLOOR")

    seen = set()
    for p in parsed:
        if p["item_id"] in seen:
            raise err("ERR_DUPLICATE_SALE_LINE", "Item appears more than once in sale")
        seen.add(p["item_id"])

    # Price band validation (priority 13). Compute each line's price/floor/current.
    line_plans = []
    for p in parsed:
        item = store.items[p["item_id"]]
        agreement = store.agreements[item["agreement_id"]]
        schedule = store.markdown_schedules[agreement["markdown_schedule_id"]]
        current = calc.markdown_price(item["list_price_cents"], item["floor_date_dt"], now(), schedule)
        floor_price = calc.markdown_floor_cents(item["list_price_cents"], schedule["base_floor_pct"])
        sold = p["sold_price_cents"] if p["sold_price_cents"] is not None else current
        if sold < floor_price or sold > current:
            raise err("ERR_PRICE_BELOW_FLOOR", "sold_price_cents outside markdown band")
        line_plans.append({
            "item": item,
            "agreement": agreement,
            "sold_price_cents": sold,
        })

    # All validations passed — commit atomically.
    sale = base_record()
    ts = now()
    business_date = serialize.iso_dt(ts)[:10]
    sale.update({
        "sold_at": serialize.iso_dt(ts),
        "business_date": business_date,
        "rung_by_user_id": request.user_id,
        "payment_method": payment_method,
        "gross_total_cents": 0,
        "status": "COMPLETED",
        "settlement_id": None,
    })
    store.sales[sale["id"]] = sale

    gross_total = 0
    affected_consignors = set()
    for plan in line_plans:
        item = plan["item"]
        agreement = plan["agreement"]
        sold = plan["sold_price_cents"]

        processing_fee = calc.PROCESSING_FEE_CENTS
        sb = calc.split_base(sold, processing_fee, agreement["split_basis"])
        proceeds = calc.consignor_proceeds(sb, agreement["split_pct"])
        store_share = sold - proceeds

        line = ledger_record()
        line.update({
            "sale_id": sale["id"],
            "item_id": item["id"],
            "consignor_id": item["consignor_id"],
            "sold_price_cents": sold,
            "processing_fee_cents": processing_fee,
            "split_base_cents": sb,
            "consignor_proceeds_cents": proceeds,
            "store_share_cents": store_share,
        })
        store.sale_lines[line["id"]] = line

        # Item ON_FLOOR -> SOLD
        item["listing_status"] = "SOLD"
        item["sold_price_cents"] = sold
        touch(item)
        gross_total += sold

        # Payout channel cascade
        if agreement["payout_method"] == "CASH":
            entry = ledger_record()
            entry.update({
                "consignor_id": item["consignor_id"],
                "sale_line_ref": item["id"],
                "entry_type": "SALE_PAYOUT",
                "amount_cents": proceeds,
                "settlement_id": None,
            })
            store.payout_ledger_entries[entry["id"]] = entry
        else:  # STORE_CREDIT
            issued = calc.store_credit_payout(proceeds)
            txn = ledger_record()
            txn.update({
                "consignor_id": item["consignor_id"],
                "txn_type": "ISSUE",
                "amount_cents": issued,
                "status": "POSTED",
                "_sale_id": sale["id"],
                "_sale_line_id": line["id"],
            })
            store.store_credit_transactions[txn["id"]] = txn
        affected_consignors.add(item["consignor_id"])

    sale["gross_total_cents"] = gross_total
    for cid in affected_consignors:
        serialize.reconcile_consignor(store.consignors[cid])

    return success(serialize.sale_out(sale), 201)


@bp.get("/sales/<sid>")
@require("CashierClerk", "SettlementManager", "StoreAdmin")
def get_sale(sid):
    s = store.sales.get(sid)
    if s is None:
        raise err("ERR_NOT_FOUND", "Sale not found")
    return success(serialize.sale_out(s), 200)


@bp.get("/sales")
@require("CashierClerk", "SettlementManager", "StoreAdmin")
def list_sales():
    limit, offset = parse_pagination()
    recs = list(store.sales.values())
    business_date = request.args.get("business_date")
    status = request.args.get("status")
    settlement_id = request.args.get("settlement_id")
    if business_date is not None:
        recs = [s for s in recs if s["business_date"] == business_date]
    if status is not None:
        recs = [s for s in recs if s["status"] == status]
    if settlement_id is not None:
        recs = [s for s in recs if s["settlement_id"] == settlement_id]
    window, total = page(recs, limit, offset)
    return paginated([serialize.sale_out(s) for s in window], limit, offset, total)


@bp.get("/sales/<sid>/lines")
@require("CashierClerk", "SettlementManager", "StoreAdmin")
def sale_lines(sid):
    if sid not in store.sales:
        raise err("ERR_NOT_FOUND", "Sale not found")
    limit, offset = parse_pagination()
    recs = [l for l in store.sale_lines.values() if l["sale_id"] == sid]
    window, total = page(recs, limit, offset)
    return paginated([serialize.sale_line_out(l) for l in window], limit, offset, total)


@bp.post("/sales/<sid>/void")
@require("CashierClerk", "SettlementManager")
def void_sale(sid):
    s = store.sales.get(sid)
    if s is None:
        raise err("ERR_NOT_FOUND", "Sale not found")

    # State + cross-entity: only COMPLETED and not yet swept.
    if s["status"] != "COMPLETED" or s["settlement_id"] is not None:
        raise err("ERR_INVALID_STATE", "Sale cannot be voided")

    s["status"] = "VOIDED"
    lines = [l for l in store.sale_lines.values() if l["sale_id"] == sid]
    affected_consignors = set()
    for line in lines:
        item = store.items[line["item_id"]]
        agreement = store.agreements[item["agreement_id"]]

        # Item back to floor; clear sold price; recompute current price.
        item["listing_status"] = "ON_FLOOR"
        item["sold_price_cents"] = None
        item["current_price_cents"] = serialize.item_current_price(item)
        touch(item)

        if agreement["payout_method"] == "CASH":
            entry = ledger_record()
            entry.update({
                "consignor_id": line["consignor_id"],
                "sale_line_ref": item["id"],
                "entry_type": "REVERSAL",
                "amount_cents": -line["consignor_proceeds_cents"],
                "settlement_id": None,
            })
            store.payout_ledger_entries[entry["id"]] = entry
        else:  # STORE_CREDIT: flip originating ISSUE to VOID
            for txn in store.store_credit_transactions.values():
                if (
                    txn.get("_sale_line_id") == line["id"]
                    and txn["txn_type"] == "ISSUE"
                    and txn["status"] == "POSTED"
                ):
                    txn["status"] = "VOID"
        affected_consignors.add(line["consignor_id"])

    for cid in affected_consignors:
        serialize.reconcile_consignor(store.consignors[cid])

    touch(s)
    return success(serialize.sale_out(s), 200)
