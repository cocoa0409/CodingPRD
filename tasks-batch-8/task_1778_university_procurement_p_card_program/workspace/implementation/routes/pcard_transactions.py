"""P-card transactions: posting gates, reconciliation (grant allowability),
disputes, and dispute resolution (PRD 3.7/3.8)."""

import db
import services as svc
from middleware import authenticate, ROLES
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    apply_filters,
    require_fk,
    dt_of,
)
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_CARD_CLOSED,
    ERR_CARD_NOT_ACTIVE,
    ERR_MCC_NOT_ALLOWED,
    ERR_SINGLE_TXN_LIMIT_EXCEEDED,
    ERR_MONTHLY_LIMIT_EXCEEDED,
    ERR_TXN_NOT_RECONCILABLE,
    ERR_TXN_NOT_DISPUTABLE,
    ERR_TXN_NOT_DISPUTED,
    ERR_GRANT_NOT_ACTIVE,
    ERR_GRANT_CATEGORY_NOT_ALLOWABLE,
    ERR_GRANT_BUDGET_PERIOD_EXPIRED,
    ERR_GRANT_BUDGET_EXCEEDED,
)

bp = make_blueprint("pcard_transactions")

ENTRY_TYPES = ["DEBIT", "CREDIT"]
ALLOCATION_TYPES = ["GENERAL", "GRANT"]


def _check_card_holder(card, user_id):
    """Cardholder identity is entity-backed: X-User-ID must equal the card id."""
    if card["id"] != user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "a cardholder may only act on their own card")


@bp.post("/pcards/<cid>/transactions")
def post_transaction(cid):
    user_id, _ = authenticate(["Cardholder"])
    card = require_fk("pcards", cid)
    _check_card_holder(card, user_id)  # p4 ownership
    if card["status"] == "CLOSED":
        raise ApiError(ERR_CARD_CLOSED, 409, "card is CLOSED")
    if card["status"] != "ACTIVE":
        raise ApiError(ERR_CARD_NOT_ACTIVE, 409, "transaction posting requires an ACTIVE card")
    body = body_json()
    check_shape(body, {
        "amount_cents": {"type": "integer", "required": True, "min_exclusive": 0},
        "entry_type": {"type": "enum", "values": ENTRY_TYPES, "required": True},
        "merchant_name": {"type": "string", "required": True},
        "mcc_code": {"type": "string", "required": True},
    })
    # p7 compliance: MCC restriction only bites when the card configures one.
    if card["allowed_mccs"] and body["mcc_code"] not in card["allowed_mccs"]:
        raise ApiError(ERR_MCC_NOT_ALLOWED, 422, "mcc_code is not allowed on this card")
    amount = body["amount_cents"]
    if body["entry_type"] == "DEBIT":
        # p11 fiscal, inclusive boundaries on both ceilings.
        if amount > svc.effective_single_limit(card):
            raise ApiError(ERR_SINGLE_TXN_LIMIT_EXCEEDED, 422, "amount exceeds the effective single-transaction limit")
        if svc.card_utilization(card) + amount > card["monthly_limit_cents"]:
            raise ApiError(ERR_MONTHLY_LIMIT_EXCEEDED, 422, "amount exceeds the monthly limit")
    txn = db.new_entity("pcard_transactions", {
        "pcard_id": card["id"],
        "amount_cents": amount,
        "entry_type": body["entry_type"],
        "merchant_name": body["merchant_name"],
        "mcc_code": body["mcc_code"],
        "posted_at": db.logical_ts(),
        "cycle_index": card["cycle_index"],
        "status": "POSTED" if body["entry_type"] == "DEBIT" else "RECONCILED",
        "pre_dispute_status": None,
        "receipt_reference": None,
        "allocation_type": None,
        "grant_id": None,
        "cost_category": None,
        "reconciled_at": None,
    })
    return success_obj(db.public(txn), 201)


