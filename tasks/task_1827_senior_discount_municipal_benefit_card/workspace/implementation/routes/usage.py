from flask import Blueprint, request

import services
import store
from auth import authenticate, authorize
from errors import (
    ERR_CARDHOLDER_NOT_ACTIVE,
    ERR_CARDHOLDER_OWNERSHIP_MISMATCH,
    ERR_CARD_NOT_ACTIVE,
    ERR_CARD_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_MERCHANT_NOT_ACTIVE,
    ERR_MERCHANT_NOT_FOUND,
    ERR_MERCHANT_OWNERSHIP_MISMATCH,
    ERR_NO_ACTIVE_OFFER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TRANSACTION_NOT_FLAGGABLE,
    ERR_TRANSACTION_NOT_FOUND,
    ERR_TRANSACTION_NOT_VOIDABLE,
    ERR_VELOCITY_HARD_LIMIT,
    raise_err,
)
from util import (
    body_json,
    bump,
    get_or_404,
    list_response,
    new_record,
    opt_enum_query,
    req_enum,
    req_int,
    req_str,
    success_object,
)

bp = Blueprint("usage", __name__)

TXN_CATEGORIES = ("GROCERY", "PHARMACY", "DINING", "RETAIL", "SERVICES")
TXN_STATUSES = ("POSTED", "FLAGGED", "VOIDED")
READ_ROLES = ["MerchantOperator", "ProgramAdministrator", "FraudAnalyst", "Cardholder"]


@bp.route("/usage-transactions", methods=["POST"])
def create_transaction():
    uid, role = authenticate()
    authorize(role, ["MerchantOperator"])
    body = body_json()
    card_id = req_str(body, "card_id")
    merchant_id = req_str(body, "merchant_id")
    category = req_enum(body, "category", TXN_CATEGORIES)
    purchase = req_int(body, "purchase_amount_cents")
    if purchase <= 0:
        raise_err(ERR_INVALID_REQUEST, "purchase_amount_cents must be > 0")

    card = store.cards.get(card_id)
    if card is None:
        raise_err(ERR_CARD_NOT_FOUND, "Card not found: %s" % card_id)
    merchant = store.merchants.get(merchant_id)
    if merchant is None:
        raise_err(ERR_MERCHANT_NOT_FOUND, "Merchant not found: %s" % merchant_id)
    # standing checks, pinned order: card -> cardholder -> merchant
    if card["status"] != "ACTIVE":
        raise_err(ERR_CARD_NOT_ACTIVE, "Card is not ACTIVE")
    ch = store.cardholders.get(card["cardholder_id"])
    if ch is None or ch["status"] not in ("ACTIVE", "RECERTIFICATION_DUE"):
        raise_err(ERR_CARDHOLDER_NOT_ACTIVE,
                  "Cardholder standing does not permit usage")
    if merchant["status"] != "ACTIVE":
        raise_err(ERR_MERCHANT_NOT_ACTIVE, "Merchant is not ACTIVE")
    # ownership: the operator records sales only for their own merchant
    if uid != merchant_id:
        raise_err(ERR_MERCHANT_OWNERSHIP_MISMATCH,
                  "MerchantOperator may record usage only for their own merchant")
    # velocity hard limit (trailing 24h, candidate included)
    trailing, cal_day = services.velocity_counts(ch["id"])
    if trailing >= services.TRAILING_24H_REJECT_THRESHOLD:
        raise_err(ERR_VELOCITY_HARD_LIMIT,
                  "Trailing-24h transaction velocity limit reached")
    # offer resolution
    offer = services.select_offer(merchant_id, category)
    if offer is None:
        raise_err(ERR_NO_ACTIVE_OFFER,
                  "No ACTIVE offer covers this merchant and category today")
    discount = services.compute_discount_cents(offer, purchase, ch["id"])

    rec = new_record()
    rec.update({
        "card_id": card["id"],
        "merchant_id": merchant["id"],
        "cardholder_id": ch["id"],
        "offer_id": offer["id"],
        "category": category,
        "purchase_amount_cents": purchase,
        "discount_cents": discount,
        "status": "POSTED",
        "flagged_by_user_id": None,
        "flag_reason": None,
        "voided_by_user_id": None,
    })
    store.transactions[rec["id"]] = rec
    # calendar-day velocity: persist POSTED, then auto-flag when threshold met
    if cal_day >= services.CALENDAR_DAY_FLAG_THRESHOLD:
        rec["status"] = "FLAGGED"
        rec["flagged_by_user_id"] = "SYSTEM"
        rec["flag_reason"] = "VELOCITY_AUTO"
        bump(rec)
        services.after_transaction_flagged(ch)
    return success_object(services.transaction_out(rec), 201)


