"""Discrepancy item endpoints (PRD 3.8).

Findings are raised beneath a transaction (the API's one nested creation
path); the first finding moves INSPECTION_COMPLETE -> DISCREPANCY_NEGOTIATION.
Resolutions recompute credits_total_usd (sum of credit_amount_usd over
RESOLVED items with resolution CREDIT) and bubble the transaction to
DELIVERY_PENDING when every item is RESOLVED.
"""
from decimal import Decimal

from flask import Blueprint

import db as dbmod
from errors import (
    ERR_AIRWORTHINESS_NOT_WAIVABLE,
    ERR_BOOKING_NOT_FOR_TRANSACTION,
    ERR_CREDIT_NOT_PROPOSED,
    ERR_DISCREPANCY_ITEM_NOT_FOUND,
    ERR_INSPECTION_BOOKING_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_TRANSACTION_NOT_FOUND,
    raise_error,
)
from middleware import ALL_ROLES, require_roles
from response import success_object
from services.core import list_page, new_record, serialize, touch
from validate import (
    body,
    opt_money,
    opt_str,
    req_enum,
    req_money,
    req_str,
)

bp = Blueprint("discrepancies", __name__)

RAISABLE_TX_STATES = ("INSPECTION_COMPLETE", "DISCREPANCY_NEGOTIATION")


def _get_item(item_id):
    rec = dbmod.db["discrepancies"].get(item_id)
    if rec is None:
        raise_error(ERR_DISCREPANCY_ITEM_NOT_FOUND,
                    "discrepancy item id does not exist")
    return rec


def _resolve(item, resolution):
    """Terminal resolution: item -> RESOLVED, credits recomputed, bubble-up."""
    item["status"] = "RESOLVED"
    item["resolution"] = resolution
    touch(item)
    tx = dbmod.db["transactions"].get(item["transaction_id"])
    if tx is None:
        return
    credits = sum(
        (
            d["credit_amount_usd"]
            for d in dbmod.db["discrepancies"].values()
            if d["transaction_id"] == tx["id"]
            and d["status"] == "RESOLVED"
            and d["resolution"] == "CREDIT"
            and d["credit_amount_usd"] is not None
        ),
        Decimal("0.00"),
    )
    mutated = credits != tx["credits_total_usd"]
    tx["credits_total_usd"] = credits
    all_resolved = all(
        d["status"] == "RESOLVED"
        for d in dbmod.db["discrepancies"].values()
        if d["transaction_id"] == tx["id"]
    )
    if all_resolved and tx["status"] == "DISCREPANCY_NEGOTIATION":
        tx["status"] = "DELIVERY_PENDING"
        mutated = True
    if mutated:
        touch(tx)


@bp.post("/api/transactions/<tx_id>/discrepancy-items")
@require_roles(["FacilityScheduler"])
def create_item(tx_id):
    tx = dbmod.db["transactions"].get(tx_id)
    if tx is None:
        raise_error(ERR_TRANSACTION_NOT_FOUND, "transaction id does not exist")
    b = body()
    # Priority 3: body-referenced booking must exist.
    if isinstance(b.get("inspection_booking_id"), str):
        if b["inspection_booking_id"] not in dbmod.db["bookings"]:
            raise_error(ERR_INSPECTION_BOOKING_NOT_FOUND,
                        "inspection booking id does not exist")
    # Priority 4: schema.
    booking_id = req_str(b, "inspection_booking_id")
    description = req_str(b, "description")
    severity = req_enum(
        b, "severity", ["AIRWORTHINESS", "NON_AIRWORTHINESS"]
    )
    estimated_cost = req_money(b, "estimated_cost_usd", allow_zero=True)
    # Priority 5(a): findings belong to the inspection/negotiation phase.
    if tx["status"] not in RAISABLE_TX_STATES:
        raise_error(
            ERR_INVALID_STATE,
            "discrepancy items require INSPECTION_COMPLETE or "
            "DISCREPANCY_NEGOTIATION",
        )
    # Priority 8: the booking must belong to the path transaction.
    booking = dbmod.db["bookings"].get(booking_id)
    if booking is None:
        raise_error(ERR_INSPECTION_BOOKING_NOT_FOUND,
                    "inspection booking id does not exist")
    if booking["transaction_id"] != tx["id"]:
        raise_error(
            ERR_BOOKING_NOT_FOR_TRANSACTION,
            "inspection_booking_id references a booking of a different "
            "transaction",
        )
    rec = new_record(
        "discrepancies",
        {
            "transaction_id": tx["id"],
            "inspection_booking_id": booking_id,
            "description": description,
            "severity": severity,
            "estimated_cost_usd": estimated_cost,
            "proposed_credit_usd": None,
            "credit_amount_usd": None,
            "resolution": None,
            "status": "RAISED",
        },
    )
    # The very first finding opens the negotiation phase.
    if tx["status"] == "INSPECTION_COMPLETE":
        tx["status"] = "DISCREPANCY_NEGOTIATION"
        touch(tx)
    return success_object(serialize("discrepancies", rec), 201)


