"""CardTransaction and Dispute endpoints (PRD 3.5, 3.6)."""

import json
from datetime import timedelta

from flask import Blueprint, g, request

from db import store
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE_TRANSITION, ERR_IDEMPOTENCY_CONFLICT,
    ERR_CARD_NOT_ACTIVE, ERR_CARD_FROZEN, ERR_HOLDER_NOT_ACTIVE,
    ERR_MERCHANT_NOT_ACTIVE, ERR_TERM_NOT_OPEN, ERR_ENROLLMENT_NOT_ACTIVE,
    ERR_ACCOUNT_FROZEN, ERR_FRAUD_HOLD, ERR_TX_NOT_DISPUTABLE,
    ERR_DISPUTE_ALREADY_OPEN, ERR_DISPUTE_WINDOW_CLOSED,
    ERR_CREDIT_NOT_APPLICABLE, ERR_SOD_RESOLVER_IS_GRANTER,
    ERR_INSUFFICIENT_FUNDS, ERR_SWIPES_EXHAUSTED, ERR_PROVISIONAL_DAILY_CAP,
)
from middleware import (
    authenticate, require_roles, get_body, v_str, v_int, v_enum, find_or_404,
    pub, paginate,
)
from response import success
from services.core import (
    new_row, touch, clock, dt_of, lazy_expire_card,
)
from services.cascades import add_fraud_strike
from services.ledger import post_entry
from services.pricing import (
    provisional_day_total, PROVISIONAL_DAILY_CAP_CENTS, DISPUTE_WINDOW_DAYS,
)

bp = Blueprint("transactions", __name__)

TENDER_TYPES = {"MEAL_SWIPE", "DINING_DOLLARS", "CAMPUS_CASH"}
REASON_CODES = {"UNAUTHORIZED_USE", "DUPLICATE_CHARGE", "AMOUNT_MISMATCH",
                "SERVICE_NOT_RECEIVED"}
DISPUTE_OPEN_STATES = {"OPENED", "PROVISIONAL_CREDIT_GRANTED"}


def _current_open_term():
    """The current term for dining/swipe derivation: the (first-created) OPEN term."""
    opens = [t for t in store.terms.values() if t["status"] == "OPEN"]
    if not opens:
        return None
    return sorted(opens, key=lambda t: (t["created_at"], t["_seq"]))[0]