@bp.get("/pcards/<cid>/transactions")
def list_card_transactions(cid):
    authenticate(ROLES)
    card = require_fk("pcards", cid)
    limit, offset = pagination_params()
    items = apply_filters(svc.txns_of_card(card["id"]), ["status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(t) for t in page], limit, offset, total, has_more)


@bp.get("/pcard-transactions")
def list_transactions():
    authenticate(ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("pcard_transactions"), ["pcard_id", "grant_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(t) for t in page], limit, offset, total, has_more)


@bp.get("/pcard-transactions/<tid>")
def get_transaction(tid):
    authenticate(ROLES)
    txn = require_fk("pcard_transactions", tid)
    return success_obj(db.public(txn), 200)


@bp.post("/pcard-transactions/<tid>/reconcile")
def reconcile_transaction(tid):
    user_id, _ = authenticate(["Cardholder"])
    txn = require_fk("pcard_transactions", tid)
    card = db.get("pcards", txn["pcard_id"])
    body = body_json()
    # p3: a GRANT allocation's grant reference exists.
    if body.get("allocation_type") == "GRANT" and isinstance(body.get("grant_id"), str):
        require_fk("grants", body["grant_id"])
    _check_card_holder(card, user_id)  # p4
    if txn["status"] != "POSTED":
        raise ApiError(ERR_TXN_NOT_RECONCILABLE, 409, "reconcile requires a POSTED transaction")
    if card["status"] == "CLOSED":
        raise ApiError(ERR_CARD_CLOSED, 409, "card is CLOSED")
    check_shape(body, {
        "receipt_reference": {"type": "string", "required": True, "non_empty": True},
        "allocation_type": {"type": "enum", "values": ALLOCATION_TYPES, "required": True},
        "grant_id": {"type": "string"},
        "cost_category": {"type": "enum", "values": svc.COST_CATEGORIES},
    })
    grant = None
    if body["allocation_type"] == "GRANT":
        if not body.get("grant_id"):
            raise ApiError(ERR_INVALID_REQUEST, 400, "grant_id is required for GRANT allocations")
        if "cost_category" not in body or body.get("cost_category") is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "cost_category is required for GRANT allocations")
        grant = require_fk("grants", body["grant_id"])
        # p7 compliance: category allowability and budget-period coverage.
        if body["cost_category"] not in grant["allowed_categories"]:
            raise ApiError(ERR_GRANT_CATEGORY_NOT_ALLOWABLE, 422, "cost_category not in grant.allowed_categories")
        now = db.now()
        if not (dt_of(grant, "budget_start") <= now <= dt_of(grant, "budget_end")):
            raise ApiError(ERR_GRANT_BUDGET_PERIOD_EXPIRED, 422, "logical clock outside the grant budget period")
        # p10 referential: grant must be ACTIVE.
        if grant["status"] != "ACTIVE":
            raise ApiError(ERR_GRANT_NOT_ACTIVE, 409, "grant must be ACTIVE")
        # p11 fiscal: provisional remaining covers the amount.
        ledger = svc.grant_ledger(grant)
        if ledger["provisional_remaining_cents"] < txn["amount_cents"]:
            raise ApiError(ERR_GRANT_BUDGET_EXCEEDED, 402, "amount exceeds the grant's provisional remaining budget")
    txn["receipt_reference"] = body["receipt_reference"]
    txn["allocation_type"] = body["allocation_type"]
    txn["grant_id"] = grant["id"] if grant is not None else None
    txn["cost_category"] = body.get("cost_category") if grant is not None else None
    txn["reconciled_at"] = db.logical_ts()
    txn["status"] = "RECONCILED"
    db.touch(txn)
    # GRANT spend books immediately into the computed ledger (spent_cents).
    return success_obj(db.public(txn), 200)


@bp.post("/pcard-transactions/<tid>/dispute")
def dispute_transaction(tid):
    user_id, _ = authenticate(["Cardholder"])
    txn = require_fk("pcard_transactions", tid)
    card = db.get("pcards", txn["pcard_id"])
    _check_card_holder(card, user_id)  # p4
    if txn["status"] not in ("POSTED", "RECONCILED"):
        raise ApiError(ERR_TXN_NOT_DISPUTABLE, 409, "dispute requires POSTED or RECONCILED")
    if card["status"] == "CLOSED":
        raise ApiError(ERR_CARD_CLOSED, 409, "card is CLOSED")
    body = body_json()
    check_shape(body, {"reason": {"type": "string", "required": True}})
    txn["pre_dispute_status"] = txn["status"]
    txn["status"] = "DISPUTED"
    db.touch(txn)
    return success_obj(db.public(txn), 200)


@bp.post("/pcard-transactions/<tid>/resolve-dispute")
def resolve_dispute(tid):
    authenticate(["ProcurementAdmin"])
    txn = require_fk("pcard_transactions", tid)
    if txn["status"] != "DISPUTED":
        raise ApiError(ERR_TXN_NOT_DISPUTED, 409, "resolve-dispute requires a DISPUTED transaction")
    body = body_json()
    check_shape(body, {
        "outcome": {"type": "enum", "values": ["CARDHOLDER_FAVOR", "MERCHANT_FAVOR"], "required": True},
    })
    if body["outcome"] == "CARDHOLDER_FAVOR":
        # REVERSED is terminal: the amount leaves utilization, and a formerly
        # grant-reconciled amount leaves the computed grant spent figure.
        txn["status"] = "REVERSED"
    else:
        txn["status"] = txn["pre_dispute_status"] or "POSTED"
    txn["pre_dispute_status"] = None
    db.touch(txn)
    return success_obj(db.public(txn), 200)