@bp.get("/api/discrepancy-items")
@require_roles(ALL_ROLES)
def list_items():
    return list_page(
        "discrepancies",
        ["transaction_id", "inspection_booking_id", "status"],
    )


@bp.get("/api/discrepancy-items/<item_id>")
@require_roles(ALL_ROLES)
def get_item(item_id):
    return success_object(serialize("discrepancies", _get_item(item_id)))


@bp.post("/api/discrepancy-items/<item_id>/counter")
@require_roles(["ListingAgent"])
def counter_item(item_id):
    item = _get_item(item_id)
    b = body()
    proposed_credit = opt_money(b, "proposed_credit_usd", allow_zero=True)
    opt_str(b, "repair_offer_note")  # accepted free text; not persisted
    if item["status"] != "RAISED":
        raise_error(
            ERR_INVALID_STATE, "only a RAISED finding can be countered"
        )
    item["status"] = "COUNTERED"
    if proposed_credit is not None:
        item["proposed_credit_usd"] = proposed_credit
    touch(item)
    return success_object(serialize("discrepancies", item))


@bp.post("/api/discrepancy-items/<item_id>/commit-repair")
@require_roles(["ListingAgent"])
def commit_repair(item_id):
    item = _get_item(item_id)
    if item["status"] not in ("RAISED", "COUNTERED"):
        raise_error(
            ERR_INVALID_STATE,
            "only a RAISED or COUNTERED finding can be committed to repair",
        )
    _resolve(item, "REPAIR")
    return success_object(serialize("discrepancies", item))


@bp.post("/api/discrepancy-items/<item_id>/agree-credit")
@require_roles(["BuyerAgent"])
def agree_credit(item_id):
    item = _get_item(item_id)
    if item["status"] != "COUNTERED":
        raise_error(
            ERR_INVALID_STATE,
            "only a COUNTERED finding can proceed to credit agreement",
        )
    if item["proposed_credit_usd"] is None:
        raise_error(
            ERR_CREDIT_NOT_PROPOSED,
            "no proposed_credit_usd has been recorded for this finding",
        )
    item["credit_amount_usd"] = item["proposed_credit_usd"]
    _resolve(item, "CREDIT")
    return success_object(serialize("discrepancies", item))


@bp.post("/api/discrepancy-items/<item_id>/waive")
@require_roles(["BuyerAgent"])
def waive(item_id):
    item = _get_item(item_id)
    if item["status"] not in ("RAISED", "COUNTERED"):
        raise_error(
            ERR_INVALID_STATE,
            "only a RAISED or COUNTERED finding can be waived",
        )
    # Business safety: an airworthiness finding may never be waived.
    if item["severity"] != "NON_AIRWORTHINESS":
        raise_error(
            ERR_AIRWORTHINESS_NOT_WAIVABLE,
            "an AIRWORTHINESS finding may not be waived",
        )
    _resolve(item, "WAIVED")
    return success_object(serialize("discrepancies", item))
