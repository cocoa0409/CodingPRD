"""Transaction endpoints (PRD 3.9): list, get, delivery-condition checklist,
as-is acceptance, termination, and closing."""
from flask import Blueprint

import db as dbmod
from errors import (
    ERR_DELIVERY_CONDITIONS_INCOMPLETE,
    ERR_INVALID_STATE,
    ERR_OPEN_DISCREPANCIES,
    ERR_STALE_VERSION,
    ERR_TRANSACTION_NOT_FOUND,
    raise_error,
)
from middleware import ALL_ROLES, require_roles
from response import success_object
from services.core import list_page, new_record, serialize, touch
from services.settlement import compute_commission, compute_settlement
from util import today_iso
from validate import (
    body,
    opt_bool,
    opt_nullable_str,
    req_int,
    req_str,
)

bp = Blueprint("transactions", __name__)

PRE_DELIVERY_STATES = (
    "OPENED",
    "ESCROW_FUNDED",
    "INSPECTION_SCHEDULED",
    "INSPECTION_COMPLETE",
    "DISCREPANCY_NEGOTIATION",
)
TERMINAL_STATES = ("CLOSED", "TERMINATED")


def _get_transaction(tx_id):
    rec = dbmod.db["transactions"].get(tx_id)
    if rec is None:
        raise_error(ERR_TRANSACTION_NOT_FOUND, "transaction id does not exist")
    return rec


def _escrow_for(tx_id):
    for esc in dbmod.db["escrows"].values():
        if esc["transaction_id"] == tx_id:
            return esc
    return None


@bp.get("/api/transactions")
@require_roles(ALL_ROLES)
def list_transactions():
    return list_page(
        "transactions", ["loi_id", "listing_id", "buyer_id", "status"]
    )


@bp.get("/api/transactions/<tx_id>")
@require_roles(ALL_ROLES)
def get_transaction(tx_id):
    return success_object(serialize("transactions", _get_transaction(tx_id)))


@bp.patch("/api/transactions/<tx_id>/delivery-conditions")
@require_roles(["BrokerPrincipal"])
def patch_delivery_conditions(tx_id):
    tx = _get_transaction(tx_id)
    b = body()
    expected = req_int(b, "expected_transaction_version")
    logbook = opt_bool(b, "logbook_complete", default=None)
    reg_docs = opt_bool(b, "registration_docs_complete", default=None)
    notes_provided, notes = opt_nullable_str(b, "tax_planning_notes")
    # Legitimate in every non-terminal state; terminal -> ERR_INVALID_STATE.
    if tx["status"] in TERMINAL_STATES:
        raise_error(
            ERR_INVALID_STATE,
            "delivery conditions cannot be updated on a terminal transaction",
        )
    if expected != tx["version"]:
        raise_error(
            ERR_STALE_VERSION,
            "expected_transaction_version does not match the transaction's "
            "current version",
        )
    if logbook is not None:
        tx["logbook_complete"] = logbook
    if reg_docs is not None:
        tx["registration_docs_complete"] = reg_docs
    if notes_provided:
        tx["tax_planning_notes"] = notes
    touch(tx)
    return success_object(serialize("transactions", tx))


@bp.post("/api/transactions/<tx_id>/accept-as-is")
@require_roles(["BuyerAgent"])
def accept_as_is(tx_id):
    tx = _get_transaction(tx_id)
    items = [
        d for d in dbmod.db["discrepancies"].values()
        if d["transaction_id"] == tx["id"]
    ]
    # PRD 3.9: as-is acceptance is allowed "only while zero discrepancy items
    # exist for the transaction — otherwise it is rejected with
    # ERR_OPEN_DISCREPANCIES". Per 3.8 the first finding moves the transaction
    # into DISCREPANCY_NEGOTIATION, so an open-items transaction is always in
    # that state and the zero-findings gate (pipeline step 5b) is the deciding
    # check there; every other non-source state fails step 5a.
    if tx["status"] == "DISCREPANCY_NEGOTIATION" or (
        tx["status"] == "INSPECTION_COMPLETE" and items
    ):
        raise_error(
            ERR_OPEN_DISCREPANCIES,
            "discrepancy items exist for this transaction",
        )
    if tx["status"] != "INSPECTION_COMPLETE":
        raise_error(
            ERR_INVALID_STATE,
            "as-is acceptance requires INSPECTION_COMPLETE",
        )
    tx["status"] = "DELIVERY_PENDING"
    touch(tx)
    return success_object(serialize("transactions", tx))


