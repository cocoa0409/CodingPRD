"""Transaction routes: create+post, get, list, void, return (PRD §3.4-3.7, §3.9).

The POST /transactions validation chain follows the fixed PRD §2.11 priority
order: auth -> role -> existence -> (fee schedule / drawer state / business
gates). For CHECK_CASH the gate order interleaves with the check-item hold fork
exactly as §3.4/§3.5 specify."""
from flask import Blueprint, request

import errors
from auth import require_auth, BOTH, MANAGER_ONLY
from db import db, new_id, common_fields, touch, serialize
from helpers import (
    get_json_body,
    parse_pagination,
    paginate,
    sort_by_creation,
    require_int,
    require_str,
    require_enum,
)
import lookups
from response import created, ok, listed
from services import calculations as calc
from services import domain
from services import posting

bp = Blueprint("transactions", __name__)

TXN_TYPES = {"CHECK_CASH", "MONEY_ORDER", "WIRE", "BILL_PAY", "PREPAID_LOAD"}
MAKER_RISKS = {"LOW", "MEDIUM", "HIGH"}
RETURN_REASONS = {"NSF", "ACCOUNT_CLOSED", "STOP_PAYMENT", "FRAUD"}


def _serialize_txn(t):
    return serialize(t)


@bp.route("/transactions", methods=["POST"])
def create_transaction():
    caller = require_auth(BOTH)
    body = get_json_body()

    # --- body shape validation (ERR_VALIDATION) ---
    txn_type = require_enum(body, "txn_type", TXN_TYPES)
    customer_id = require_str(body, "customer_id")
    drawer_id = require_str(body, "drawer_id")
    face_amount_cents = require_int(body, "face_amount_cents", minimum=1)
    fee_schedule_id = require_str(body, "fee_schedule_id", required=False, allow_none=True)

    maker_account_risk = None
    if txn_type == "CHECK_CASH":
        maker_account_risk = require_enum(body, "maker_account_risk", MAKER_RISKS)

    # product-specific required fields (validated as shape before gating)
    payee_name = destination_country = beneficiary_name = None
    biller_code = account_reference = card_last_four = None
    if txn_type == "MONEY_ORDER":
        payee_name = require_str(body, "payee_name")
    elif txn_type == "WIRE":
        destination_country = require_str(body, "destination_country")
        beneficiary_name = require_str(body, "beneficiary_name")
    elif txn_type == "BILL_PAY":
        biller_code = require_str(body, "biller_code")
        account_reference = require_str(body, "account_reference")
    elif txn_type == "PREPAID_LOAD":
        card_last_four = require_str(body, "card_last_four")

    # --- priority 3: existence (left to right: customer, drawer, fee schedule) ---
    customer = lookups.get_customer(customer_id)
    drawer = lookups.get_drawer(drawer_id)
    schedule = None
    if fee_schedule_id is not None:
        schedule = lookups.get_fee_schedule(fee_schedule_id)

    # priority 4 (state) does not apply to creation.

    # priority 5 (segregation) does not apply to creation.

    # --- priority 6: KYC gate ---
    if customer["kyc_status"] != "VERIFIED":
        raise errors.err(errors.ERR_KYC_NOT_VERIFIED, "Customer KYC is not VERIFIED")

    # --- priority 7: OFAC block ---
    if customer["kyc_status"] == "OFAC_BLOCKED":
        raise errors.err(errors.ERR_OFAC_BLOCKED, "Customer is OFAC blocked")

    # --- priority 8: fee schedule validity ---
    if txn_type == "CHECK_CASH":
        if fee_schedule_id is None or schedule is None or not schedule["active"]:
            raise errors.err(
                errors.ERR_FEE_SCHEDULE_INVALID,
                "CHECK_CASH requires an active fee_schedule_id",
            )
    else:
        if fee_schedule_id is not None:
            raise errors.err(
                errors.ERR_FEE_SCHEDULE_INVALID,
                "fee_schedule_id must be null for non-CHECK_CASH transactions",
            )

    # --- priority 9: drawer open ---
    if drawer["status"] != "OPEN":
        raise errors.err(errors.ERR_DRAWER_NOT_OPEN, "Drawer is not OPEN")

    # --- priority 10: embargoed wire destination ---
    if txn_type == "WIRE" and destination_country in calc.EMBARGOED_COUNTRIES:
        raise errors.err(errors.ERR_EMBARGOED_DESTINATION, "Wire destination is embargoed")

    # --- priority 11: per-transaction risk-tier ceiling ---
    ceiling = calc.ceiling_for_tier(customer["risk_tier"])
    if face_amount_cents > ceiling:
        raise errors.err(
            errors.ERR_RISK_CEILING_EXCEEDED,
            "face_amount_cents exceeds the risk-tier ceiling",
        )

    # --- priority 12/13/17: rolling-window velocity ---
    domain.roll_velocity_window_if_needed(customer)
    projected_count = customer["daily_transaction_count"] + 1
    if projected_count > calc.DAILY_TXN_LIMIT:
        raise errors.err(
            errors.ERR_VELOCITY_LIMIT_EXCEEDED, "Daily transaction limit exceeded"
        )
    if txn_type == "CHECK_CASH":
        projected_cashed = customer["daily_cashed_amount_cents"] + face_amount_cents
        if projected_cashed > calc.DAILY_CASH_LIMIT_CENTS:
            raise errors.err(
                errors.ERR_DAILY_LIMIT_EXCEEDED, "Daily cash limit exceeded"
            )

    # --- build the transaction (DRAFT/UNSETTLED) ---
    tid = new_id()
    txn = {
        "id": tid,
        "customer_id": customer_id,
        "drawer_id": drawer_id,
        "txn_type": txn_type,
        "face_amount_cents": face_amount_cents,
        "fee_schedule_id": fee_schedule_id,
        "fee_cents": 0,
        "net_disbursed_cents": 0,
        "lifecycle_state": "DRAFT",
        "settlement_state": "UNSETTLED",
        # internal, never serialized:
        "_creating_teller_id": caller.user_id,
        "_schedule": schedule,
        "_payee_name": payee_name,
        "_destination_country": destination_country,
        "_beneficiary_name": beneficiary_name,
        "_biller_code": biller_code,
        "_account_reference": account_reference,
        "_card_last_four": card_last_four,
    }
    txn.update(common_fields())
    db.transactions[tid] = txn

    if txn_type == "CHECK_CASH":
        _handle_check_cash(txn, customer, drawer, maker_account_risk)
    else:
        posting.post_transaction(txn, customer, drawer)

    return created(_serialize_txn(txn))


