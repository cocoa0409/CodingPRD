from flask import Blueprint, request

from db import store
from errors import err
from middleware import require
from response import success, paginated
from services.common import base_record, touch, require_body, parse_pagination, page
from services import serialize

bp = Blueprint("settlements", __name__)

DATE_RE = None


def _valid_business_date(value):
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        return False
    parts = value.split("-")
    if len(parts) != 3:
        return False
    y, m, d = parts
    if not (y.isdigit() and m.isdigit() and d.isdigit()):
        return False
    if not (1 <= int(m) <= 12 and 1 <= int(d) <= 31):
        return False
    return True


@bp.post("/settlements")
@require("SettlementManager")
def open_settlement():
    body = require_body()
    if "business_date" not in body or not _valid_business_date(body["business_date"]):
        raise err("ERR_INVALID_REQUEST", "business_date (YYYY-MM-DD) required")
    business_date = body["business_date"]

    for s in store.settlements.values():
        if s["business_date"] == business_date and s["status"] != "VOIDED":
            raise err("ERR_SETTLEMENT_DATE_TAKEN", "A non-VOIDED settlement covers this date")

    rec = base_record()
    rec.update({
        "business_date": business_date,
        "status": "OPEN",
        "total_gross_cents": 0,
        "total_consignor_payable_cents": 0,
        "total_store_credit_issued_cents": 0,
        "total_store_share_cents": 0,
        "swept_sale_count": 0,
    })
    store.settlements[rec["id"]] = rec
    return success(serialize.settlement_out(rec), 201)


@bp.get("/settlements/<sid>")
@require("SettlementManager", "StoreAdmin")
def get_settlement(sid):
    s = store.settlements.get(sid)
    if s is None:
        raise err("ERR_NOT_FOUND", "Settlement not found")
    return success(serialize.settlement_out(s), 200)


@bp.get("/settlements")
@require("SettlementManager", "StoreAdmin")
def list_settlements():
    limit, offset = parse_pagination()
    recs = list(store.settlements.values())
    business_date = request.args.get("business_date")
    status = request.args.get("status")
    if business_date is not None:
        recs = [s for s in recs if s["business_date"] == business_date]
    if status is not None:
        recs = [s for s in recs if s["status"] == status]
    window, total = page(recs, limit, offset)
    return paginated([serialize.settlement_out(s) for s in window], limit, offset, total)


@bp.post("/settlements/<sid>/finalize")
@require("SettlementManager")
def finalize_settlement(sid):
    s = store.settlements.get(sid)
    if s is None:
        raise err("ERR_NOT_FOUND", "Settlement not found")
    body = require_body()
    if "expected_settlement_version" not in body:
        raise err("ERR_INVALID_REQUEST", "expected_settlement_version required")
    expected = body["expected_settlement_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_settlement_version must be an integer")

    # State precedes OCC (PRD §2.5).
    if s["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Settlement is not OPEN")

    if expected != s["version"]:
        raise err("ERR_STALE_SETTLEMENT_VERSION", "expected_settlement_version does not match")

    # Scope: COMPLETED sales for this business_date not already swept.
    scope = [
        sale for sale in store.sales.values()
        if sale["business_date"] == s["business_date"]
        and sale["status"] == "COMPLETED"
        and sale["settlement_id"] is None
    ]

    total_gross = 0
    total_consignor_payable = 0
    total_store_credit_issued = 0
    affected_consignors = set()
    scope_sale_ids = set(sale["id"] for sale in scope)

    for sale in scope:
        total_gross += sale["gross_total_cents"]

    # Per-line cash proceeds (round-per-line-then-sum) and store-credit issued.
    for line in store.sale_lines.values():
        if line["sale_id"] not in scope_sale_ids:
            continue
        item = store.items[line["item_id"]]
        agreement = store.agreements[item["agreement_id"]]
        if agreement["payout_method"] == "CASH":
            total_consignor_payable += line["consignor_proceeds_cents"]
        affected_consignors.add(line["consignor_id"])

    for txn in store.store_credit_transactions.values():
        if (
            txn["txn_type"] == "ISSUE"
            and txn["status"] == "POSTED"
            and txn.get("_sale_id") in scope_sale_ids
        ):
            total_store_credit_issued += txn["amount_cents"]

    total_store_share = total_gross - total_consignor_payable - total_store_credit_issued

    # Cascade sweep: stamp settlement_id on sales and unsettled ledger entries.
    for sale in scope:
        sale["settlement_id"] = s["id"]
    for entry in store.payout_ledger_entries.values():
        if entry["settlement_id"] is None:
            # entry belongs to a scope sale if its originating sale line is in scope
            for line in store.sale_lines.values():
                if (
                    line["sale_id"] in scope_sale_ids
                    and line["item_id"] == entry["sale_line_ref"]
                    and line["consignor_id"] == entry["consignor_id"]
                ):
                    entry["settlement_id"] = s["id"]
                    affected_consignors.add(entry["consignor_id"])
                    break

    for cid in affected_consignors:
        serialize.reconcile_consignor(store.consignors[cid])

    s["total_gross_cents"] = total_gross
    s["total_consignor_payable_cents"] = total_consignor_payable
    s["total_store_credit_issued_cents"] = total_store_credit_issued
    s["total_store_share_cents"] = total_store_share
    s["swept_sale_count"] = len(scope)
    s["status"] = "FINALIZED"
    touch(s)
    return success(serialize.settlement_out(s), 200)


@bp.post("/settlements/<sid>/void")
@require("SettlementManager")
def void_settlement(sid):
    s = store.settlements.get(sid)
    if s is None:
        raise err("ERR_NOT_FOUND", "Settlement not found")
    if s["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Only OPEN settlements may be voided")
    s["status"] = "VOIDED"
    touch(s)
    return success(serialize.settlement_out(s), 200)


@bp.get("/settlements/<sid>/sales")
@require("SettlementManager", "StoreAdmin")
def settlement_sales(sid):
    if sid not in store.settlements:
        raise err("ERR_NOT_FOUND", "Settlement not found")
    limit, offset = parse_pagination()
    recs = [sale for sale in store.sales.values() if sale["settlement_id"] == sid]
    window, total = page(recs, limit, offset)
    return paginated([serialize.sale_out(sale) for sale in window], limit, offset, total)


@bp.get("/settlements/<sid>/ledger-entries")
@require("SettlementManager", "StoreAdmin")
def settlement_ledger(sid):
    if sid not in store.settlements:
        raise err("ERR_NOT_FOUND", "Settlement not found")
    limit, offset = parse_pagination()
    recs = [e for e in store.payout_ledger_entries.values() if e["settlement_id"] == sid]
    window, total = page(recs, limit, offset)
    return paginated([serialize.ledger_out(e) for e in window], limit, offset, total)
