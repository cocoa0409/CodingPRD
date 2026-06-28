"""Transaction posting engine (PRD §3.4, §3.5, §3.6, §3.8).

Validation order is the fixed priority chain from PRD §2.11. CHECK_CASH forks
into auto-clear (POST) or RISK_HELD (DRAFT) on the CheckItem; non-CHECK_CASH
posts immediately and creates a product child."""
import errors
from db import db, new_id, common_fields, touch, next_money_order_serial

from services import calculations as calc
from services import domain


def compute_fee(txn_type, face_cents, schedule):
    if txn_type == "CHECK_CASH":
        return calc.check_cash_fee(face_cents, schedule)
    return calc.service_fee(txn_type, face_cents)


def create_product_child(txn, body):
    """Create the matching product child instrument for a posted non-CHECK_CASH
    transaction (PRD §3.6). Each carries its own common fields/version."""
    tid = txn["id"]
    txn_type = txn["txn_type"]
    face = txn["face_amount_cents"]

    if txn_type == "MONEY_ORDER":
        mid = new_id()
        child = {
            "id": mid,
            "transaction_id": tid,
            "serial_number": next_money_order_serial(),
            "payee_name": txn["_payee_name"],
            "amount_cents": face,
            "status": "ISSUED",
        }
        child.update(common_fields())
        db.money_orders[mid] = child
    elif txn_type == "WIRE":
        wid = new_id()
        child = {
            "id": wid,
            "transaction_id": tid,
            "destination_country": txn["_destination_country"],
            "beneficiary_name": txn["_beneficiary_name"],
            "status": "SENT",
        }
        child.update(common_fields())
        db.wire_transfers[wid] = child
    elif txn_type == "BILL_PAY":
        bid = new_id()
        child = {
            "id": bid,
            "transaction_id": tid,
            "biller_code": txn["_biller_code"],
            "account_reference": txn["_account_reference"],
            "status": "SUBMITTED",
        }
        child.update(common_fields())
        db.bill_payments[bid] = child
    elif txn_type == "PREPAID_LOAD":
        pid = new_id()
        child = {
            "id": pid,
            "transaction_id": tid,
            "card_last_four": txn["_card_last_four"],
            "loaded_amount_cents": face,
            "status": "LOADED",
        }
        child.update(common_fields())
        db.prepaid_card_loads[pid] = child


def post_transaction(txn, customer, drawer, compute=True):
    """Move a transaction to POSTED/SETTLED, recompute drawer cash, bump the
    customer's velocity counters with the projected values (PRD §3.4, §3.5).

    The velocity window must already have been rolled and the projected caps
    validated by the caller before this commits. When compute is False the
    caller has already set fee_cents/net_disbursed_cents (held-check release)."""
    if compute:
        txn["fee_cents"] = compute_fee(
            txn["txn_type"], txn["face_amount_cents"], txn.get("_schedule")
        )
        txn["net_disbursed_cents"] = calc.net_disbursed(
            txn["txn_type"], txn["face_amount_cents"], txn["fee_cents"]
        )
    txn["lifecycle_state"] = "POSTED"
    txn["settlement_state"] = "SETTLED"
    touch(txn)

    # velocity counters take projected values (PRD §3.8): CHECK_CASH face only.
    customer["daily_transaction_count"] += 1
    if txn["txn_type"] == "CHECK_CASH":
        customer["daily_cashed_amount_cents"] += txn["face_amount_cents"]
    touch(customer)

    domain.recompute_drawer_expected_cash(drawer)

    if txn["txn_type"] != "CHECK_CASH":
        create_product_child(txn, None)
