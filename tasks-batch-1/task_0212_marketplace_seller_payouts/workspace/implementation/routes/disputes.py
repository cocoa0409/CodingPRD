"""A-to-Z dispute endpoints (PRD §3.8 cyclic claim process)."""
from flask import Blueprint, request

from common import (
    parse_pagination, paginate, sort_by_created, get_json_body,
    require_fields, require_enum, err,
)
from errors import (
    ERR_INVALID_STATE, ERR_INVALID_REQUEST, ERR_DISPUTE_ROUND_EXHAUSTED,
)
from db import db
from middleware import (
    get_identity, require_roles, ROLE_SELLER, ROLE_REVIEWER, ROLE_FINANCE,
)
from response import success
from routes.helpers import fetch, ensure_seller_owns
from services.entity import stamp_create, touch
from services.ledger import post_ledger_entry, HOLD_AVAILABLE
from services.seller import refresh_seller_derived

bp = Blueprint("disputes", __name__)

CLAIM_TYPES = {"ITEM_NOT_RECEIVED", "ITEM_NOT_AS_DESCRIBED", "RETURN_NOT_REFUNDED"}


@bp.post("/disputes")
def create_dispute():
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER, ROLE_FINANCE])
    body = get_json_body()
    require_fields(body, ["order_id", "claim_type"])
    require_enum(body["claim_type"], CLAIM_TYPES, "claim_type")
    order = fetch(db.orders, body["order_id"])

    dispute = {
        "order_id": order["id"],
        "seller_id": order["seller_id"],
        "claim_type": body["claim_type"],
        "dispute_status": "FILED",
        "response_round": 0,
        "granted_amount_cents": 0,
    }
    stamp_create(dispute)
    db.disputes[dispute["id"]] = dispute
    return success(dispute, status=201)


@bp.get("/disputes/<dispute_id>")
def get_dispute(dispute_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER, ROLE_FINANCE, ROLE_SELLER])
    dispute = fetch(db.disputes, dispute_id)
    ensure_seller_owns(role, user_id, dispute["seller_id"])
    return success(dispute)


@bp.get("/disputes")
def list_disputes():
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER, ROLE_FINANCE, ROLE_SELLER])
    limit, offset = parse_pagination()
    items = list(db.disputes.values())
    if role == ROLE_SELLER:
        items = [d for d in items if d["seller_id"] == user_id]
    for key in ("order_id", "seller_id", "dispute_status"):
        val = request.args.get(key)
        if val is not None:
            items = [d for d in items if d[key] == val]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, pagination=meta)


@bp.post("/disputes/<dispute_id>/open-review")
def open_review(dispute_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER])
    dispute = fetch(db.disputes, dispute_id)
    status = dispute["dispute_status"]
    # Valid from FILED or (cyclically) from SELLER_RESPONDED.
    if status not in ("FILED", "SELLER_RESPONDED"):
        raise err(ERR_INVALID_STATE, "open-review not valid from this state.")
    # Round bound: cannot re-open once response_round has reached 3 (PRD §3.8).
    if status == "SELLER_RESPONDED" and dispute["response_round"] >= 3:
        raise err(ERR_DISPUTE_ROUND_EXHAUSTED, "Dispute response rounds exhausted.")
    dispute["dispute_status"] = "UNDER_REVIEW"
    touch(dispute)
    return success(dispute)


@bp.post("/disputes/<dispute_id>/respond")
def respond(dispute_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_SELLER])
    dispute = fetch(db.disputes, dispute_id)
    ensure_seller_owns(role, user_id, dispute["seller_id"])
    if dispute["dispute_status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "respond only valid from UNDER_REVIEW.")
    dispute["dispute_status"] = "SELLER_RESPONDED"
    dispute["response_round"] += 1
    touch(dispute)
    return success(dispute)


@bp.post("/disputes/<dispute_id>/decision")
def decision(dispute_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER])
    dispute = fetch(db.disputes, dispute_id)
    body = get_json_body()
    require_fields(body, ["outcome"])
    outcome = body["outcome"]
    # outcome names the winner: buyer -> GRANTED, seller -> DENIED (PRD §3.8).
    if outcome not in ("GRANTED", "DENIED", "BUYER", "SELLER"):
        raise err(ERR_INVALID_REQUEST, "outcome must name the winner.")
    buyer_wins = outcome in ("GRANTED", "BUYER")
    seller_wins = outcome in ("DENIED", "SELLER")

    order = db.orders[dispute["order_id"]]
    seller = db.sellers[dispute["seller_id"]]
    status = dispute["dispute_status"]

    if buyer_wins:
        # GRANTED is reachable from UNDER_REVIEW (PRD §3.8).
        if status != "UNDER_REVIEW":
            raise err(ERR_INVALID_STATE, "GRANTED only valid from UNDER_REVIEW.")
        dispute["dispute_status"] = "GRANTED"
        dispute["granted_amount_cents"] = order["gross_amount_cents"]
        # If the order has not already been clawed, post a full-gross
        # REFUND_CLAWBACK and drive Order_clawback NONE->REFUND_CLAWED.
        if order["clawback_status"] == "NONE":
            state = HOLD_AVAILABLE if order["settlement_status"] == "AVAILABLE" else "PENDING"
            post_ledger_entry(
                seller_id=dispute["seller_id"],
                source_type="REFUND_CLAWBACK",
                source_id=order["id"],
                amount_cents=-order["gross_amount_cents"],
                hold_state=state,
                memo="A-to-Z claim granted (full gross)",
            )
            order["clawback_status"] = "REFUND_CLAWED"
            touch(order)
        touch(dispute)
        refresh_seller_derived(seller)
        return success(dispute)

    # seller wins -> DENIED, reachable from SELLER_RESPONDED (PRD §3.8).
    if status != "SELLER_RESPONDED":
        raise err(ERR_INVALID_STATE, "DENIED only valid from SELLER_RESPONDED.")
    dispute["dispute_status"] = "DENIED"
    touch(dispute)
    return success(dispute)