@bp.post("/api/transactions/<tx_id>/terminate")
@require_roles(["BrokerPrincipal", "ListingAgent"])
def terminate(tx_id):
    tx = _get_transaction(tx_id)
    b = body()
    reason = req_str(b, "reason")
    if tx["status"] in TERMINAL_STATES:
        raise_error(
            ERR_INVALID_STATE, "transaction is already terminal"
        )
    prior_status = tx["status"]
    tx["status"] = "TERMINATED"
    tx["termination_reason"] = reason
    touch(tx)
    # Escrow disposition: refund before DELIVERY_PENDING, forfeit at it.
    esc = _escrow_for(tx["id"])
    if esc is not None and esc["status"] == "FUNDED":
        if prior_status == "DELIVERY_PENDING":
            esc["status"] = "FORFEITED"
            esc["forfeited_usd"] = esc["deposit_amount_usd"]
        else:
            esc["status"] = "REFUNDED"
            esc["refunded_usd"] = esc["deposit_amount_usd"]
        touch(esc)
    # Listing becomes marketable again.
    listing = dbmod.db["listings"].get(tx["listing_id"])
    if listing is not None and listing["status"] == "UNDER_CONTRACT":
        listing["status"] = "ACTIVE"
        touch(listing)
    return success_object(serialize("transactions", tx))


@bp.post("/api/transactions/<tx_id>/close")
@require_roles(["BrokerPrincipal"])
def close(tx_id):
    tx = _get_transaction(tx_id)
    if tx["status"] != "DELIVERY_PENDING":
        raise_error(
            ERR_INVALID_STATE, "closing requires DELIVERY_PENDING"
        )
    if not (tx["logbook_complete"] and tx["registration_docs_complete"]):
        raise_error(
            ERR_DELIVERY_CONDITIONS_INCOMPLETE,
            "logbook_complete and registration_docs_complete must both be "
            "true before closing",
        )
    esc = _escrow_for(tx["id"])
    # Pinned order: commission_settlement runs first, then closing_settlement.
    commission = compute_commission(
        tx["agreed_price_usd"], tx["credits_total_usd"], tx["dual_agency"]
    )
    deposit = esc["deposit_amount_usd"] if esc is not None else None
    buyer_due, seller_net = compute_settlement(
        tx["agreed_price_usd"], tx["credits_total_usd"], deposit, commission
    )
    tx["commission_amount_usd"] = commission
    tx["settlement_buyer_due_usd"] = buyer_due
    tx["settlement_seller_net_usd"] = seller_net
    tx["status"] = "CLOSED"
    touch(tx)
    # Escrow releases the full deposit to the seller.
    if esc is not None and esc["status"] == "FUNDED":
        esc["status"] = "RELEASED"
        esc["released_usd"] = esc["deposit_amount_usd"]
        touch(esc)
    # Listing sells and mints a VERIFIED comparable from the closing.
    listing = dbmod.db["listings"].get(tx["listing_id"])
    if listing is not None and listing["status"] == "UNDER_CONTRACT":
        listing["status"] = "SOLD"
        touch(listing)
        new_record(
            "comps",
            {
                "make": listing["make"],
                "model": listing["model"],
                "year": listing["year"],
                "sale_price_usd": tx["agreed_price_usd"],
                "sale_date": today_iso(),
                "total_time_hours": listing["total_time_hours"],
                "comp_status": "VERIFIED",
                "source_listing_id": listing["id"],
            },
        )
    return success_object(serialize("transactions", tx))
