"""ShrinkRecord and CreditMemo routes — segregation of duties (Receiver files,
MarketAdmin approves), payable reconciliation, compensating memo void."""

from flask import Blueprint

from db import store
from errors import (
    raise_error,
    ERR_INVALID_STATE,
    ERR_INSUFFICIENT_QUANTITY,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.domain import (
    get_json_body,
    require_fields,
    req_positive_int,
    req_enum,
    is_str,
    lookup,
    stamp_new,
    touch,
    paginate,
    sorted_by_created,
    credit_memo_amount_cents,
    recompute_lot_payable,
    recompute_lot_available,
    recompute_shipper_trust_exposure,
    now_iso,
)

bp = Blueprint("shrink", __name__)


@bp.post("/market/shrink-records")
def create_shrink_record():
    require_roles(["Receiver"])
    body = get_json_body()
    require_fields(body, ["purchase_lot_id", "quantity", "reason"])
    purchase_lot_id = body.get("purchase_lot_id")
    if not is_str(purchase_lot_id):
        from errors import ERR_VALIDATION

        raise_error(ERR_VALIDATION, "purchase_lot_id must be a string")
    quantity = req_positive_int(body, "quantity")
    reason = req_enum(body, "reason", {"DUMP", "TRIM", "DAMAGE", "THEFT"})

    lot = lookup(store.purchase_lots, purchase_lot_id, "PurchaseLot")
    # Shrink is recorded on an ACCEPTED lot (PRD §3.8)
    if lot["status"] != "ACCEPTED":
        raise_error(
            ERR_INVALID_STATE,
            f"Shrink may only be recorded on an ACCEPTED lot; current status {lot['status']}",
        )
    record = stamp_new(
        {
            "purchase_lot_id": purchase_lot_id,
            "quantity": quantity,
            "reason": reason,
            "status": "DRAFT",
            "credit_memo_id": None,
        }
    )
    store.shrink_records[record["id"]] = record
    return success_object(record, 201)


@bp.get("/market/purchase-lots/<lot_id>/shrink-records")
def list_lot_shrink_records(lot_id):
    require_roles(ALL_ROLES)
    lookup(store.purchase_lots, lot_id, "PurchaseLot")
    items = [
        r for r in store.shrink_records.values() if r["purchase_lot_id"] == lot_id
    ]
    items = sorted_by_created(items)
    page, pagination = paginate(items)
    return success_list(page, pagination, 200)


@bp.post("/market/shrink-records/<record_id>/approve")
def approve_shrink_record(record_id):
    require_roles(["MarketAdmin"])
    record = lookup(store.shrink_records, record_id, "ShrinkRecord")
    if record["status"] != "DRAFT":
        raise_error(
            ERR_INVALID_STATE,
            f"Shrink record must be DRAFT to approve; current status {record['status']}",
        )
    lot = lookup(store.purchase_lots, record["purchase_lot_id"], "PurchaseLot")
    recompute_lot_available(lot)
    if record["quantity"] > lot["available_units"]:
        raise_error(
            ERR_INSUFFICIENT_QUANTITY,
            f"Shrink quantity {record['quantity']} exceeds available_units {lot['available_units']}",
        )

    # Cascade hop 1: issue the CreditMemo
    amount = credit_memo_amount_cents(
        lot["adjusted_cost_cents"], record["quantity"], lot["quantity_units"]
    )
    memo = stamp_new(
        {
            "purchase_lot_id": lot["id"],
            "amount_cents": amount,
            "status": "ISSUED",
            "issued_at": now_iso(),
            "voided_at": None,
        }
    )
    store.credit_memos[memo["id"]] = memo

    # Cascade hop 2: lot accounting
    record["status"] = "APPROVED"
    record["credit_memo_id"] = memo["id"]
    touch(record)
    lot["dumped_units"] += record["quantity"]
    recompute_lot_payable(lot)
    recompute_lot_available(lot)
    touch(lot)
    recompute_shipper_trust_exposure(lot["shipper_id"])
    return success_object(record, 200)


@bp.get("/market/purchase-lots/<lot_id>/credit-memos")
def list_lot_credit_memos(lot_id):
    require_roles(ALL_ROLES)
    lookup(store.purchase_lots, lot_id, "PurchaseLot")
    items = [
        m for m in store.credit_memos.values() if m["purchase_lot_id"] == lot_id
    ]
    items = sorted_by_created(items)
    page, pagination = paginate(items)
    return success_list(page, pagination, 200)


@bp.post("/market/credit-memos/<memo_id>/void")
def void_credit_memo(memo_id):
    require_roles(["BillingClerk"])
    memo = lookup(store.credit_memos, memo_id, "CreditMemo")
    if memo["status"] != "ISSUED":
        raise_error(
            ERR_INVALID_STATE,
            f"Credit memo must be ISSUED to void; current status {memo['status']}",
        )
    memo["status"] = "VOID"
    memo["voided_at"] = now_iso()
    touch(memo)
    lot = lookup(store.purchase_lots, memo["purchase_lot_id"], "PurchaseLot")
    recompute_lot_payable(lot)
    touch(lot)
    recompute_shipper_trust_exposure(lot["shipper_id"])
    return success_object(memo, 200)