# --------------------------------------------------------------- transactions
@bp.route("/api/transactions", methods=["POST"])
def create_transaction():
    authenticate()
    require_roles("PointOfSale", "MerchantUser")
    body = get_body()
    # Priority 3: MerchantUser must pass merchant_id equal to its own id.
    merchant_id = body.get("merchant_id")
    if (g.role == "MerchantUser" and merchant_id is not None
            and merchant_id != g.user_id):
        err(ERR_NOT_RESOURCE_OWNER,
            "MerchantUser may post only with its own merchant id")
    # Priority 4: body well-formedness.
    card_id = v_str(body, "card_id")
    tender_type = v_enum(body, "tender_type", TENDER_TYPES)
    if "amount_cents" not in body or body["amount_cents"] is None:
        err(ERR_VALIDATION, "Missing required field: amount_cents")
    amount_cents = body["amount_cents"]
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        err(ERR_VALIDATION, "amount_cents must be an integer")
    if tender_type == "MEAL_SWIPE":
        if amount_cents != 0:
            err(ERR_VALIDATION, "amount_cents must be exactly 0 for MEAL_SWIPE")
    elif amount_cents <= 0:
        err(ERR_VALIDATION, "amount_cents must be positive")
    idempotency_key = v_str(body, "idempotency_key")
    location_description = v_str(body, "location_description", required=False)
    if g.role == "MerchantUser":
        if merchant_id is None:
            err(ERR_VALIDATION, "MerchantUser must pass merchant_id")
        if not isinstance(merchant_id, str):
            err(ERR_VALIDATION, "merchant_id must be a string")
    else:  # PointOfSale must omit merchant_id
        if merchant_id is not None:
            err(ERR_VALIDATION, "PointOfSale postings must omit merchant_id")
    # Priority 6: body-referenced ids exist.
    card = find_or_404(store.cards, card_id)
    merchant = None
    if g.role == "MerchantUser":
        merchant = find_or_404(store.merchants, merchant_id)
    # Priority 7: idempotency.
    idem_key = f"transaction:{idempotency_key}"
    payload = json.dumps({"body": body, "role": g.role}, sort_keys=True)
    prior = store.idempotency.get(idem_key)
    if prior is not None:
        if prior["payload"] == payload:
            return success(prior["data"], 201)
        err(ERR_IDEMPOTENCY_CONFLICT,
            "idempotency_key was already used with a divergent payload")
    # Priority 10: cross-entity referenced state. A card touched at/after
    # expires_at flips to EXPIRED first and fails as not active.
    lazy_expire_card(card)
    if card["lifecycle_status"] in ("LOST_FROZEN", "STOLEN_FROZEN"):
        err(ERR_CARD_FROZEN, "Card is frozen")
    if card["lifecycle_status"] != "ACTIVE":
        err(ERR_CARD_NOT_ACTIVE, "Card is not ACTIVE")
    holder = store.holders[card["holder_id"]]
    if holder["status"] != "ACTIVE":
        err(ERR_HOLDER_NOT_ACTIVE, "Holder is not ACTIVE")
    if merchant is not None and merchant["status"] != "ACTIVE":
        err(ERR_MERCHANT_NOT_ACTIVE, "Merchant is not ACTIVE")
    # Derivation of account / enrollment from tender type and current term.
    account = None
    enrollment = None
    if tender_type == "MEAL_SWIPE":
        term = _current_open_term()
        if term is None:
            err(ERR_TERM_NOT_OPEN, "No term is OPEN for swipe derivation")
        for e in store.enrollments.values():
            if (e["holder_id"] == holder["id"] and e["term_id"] == term["id"]
                    and e["status"] == "ACTIVE"):
                enrollment = e
                break
        if enrollment is None:
            err(ERR_ENROLLMENT_NOT_ACTIVE,
                "No ACTIVE enrollment in the current term")
    else:
        if tender_type == "DINING_DOLLARS":
            term = _current_open_term()
            if term is None:
                err(ERR_TERM_NOT_OPEN, "No term is OPEN for dining derivation")
            for a in store.accounts.values():
                if (a["holder_id"] == holder["id"]
                        and a["account_type"] == "DINING_DOLLARS"
                        and a.get("term_id") == term["id"]
                        and a["status"] in ("OPEN", "FROZEN", "CLOSE_PENDING")):
                    account = a
                    break
        else:
            for a in store.accounts.values():
                if (a["holder_id"] == holder["id"]
                        and a["account_type"] == "CAMPUS_CASH"
                        and a["status"] in ("OPEN", "FROZEN", "CLOSE_PENDING")):
                    account = a
                    break
        if account is None or account["status"] != "OPEN":
            err(ERR_ACCOUNT_FROZEN, "The resolved account is not OPEN")
    # Priority 11: fraud hold on value-extending actions.
    if holder["status"] == "SUSPENDED" or holder["fraud_flag"]:
        err(ERR_FRAUD_HOLD, "Holder is under a fraud hold")
    # Priority 14: funds and thresholds.
    if tender_type == "MEAL_SWIPE":
        if not enrollment["is_unlimited_swipes"]:
            if enrollment["swipes_used_this_week"] >= enrollment["weekly_swipe_allowance"]:
                err(ERR_SWIPES_EXHAUSTED, "Weekly swipe allowance is exhausted")
    else:
        if amount_cents > account["balance_cents"]:
            err(ERR_INSUFFICIENT_FUNDS, "Purchase amount exceeds the account balance")
        if card["is_provisional"]:
            day_total = provisional_day_total(card["id"])
            if day_total + amount_cents > PROVISIONAL_DAILY_CAP_CENTS:
                err(ERR_PROVISIONAL_DAILY_CAP,
                    "Provisional daily cap would be exceeded")
    # Post the transaction.
    tx = new_row()
    tx.update({
        "card_id": card["id"],
        "account_id": account["id"] if account is not None else None,
        "enrollment_id": enrollment["id"] if enrollment is not None else None,
        "merchant_id": merchant["id"] if merchant is not None else None,
        "tender_type": tender_type,
        "amount_cents": amount_cents,
        "idempotency_key": idempotency_key,
        "location_description": location_description,
        "status": "POSTED" if merchant is not None else "SETTLED",
        "pre_dispute_status": None,
        "settled_in_settlement_id": None,
    })
    store.transactions[tx["id"]] = tx
    if tender_type == "MEAL_SWIPE":
        enrollment["swipes_used_this_week"] += 1
        touch(enrollment)
    else:
        post_entry(account, "PURCHASE", amount_cents,
                   f"Card purchase for transaction {tx['id']}",
                   reference_transaction_id=tx["id"])
    data = pub(tx)
    store.idempotency[idem_key] = {"payload": payload, "data": data}
    return success(data, 201)


