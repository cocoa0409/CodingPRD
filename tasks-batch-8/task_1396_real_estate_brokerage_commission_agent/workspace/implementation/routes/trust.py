"""Trust accounting read routes (PRD §3.8, §2.11)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_FORBIDDEN_RESOURCE
from middleware import parse_enum_filter, parse_str_filter
from response import success_obj
from routes.helpers import guard, public, list_response, by_created

bp = Blueprint("trust", __name__)

TRUST_KINDS = {"RECEIPT", "RECEIPT_REVERSAL", "RELEASE"}


@bp.route("/brokerage/trust-transactions/<transactionId>", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "Auditor"])
def get_transaction(user_id, role, transactionId):
    t = db.trust_transactions.get(transactionId)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, 404, "trust transaction not found")
    return success_obj(public(t))


@bp.route("/brokerage/trust-ledger", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "Auditor"])
def trust_ledger(user_id, role):
    received = 0
    released = 0
    for t in db.trust_transactions.values():
        if t["kind"] == "RECEIPT":
            received += t["amount_cents"]
        elif t["kind"] == "RECEIPT_REVERSAL":
            received += t["amount_cents"]  # negative: net received
        elif t["kind"] == "RELEASE":
            released += -t["amount_cents"]
    held = received - released
    return success_obj({
        "received_cents": received,
        "released_cents": released,
        "held_cents": held,
        "transaction_count": len(db.trust_transactions),
    })


@bp.route("/brokerage/trust-transactions", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def list_transactions(user_id, role):
    deal_id = parse_str_filter("deal_id")
    kind = parse_enum_filter("kind", TRUST_KINDS)
    items = list(db.trust_transactions.values())
    if role == "Agent":
        own_deals = {d["id"] for d in db.deals.values() if d["agent_id"] == user_id}
        items = [t for t in items if t["deal_id"] in own_deals]
    if deal_id is not None:
        items = [t for t in items if t["deal_id"] == deal_id]
    if kind is not None:
        items = [t for t in items if t["kind"] == kind]
    return list_response(by_created(items))