def _handle_check_cash(txn, customer, drawer, maker_account_risk):
    """Create the CheckItem and fork on the hold conditions (PRD §3.5).
    Hold if face >= 300000, OR maker HIGH, OR daily_transaction_count >= 8.
    hold_reason = first matching in that exact order."""
    cid = new_id()
    check_item = {
        "id": cid,
        "transaction_id": txn["id"],
        "check_face_cents": txn["face_amount_cents"],
        "maker_account_risk": maker_account_risk,
        "verification_state": "VERIFYING",
        "hold_reason": None,
    }
    check_item.update(common_fields())
    db.check_items[cid] = check_item

    # PRD §3.4: fee_cents and net_disbursed_cents are computed at creation for
    # every check-cash (the fee is fixed; only whether it affects the drawer
    # depends on POSTED state).
    txn["fee_cents"] = posting.compute_fee(
        txn["txn_type"], txn["face_amount_cents"], txn.get("_schedule")
    )
    txn["net_disbursed_cents"] = calc.net_disbursed(
        txn["txn_type"], txn["face_amount_cents"], txn["fee_cents"]
    )
    touch(txn)

    hold_reason = None
    if txn["face_amount_cents"] >= calc.HOLD_THRESHOLD_CENTS:
        hold_reason = "AMOUNT_THRESHOLD"
    elif maker_account_risk == "HIGH":
        hold_reason = "MAKER_RISK"
    elif customer["daily_transaction_count"] >= calc.VELOCITY_HOLD_COUNT:
        hold_reason = "VELOCITY"

    if hold_reason is not None:
        # RISK_HELD: no cash moves, transaction stays DRAFT, provisional risk
        # is NOT written to the confirmed score.
        check_item["verification_state"] = "RISK_HELD"
        check_item["hold_reason"] = hold_reason
        touch(check_item)
    else:
        # auto-clear: CheckItem -> CLEARED and post the transaction.
        # fee/net already computed above; do not recompute.
        check_item["verification_state"] = "CLEARED"
        touch(check_item)
        posting.post_transaction(txn, customer, drawer, compute=False)


@bp.route("/transactions/<tid>", methods=["GET"])
def get_transaction(tid):
    require_auth(BOTH)
    txn = lookups.get_transaction(tid)
    return ok(_serialize_txn(txn))