def _tx_visible(tx):
    if g.role == "CardHolder":
        card = store.cards.get(tx["card_id"])
        return card is not None and card["holder_id"] == g.user_id
    if g.role == "MerchantUser":
        return tx.get("merchant_id") == g.user_id
    return True


@bp.route("/api/transactions", methods=["GET"])
def list_transactions():
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "BursarOffice",
                  "FraudAnalyst", "CardHolder", "MerchantUser")
    rows = [t for t in store.transactions.values() if _tx_visible(t)]
    card_id = request.args.get("card_id")
    account_id = request.args.get("account_id")
    enrollment_id = request.args.get("enrollment_id")
    merchant_id = request.args.get("merchant_id")
    settlement_id = request.args.get("settled_in_settlement_id")
    status = request.args.get("status")
    if card_id is not None:
        if g.role == "CardHolder":
            target = store.cards.get(card_id)
            if target is not None and target["holder_id"] != g.user_id:
                err(ERR_NOT_RESOURCE_OWNER, "Cannot filter by another holder's card")
        rows = [t for t in rows if t["card_id"] == card_id]
    if account_id is not None:
        if g.role == "CardHolder":
            target = store.accounts.get(account_id)
            if target is not None and target["holder_id"] != g.user_id:
                err(ERR_NOT_RESOURCE_OWNER, "Cannot filter by another holder's account")
        rows = [t for t in rows if t.get("account_id") == account_id]
    if enrollment_id is not None:
        rows = [t for t in rows if t.get("enrollment_id") == enrollment_id]
    if merchant_id is not None:
        if g.role == "MerchantUser" and merchant_id != g.user_id:
            err(ERR_NOT_RESOURCE_OWNER, "Cannot filter by another merchant")
        rows = [t for t in rows if t.get("merchant_id") == merchant_id]
    if settlement_id is not None:
        rows = [t for t in rows if t.get("settled_in_settlement_id") == settlement_id]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/transactions/<tid>", methods=["GET"])
def get_transaction(tid):
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "BursarOffice",
                  "FraudAnalyst", "CardHolder", "MerchantUser")
    tx = store.transactions.get(tid)
    if tx is not None and not _tx_visible(tx):
        err(ERR_NOT_RESOURCE_OWNER, "Not the owner of this transaction")
    if tx is None:
        err(ERR_NOT_FOUND, "Transaction not found")
    return success(pub(tx), 200)


