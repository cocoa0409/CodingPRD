"""ReconciliationClaim endpoints: file / approve / deny / appeal / resolve."""

from decimal import Decimal

from flask import Blueprint, request

import db
import errors
import helpers
import middleware
import services
from helpers import (
    get_claim, get_order, get_order_line, new_id, now_iso, paginate, sort_created,
    req_string, req_int, req_enum, opt_string,
    serialize_claim,
)
from middleware import get_body, parse_pagination
from response import success_object, success_list

bp = Blueprint("claims", __name__)

CLAIM_TYPES = ("MISSING", "DAMAGED")


def _line_availability(line):
    return (
        line["quantity"]
        - line["returned_qty"]
        - line["claim_resolved_refund_qty"]
        - line["sort_shortage_qty"]
    )


def _sibling_claimed_qty(line_id, exclude_claim_id=None):
    """Quantities reserved by sibling claims still in SUBMITTED or APPROVED."""
    total = 0
    for c in db.claims.values():
        if c["order_line_id"] != line_id:
            continue
        if exclude_claim_id is not None and c["id"] == exclude_claim_id:
            continue
        if c["status"] in ("SUBMITTED", "APPROVED"):
            total += c["quantity"]
    return total


@bp.post("/fundraiser/reconciliation-claims")
def create_claim():
    user_id, _role = middleware.require_role("GroupCoordinator")
    body = get_body(required=True)
    order_id = req_string(body, "order_id")
    order_line_id = req_string(body, "order_line_id")
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    quantity = req_int(body, "quantity", minimum=1)
    note = opt_string(body, "note", default=None)
    order = get_order(order_id)
    line = get_order_line(order_line_id)
    if order["fulfillment_status"] not in ("SORTED", "DISTRIBUTED", "PARTIALLY_RETURNED"):
        raise errors.err_invalid_state("Order fulfillment must be SORTED, DISTRIBUTED, or PARTIALLY_RETURNED")
    if line["order_id"] != order_id:
        raise errors.err_order_line_mismatch()
    available = _line_availability(line) - _sibling_claimed_qty(line["id"])
    if quantity > available:
        raise errors.err_claim_qty_exceeds_available()
    cid = new_id()
    claim = {
        "id": cid,
        "order_id": order_id,
        "order_line_id": order_line_id,
        "campaign_id": order["campaign_id"],
        "claim_type": claim_type,
        "quantity": quantity,
        "note": note,
        "status": "SUBMITTED",
        "reported_by_user_id": user_id,
        "reviewed_by_user_id": None,
        "resolution": None,
        "credit_cents": 0,
        "supersedes_claim_id": None,
        "auto_generated": False,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.claims[cid] = claim
    return success_object(serialize_claim(claim), status=201)


@bp.get("/fundraiser/reconciliation-claims")
def list_claims():
    middleware.any_role()
    limit, offset = parse_pagination()
    items = list(db.claims.values())
    for param in ("order_id", "campaign_id", "order_line_id", "supersedes_claim_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(param) == v]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_claim(c) for c in page], limit, offset, total)


@bp.get("/fundraiser/reconciliation-claims/<cid>")
def read_claim(cid):
    middleware.any_role()
    claim = get_claim(cid)
    return success_object(serialize_claim(claim))


@bp.post("/fundraiser/reconciliation-claims/<cid>/approve")
def approve_claim(cid):
    user_id, _role = middleware.require_role("FundraiserAdmin")
    claim = get_claim(cid)
    get_body()
    if claim["status"] != "SUBMITTED":
        raise errors.err_invalid_state("Claim is not SUBMITTED")
    if user_id == claim["reported_by_user_id"]:
        raise errors.err_segregation("Approver must differ from the reporter")
    claim["status"] = "APPROVED"
    claim["reviewed_by_user_id"] = user_id
    helpers.touch(claim)
    return success_object(serialize_claim(claim))


@bp.post("/fundraiser/reconciliation-claims/<cid>/deny")
def deny_claim(cid):
    user_id, _role = middleware.require_role("FundraiserAdmin")
    claim = get_claim(cid)
    body = get_body()
    if body:
        opt_string(body, "reason", default=None)
    if claim["status"] != "SUBMITTED":
        raise errors.err_invalid_state("Claim is not SUBMITTED")
    if user_id == claim["reported_by_user_id"]:
        raise errors.err_segregation("Denier must differ from the reporter")
    claim["status"] = "DENIED"
    claim["reviewed_by_user_id"] = user_id
    helpers.touch(claim)
    return success_object(serialize_claim(claim))


@bp.post("/fundraiser/reconciliation-claims/<cid>/appeal")
def appeal_claim(cid):
    middleware.require_role("GroupCoordinator")
    claim = get_claim(cid)
    body = get_body()
    note = opt_string(body, "note", default=None) if body else None
    if claim["status"] != "DENIED":
        raise errors.err_invalid_state("Claim is not DENIED")
    if claim["supersedes_claim_id"] is not None:
        raise errors.err_appeal_limit_exceeded()
    claim["status"] = "APPEALED"
    helpers.touch(claim)
    sid = new_id()
    successor = {
        "id": sid,
        "order_id": claim["order_id"],
        "order_line_id": claim["order_line_id"],
        "campaign_id": claim["campaign_id"],
        "claim_type": claim["claim_type"],
        "quantity": claim["quantity"],
        "note": note,
        "status": "SUBMITTED",
        "reported_by_user_id": None,
        "reviewed_by_user_id": None,
        "resolution": None,
        "credit_cents": 0,
        "supersedes_claim_id": claim["id"],
        "auto_generated": claim["auto_generated"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    # Successor reporter: the appealing coordinator
    successor["reported_by_user_id"] = middleware.actor()[0]
    db.claims[sid] = successor
    return success_object(serialize_claim(successor), status=201)


@bp.post("/fundraiser/reconciliation-claims/<cid>/resolve")
def resolve_claim(cid):
    middleware.require_role("FundraiserAdmin")
    claim = get_claim(cid)
    body = get_body(required=True)
    resolution = req_enum(body, "resolution", ("REPLACEMENT", "REFUND"))
    if claim["status"] != "APPROVED":
        raise errors.err_invalid_state("Claim is not APPROVED")
    order = db.orders[claim["order_id"]]
    line = db.order_lines[claim["order_line_id"]]
    product = db.products[line["product_id"]]

    if resolution == "REPLACEMENT":
        if order["fulfillment_status"] not in ("DISTRIBUTED", "PARTIALLY_RETURNED"):
            raise errors.err_invalid_state("Order fulfillment must be DISTRIBUTED or PARTIALLY_RETURNED for replacement")
        if product["surplus_units"] < claim["quantity"]:
            raise errors.err_insufficient_surplus()
        product["surplus_units"] -= claim["quantity"]
        if claim["claim_type"] == "DAMAGED":
            product["lost_units"] += claim["quantity"]
        helpers.touch(product)
        claim["credit_cents"] = 0
        claim["resolution"] = "REPLACEMENT"
        claim["status"] = "RESOLVED_REPLACEMENT"
        helpers.touch(claim)
    else:  # REFUND
        claim["credit_cents"] = claim["quantity"] * line["unit_price_cents"]
        line["claim_resolved_refund_qty"] += claim["quantity"]
        helpers.touch(line)
        loss = (Decimal(claim["quantity"])
                * Decimal(line["unit_price_cents"] - line["unit_cost_cents"])
                * Decimal(product["profit_share_bps"])) / Decimal(10000)
        loss_cents = services.round_half_up_cents(loss)
        services.post_ledger_entry(
            group_id=order["group_id"], campaign_id=order["campaign_id"],
            entry_type="CLAIM_LOSS_DEBIT", amount_cents=-loss_cents,
            reference_type="CLAIM", reference_id=claim["id"],
            memo=f"Claim loss debit for refund-resolved claim {claim['id']}",
        )
        if order["fulfillment_status"] in ("DISTRIBUTED", "PARTIALLY_RETURNED") and not claim["auto_generated"]:
            product["distributed_units"] -= claim["quantity"]
            product["lost_units"] += claim["quantity"]
            helpers.touch(product)
        claim["resolution"] = "REFUND"
        claim["status"] = "RESOLVED_REFUND"
        helpers.touch(claim)

    services.recompute_order_fulfillment(order)
    seller = db.sellers[order["seller_id"]]
    services.recompute_seller_metrics(seller)
    services.evaluate_prizes_for_seller(seller)
    services.recompute_campaign_totals(db.campaigns[order["campaign_id"]])
    return success_object(serialize_claim(claim))