@bp.route("/usage-transactions", methods=["GET"])
def list_transactions():
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    f_card = request.args.get("card_id")
    f_cardholder = request.args.get("cardholder_id")
    f_merchant = request.args.get("merchant_id")
    f_offer = request.args.get("offer_id")
    f_status = opt_enum_query("status", TXN_STATUSES)

    items = list(store.transactions.values())
    if role == "MerchantOperator":
        if f_merchant is not None and f_merchant != uid:
            raise_err(ERR_MERCHANT_OWNERSHIP_MISMATCH,
                      "MerchantOperator may filter only by their own merchant_id")
        items = [t for t in items if t["merchant_id"] == uid]
    elif role == "Cardholder":
        if f_cardholder is not None and f_cardholder != uid:
            raise_err(ERR_CARDHOLDER_OWNERSHIP_MISMATCH,
                      "Cardholder may filter only by their own cardholder_id")
        items = [t for t in items if t["cardholder_id"] == uid]

    if f_card is not None:
        items = [t for t in items if t["card_id"] == f_card]
    if f_cardholder is not None:
        items = [t for t in items if t["cardholder_id"] == f_cardholder]
    if f_merchant is not None:
        items = [t for t in items if t["merchant_id"] == f_merchant]
    if f_offer is not None:
        items = [t for t in items if t["offer_id"] == f_offer]
    if f_status is not None:
        items = [t for t in items if t["status"] == f_status]
    return list_response(items, services.transaction_out)


@bp.route("/usage-transactions/<rid>", methods=["GET"])
def get_transaction(rid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    rec = get_or_404(store.transactions, rid, ERR_TRANSACTION_NOT_FOUND, "Transaction")
    if role == "MerchantOperator" and rec["merchant_id"] != uid:
        raise_err(ERR_MERCHANT_OWNERSHIP_MISMATCH,
                  "MerchantOperator may read only their own merchant's transactions")
    if role == "Cardholder" and rec["cardholder_id"] != uid:
        raise_err(ERR_CARDHOLDER_OWNERSHIP_MISMATCH,
                  "Cardholder may read only their own transactions")
    return success_object(services.transaction_out(rec))


@bp.route("/usage-transactions/<rid>/void", methods=["POST"])
def void_transaction(rid):
    uid, role = authenticate()
    authorize(role, ["MerchantOperator"])
    rec = get_or_404(store.transactions, rid, ERR_TRANSACTION_NOT_FOUND, "Transaction")
    if rec["status"] != "POSTED":
        raise_err(ERR_TRANSACTION_NOT_VOIDABLE,
                  "Only a POSTED transaction can be voided")
    if uid != rec["merchant_id"]:
        raise_err(ERR_MERCHANT_OWNERSHIP_MISMATCH,
                  "MerchantOperator may void only their own merchant's transactions")
    rec["status"] = "VOIDED"
    rec["voided_by_user_id"] = uid
    bump(rec)
    return success_object(services.transaction_out(rec))


@bp.route("/usage-transactions/<rid>/flag", methods=["POST"])
def flag_transaction(rid):
    uid, role = authenticate()
    authorize(role, ["FraudAnalyst"])
    rec = get_or_404(store.transactions, rid, ERR_TRANSACTION_NOT_FOUND, "Transaction")
    if rec["status"] != "POSTED":
        raise_err(ERR_TRANSACTION_NOT_FLAGGABLE,
                  "Only a POSTED transaction can be flagged")
    body = body_json()
    reason = req_str(body, "reason")
    rec["status"] = "FLAGGED"
    rec["flagged_by_user_id"] = uid
    rec["flag_reason"] = reason
    bump(rec)
    ch = store.cardholders.get(rec["cardholder_id"])
    if ch is not None:
        services.after_transaction_flagged(ch)
    return success_object(services.transaction_out(rec))


@bp.route("/usage-transactions/<rid>/clear-flag", methods=["POST"])
def clear_flag(rid):
    uid, role = authenticate()
    authorize(role, ["FraudAnalyst"])
    rec = get_or_404(store.transactions, rid, ERR_TRANSACTION_NOT_FOUND, "Transaction")
    if rec["status"] != "FLAGGED":
        raise_err(ERR_TRANSACTION_NOT_FLAGGABLE,
                  "Only a FLAGGED transaction can be cleared")
    if rec["flagged_by_user_id"] != "SYSTEM" and rec["flagged_by_user_id"] == uid:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "An analyst cannot clear a flag they raised")
    rec["status"] = "POSTED"
    rec["flagged_by_user_id"] = None
    rec["flag_reason"] = None
    bump(rec)
    ch = store.cardholders.get(rec["cardholder_id"])
    if ch is not None:
        services.after_transaction_unflagged(ch)
    return success_object(services.transaction_out(rec))