# ------------------------------------------------------------------- disputes
@bp.route("/api/transactions/<tid>/disputes", methods=["POST"])
def create_dispute(tid):
    authenticate()
    require_roles("CardHolder")
    tx = store.transactions.get(tid)
    if tx is not None:
        card = store.cards.get(tx["card_id"])
        if card is None or card["holder_id"] != g.user_id:
            err(ERR_NOT_RESOURCE_OWNER,
                "CardHolder may dispute only its own transactions")
    body = get_body()
    reason_code = v_enum(body, "reason_code", REASON_CODES)
    if tx is None:
        err(ERR_NOT_FOUND, "Transaction not found")
    # Priority 12: filing window.
    if clock() > dt_of(tx, "created_at") + timedelta(days=DISPUTE_WINDOW_DAYS):
        err(ERR_DISPUTE_WINDOW_CLOSED,
            "Dispute filed after the filing window")
    # Priority 13: uniqueness and disputable-state checks.
    for d in store.disputes.values():
        if d["transaction_id"] == tx["id"] and d["status"] in DISPUTE_OPEN_STATES:
            err(ERR_DISPUTE_ALREADY_OPEN,
                "A non-terminal dispute already exists on the transaction")
    if tx["status"] == "REVERSED":
        err(ERR_TX_NOT_DISPUTABLE, "A REVERSED transaction cannot be disputed")
    if tx.get("settled_in_settlement_id"):
        settlement = store.settlements.get(tx["settled_in_settlement_id"])
        if settlement is not None and settlement["status"] in ("APPROVED", "PAID"):
            err(ERR_TX_NOT_DISPUTABLE,
                "Transaction is locked in an APPROVED or PAID settlement")
    tx["pre_dispute_status"] = tx["status"]
    tx["status"] = "UNDER_DISPUTE"
    touch(tx)
    dispute = new_row()
    dispute.update({
        "transaction_id": tx["id"],
        "filed_by_holder_id": g.user_id,
        "reason_code": reason_code,
        "status": "OPENED",
        "provisional_credit_cents": 0,
        "granter_analyst_id": None,
        "resolver_analyst_id": None,
        "resolution_note": None,
    })
    store.disputes[dispute["id"]] = dispute
    return success(pub(dispute), 201)


def _own_dispute_or_403(dispute):
    if g.role == "CardHolder" and dispute["filed_by_holder_id"] != g.user_id:
        err(ERR_NOT_RESOURCE_OWNER, "CardHolder may act only on its own disputes")


@bp.route("/api/disputes", methods=["GET"])
def list_disputes():
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "BursarOffice",
                  "FraudAnalyst", "CardHolder")
    rows = list(store.disputes.values())
    if g.role == "CardHolder":
        rows = [d for d in rows if d["filed_by_holder_id"] == g.user_id]
    transaction_id = request.args.get("transaction_id")
    holder_id = request.args.get("filed_by_holder_id")
    status = request.args.get("status")
    if transaction_id is not None:
        rows = [d for d in rows if d["transaction_id"] == transaction_id]
    if holder_id is not None:
        if g.role == "CardHolder" and holder_id != g.user_id:
            err(ERR_NOT_RESOURCE_OWNER, "Cannot filter by another holder")
        rows = [d for d in rows if d["filed_by_holder_id"] == holder_id]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/disputes/<did>", methods=["GET"])
def get_dispute(did):
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "BursarOffice",
                  "FraudAnalyst", "CardHolder")
    dispute = store.disputes.get(did)
    if dispute is not None:
        _own_dispute_or_403(dispute)
    if dispute is None:
        err(ERR_NOT_FOUND, "Dispute not found")
    return success(pub(dispute), 200)


def _mark_carryover(tx):
    """When a disputed transaction is restored, it becomes a carried candidate
    for the merchant's next sweep if a settlement previously excluded it."""
    if tx.get("_excluded_by_settlement_id"):
        tx["_carried"] = True


def _restore_transaction(dispute, tx, clawback):
    """Restore the transaction to its pre-dispute status; optionally claw back
    the provisional credit."""
    if clawback and dispute["provisional_credit_cents"] > 0:
        acct = store.accounts.get(tx.get("account_id"))
        if acct is not None:
            post_entry(acct, "PROVISIONAL_CLAWBACK",
                       dispute["provisional_credit_cents"],
                       f"Provisional credit clawback for dispute {dispute['id']}",
                       reference_transaction_id=tx["id"],
                       reference_dispute_id=dispute["id"])
    tx["status"] = tx["pre_dispute_status"]
    touch(tx)
    _mark_carryover(tx)