@bp.route("/transactions", methods=["GET"])
def list_transactions():
    require_auth(BOTH)
    limit, offset = parse_pagination()
    items = list(db.transactions.values())

    for field in ("customer_id", "drawer_id", "fee_schedule_id", "txn_type"):
        val = request.args.get(field)
        if val is not None:
            items = [t for t in items if t.get(field) == val]

    items = sort_by_creation(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return listed([_serialize_txn(t) for t in page], limit, offset, total)


@bp.route("/transactions/<tid>/void", methods=["POST"])
def void_transaction(tid):
    caller = require_auth(MANAGER_ONLY)
    txn = lookups.get_transaction(tid)

    # priority 4: must be POSTED, and settlement not RETURNED/RECOVERED
    if txn["lifecycle_state"] != "POSTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Transaction is not POSTED")
    if txn["settlement_state"] in ("RETURNED", "RECOVERED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Transaction has been returned/recovered")

    # priority 5: segregation of duties
    if caller.user_id == txn["_creating_teller_id"]:
        raise errors.err(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "Voider must differ from the creating Teller",
        )

    # priority 9: drawer must be OPEN
    drawer = lookups.get_drawer(txn["drawer_id"])
    if drawer["status"] != "OPEN":
        raise errors.err(errors.ERR_DRAWER_NOT_OPEN, "Drawer is not OPEN")

    # void: lifecycle -> VOIDED; product child -> voided form
    txn["lifecycle_state"] = "VOIDED"
    touch(txn)
    _void_product_child(txn)

    # recompute drawer expected cash (reverse net impact via re-aggregation)
    domain.recompute_drawer_expected_cash(drawer)

    # compensation: decrement customer velocity counters
    customer = lookups.get_customer(txn["customer_id"])
    customer["daily_transaction_count"] -= 1
    if txn["txn_type"] == "CHECK_CASH":
        customer["daily_cashed_amount_cents"] -= txn["face_amount_cents"]
    touch(customer)

    return ok(_serialize_txn(txn))


def _void_product_child(txn):
    tid = txn["id"]
    txn_type = txn["txn_type"]
    if txn_type == "MONEY_ORDER":
        for child in db.money_orders.values():
            if child["transaction_id"] == tid:
                child["status"] = "VOIDED"
                touch(child)
    elif txn_type == "WIRE":
        for child in db.wire_transfers.values():
            if child["transaction_id"] == tid:
                child["status"] = "RECALLED"
                touch(child)
    elif txn_type == "BILL_PAY":
        for child in db.bill_payments.values():
            if child["transaction_id"] == tid:
                child["status"] = "VOIDED"
                touch(child)
    elif txn_type == "PREPAID_LOAD":
        for child in db.prepaid_card_loads.values():
            if child["transaction_id"] == tid:
                child["status"] = "REVERSED"
                touch(child)


@bp.route("/transactions/<tid>/return", methods=["POST"])
def return_transaction(tid):
    require_auth(MANAGER_ONLY)
    txn = lookups.get_transaction(tid)
    body = get_json_body()
    return_reason = require_enum(body, "return_reason", RETURN_REASONS)

    # priority 4: must be CHECK_CASH, POSTED + SETTLED
    if txn["txn_type"] != "CHECK_CASH":
        raise errors.err(errors.ERR_INVALID_STATE, "Only CHECK_CASH can be returned")
    if not (txn["lifecycle_state"] == "POSTED" and txn["settlement_state"] == "SETTLED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Transaction is not POSTED+SETTLED")

    customer = lookups.get_customer(txn["customer_id"])

    # settlement -> RETURNED
    txn["settlement_state"] = "RETURNED"
    touch(txn)

    # create the ReturnedItem (status OUTSTANDING)
    rid = new_id()
    return_fee = calc.RETURN_FEE_CENTS
    returned_item = {
        "id": rid,
        "transaction_id": tid,
        "customer_id": txn["customer_id"],
        "return_reason": return_reason,
        "return_fee_cents": return_fee,
        "recovered_cents": 0,
        "status": "OUTSTANDING",
        "_total_owed": txn["face_amount_cents"] + return_fee,
    }
    returned_item.update(common_fields())
    db.returned_items[rid] = returned_item

    # cascade hop 1: outstanding_recovery_cents += (face + return_fee)
    customer["outstanding_recovery_cents"] += txn["face_amount_cents"] + return_fee
    touch(customer)

    # cascade hop 2: confirmed risk += RETURN_RISK_DELTA (may bump tier)
    domain.apply_risk_delta(customer, calc.RETURN_RISK_DELTA)

    return created(serialize(returned_item))