@bp.route("/api/disputes/<did>/grant-provisional-credit", methods=["POST"])
def grant_provisional_credit(did):
    authenticate()
    require_roles("FraudAnalyst")
    dispute = find_or_404(store.disputes, did)
    if dispute["status"] != "OPENED":
        err(ERR_INVALID_STATE_TRANSITION,
            "Only an OPENED dispute can receive provisional credit")
    tx = store.transactions[dispute["transaction_id"]]
    if tx["tender_type"] == "MEAL_SWIPE":
        err(ERR_CREDIT_NOT_APPLICABLE,
            "Provisional credit is not applicable to meal swipes")
    acct = store.accounts[tx["account_id"]]
    post_entry(acct, "PROVISIONAL_CREDIT", tx["amount_cents"],
               f"Provisional credit for dispute {dispute['id']}",
               reference_transaction_id=tx["id"],
               reference_dispute_id=dispute["id"])
    dispute["provisional_credit_cents"] = tx["amount_cents"]
    dispute["granter_analyst_id"] = g.user_id
    dispute["status"] = "PROVISIONAL_CREDIT_GRANTED"
    touch(dispute)
    return success(pub(dispute), 200)


@bp.route("/api/disputes/<did>/resolve", methods=["POST"])
def resolve_dispute(did):
    authenticate()
    require_roles("FraudAnalyst")
    body = get_body()
    outcome = v_enum(body, "outcome", {"FOR_CARDHOLDER", "FOR_MERCHANT"})
    resolution_note = v_str(body, "resolution_note")
    dispute = find_or_404(store.disputes, did)
    if dispute["status"] not in DISPUTE_OPEN_STATES:
        err(ERR_INVALID_STATE_TRANSITION,
            "Only an open dispute can be resolved")
    had_credit = dispute["status"] == "PROVISIONAL_CREDIT_GRANTED"
    if had_credit and dispute["granter_analyst_id"] == g.user_id:
        err(ERR_SOD_RESOLVER_IS_GRANTER,
            "The resolving analyst must differ from the provisional credit granter")
    tx = store.transactions[dispute["transaction_id"]]
    if outcome == "FOR_CARDHOLDER":
        dispute["status"] = "RESOLVED_FOR_CARDHOLDER"
        tx["status"] = "REVERSED"
        touch(tx)
        if not had_credit and tx["tender_type"] != "MEAL_SWIPE":
            acct = store.accounts.get(tx.get("account_id"))
            if acct is not None:
                post_entry(acct, "PURCHASE_REVERSAL", tx["amount_cents"],
                           f"Purchase reversal for dispute {dispute['id']}",
                           reference_transaction_id=tx["id"])
        # With provisional credit already posted, the credit becomes permanent.
    else:
        dispute["status"] = "RESOLVED_FOR_MERCHANT"
        _restore_transaction(dispute, tx, clawback=had_credit)
        if dispute["reason_code"] == "UNAUTHORIZED_USE":
            holder = store.holders.get(dispute["filed_by_holder_id"])
            if holder is not None:
                add_fraud_strike(holder)
    dispute["resolver_analyst_id"] = g.user_id
    dispute["resolution_note"] = resolution_note
    touch(dispute)
    return success(pub(dispute), 200)


@bp.route("/api/disputes/<did>/withdraw", methods=["POST"])
def withdraw_dispute(did):
    authenticate()
    require_roles("CardHolder")
    dispute = store.disputes.get(did)
    if dispute is not None:
        _own_dispute_or_403(dispute)
    if dispute is None:
        err(ERR_NOT_FOUND, "Dispute not found")
    if dispute["status"] not in DISPUTE_OPEN_STATES:
        err(ERR_INVALID_STATE_TRANSITION,
            "Only an open dispute can be withdrawn")
    had_credit = dispute["status"] == "PROVISIONAL_CREDIT_GRANTED"
    tx = store.transactions[dispute["transaction_id"]]
    _restore_transaction(dispute, tx, clawback=had_credit)
    dispute["status"] = "WITHDRAWN"
    touch(dispute)
    return success(pub(dispute), 200)
