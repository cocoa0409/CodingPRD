"""ReturnRequest endpoints: create / approve / reject / resubmit / receive."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
import errors
import helpers
import middleware
import services
from db import clock, _parse_iso
from helpers import (
    get_campaign, get_order, get_order_line, get_return, get_seller,
    new_id, now_iso, paginate, sort_created,
    req_string, req_int, req_enum, opt_string,
    serialize_return,
)
from middleware import get_body, parse_pagination
from response import success_object, success_list

bp = Blueprint("returns", __name__)

REASONS = ("UNSOLD", "DEFECTIVE", "WRONG_ITEM", "FAMILY_CHANGED_MIND")
NO_FEE_REASONS = ("DEFECTIVE", "WRONG_ITEM")


def _line_availability(line):
    return (
        line["quantity"]
        - line["returned_qty"]
        - line["claim_resolved_refund_qty"]
        - line["sort_shortage_qty"]
    )


def _sibling_reserved(line_id, exclude_return_id=None):
    total = 0
    for r in db.return_requests.values():
        if r["order_line_id"] != line_id:
            continue
        if exclude_return_id is not None and r["id"] == exclude_return_id:
            continue
        if r["status"] in ("REQUESTED", "APPROVED"):
            total += r["quantity"]
    return total


def _window_open(campaign):
    dca = campaign.get("distribution_completed_at")
    if dca is None:
        return False
    deadline = _parse_iso(dca) + timedelta(days=services.RETURN_WINDOW_DAYS)
    return clock.now() <= deadline


@bp.post("/fundraiser/return-requests")
def create_return():
    user_id, _role = middleware.require_role("GroupCoordinator")
    body = get_body(required=True)
    seller_id = req_string(body, "seller_id")
    order_id = req_string(body, "order_id")
    order_line_id = req_string(body, "order_line_id")
    quantity = req_int(body, "quantity", minimum=1)
    reason = req_enum(body, "reason", REASONS)
    seller = get_seller(seller_id)
    order = get_order(order_id)
    line = get_order_line(order_line_id)
    campaign = get_campaign(order["campaign_id"])
    if campaign["status"] not in ("DISTRIBUTION_COMPLETE", "RECONCILED"):
        raise errors.err_invalid_state("Campaign must be DISTRIBUTION_COMPLETE or RECONCILED")
    if not _window_open(campaign):
        raise errors.err_return_window_expired()
    if seller["campaign_id"] != order["campaign_id"] or seller["id"] != order["seller_id"]:
        raise errors.err_cross_campaign_reference("seller_id must match the order's seller")
    if line["order_id"] != order_id:
        raise errors.err_order_line_mismatch()
    product = db.products[line["product_id"]]
    if not product["returnable"]:
        raise errors.err_product_not_returnable()
    available = _line_availability(line) - _sibling_reserved(line["id"])
    if quantity > available:
        raise errors.err_return_qty_exceeds_available()
    rid = new_id()
    ret = {
        "id": rid,
        "seller_id": seller_id,
        "order_id": order_id,
        "order_line_id": order_line_id,
        "campaign_id": order["campaign_id"],
        "quantity": quantity,
        "reason": reason,
        "status": "REQUESTED",
        "requested_by_user_id": user_id,
        "decided_by_user_id": None,
        "refund_cents": None,
        "restocking_fee_cents": None,
        "resubmission_count": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.return_requests[rid] = ret
    return success_object(serialize_return(ret), status=201)


@bp.get("/fundraiser/return-requests")
def list_returns():
    middleware.any_role()
    limit, offset = parse_pagination()
    items = list(db.return_requests.values())
    for param in ("seller_id", "order_id", "order_line_id", "campaign_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_return(r) for r in page], limit, offset, total)


@bp.get("/fundraiser/return-requests/<rid>")
def read_return(rid):
    middleware.any_role()
    ret = get_return(rid)
    return success_object(serialize_return(ret))


def _pin_amounts(ret):
    line = db.order_lines[ret["order_line_id"]]
    if ret["reason"] in NO_FEE_REASONS:
        fee_per_unit = 0
    else:
        fee = (Decimal(line["unit_price_cents"]) * Decimal(services.RESTOCK_FEE_BPS)) / Decimal(10000)
        fee_per_unit = services.round_half_up_cents(fee)
    ret["restocking_fee_cents"] = fee_per_unit * ret["quantity"]
    ret["refund_cents"] = ret["quantity"] * line["unit_price_cents"] - ret["restocking_fee_cents"]


@bp.post("/fundraiser/return-requests/<rid>/approve")
def approve_return(rid):
    user_id, _role = middleware.require_role("Treasurer")
    ret = get_return(rid)
    get_body()
    if ret["status"] != "REQUESTED":
        raise errors.err_invalid_state("Return request is not REQUESTED")
    if user_id == ret["requested_by_user_id"]:
        raise errors.err_segregation("Approver must differ from the filer")
    _pin_amounts(ret)
    ret["decided_by_user_id"] = user_id
    ret["status"] = "APPROVED"
    helpers.touch(ret)
    return success_object(serialize_return(ret))


@bp.post("/fundraiser/return-requests/<rid>/reject")
def reject_return(rid):
    user_id, _role = middleware.require_role("Treasurer")
    ret = get_return(rid)
    body = get_body()
    if body:
        opt_string(body, "reason", default=None)
    if ret["status"] != "REQUESTED":
        raise errors.err_invalid_state("Return request is not REQUESTED")
    if user_id == ret["requested_by_user_id"]:
        raise errors.err_segregation("Rejector must differ from the filer")
    ret["decided_by_user_id"] = user_id
    ret["status"] = "REJECTED"
    helpers.touch(ret)
    return success_object(serialize_return(ret))


@bp.post("/fundraiser/return-requests/<rid>/resubmit")
def resubmit_return(rid):
    middleware.require_role("GroupCoordinator")
    ret = get_return(rid)
    body = get_body(required=True)
    quantity = req_int(body, "quantity", minimum=1)
    reason = req_enum(body, "reason", REASONS)
    if ret["status"] != "REJECTED":
        raise errors.err_invalid_state("Return request is not REJECTED")
    campaign = db.campaigns[ret["campaign_id"]]
    if not _window_open(campaign):
        raise errors.err_return_window_expired()
    line = db.order_lines[ret["order_line_id"]]
    product = db.products[line["product_id"]]
    if not product["returnable"]:
        raise errors.err_product_not_returnable()
    available = _line_availability(line) - _sibling_reserved(line["id"], exclude_return_id=ret["id"])
    if quantity > available:
        raise errors.err_return_qty_exceeds_available()
    ret["quantity"] = quantity
    ret["reason"] = reason
    ret["status"] = "REQUESTED"
    ret["resubmission_count"] += 1
    helpers.touch(ret)
    return success_object(serialize_return(ret))


@bp.post("/fundraiser/return-requests/<rid>/receive")
def receive_return(rid):
    middleware.require_role("Treasurer")
    ret = get_return(rid)
    body = get_body(required=True)
    disposition = req_enum(body, "disposition", ("RESTOCKABLE", "DAMAGED_WRITE_OFF"))
    if ret["status"] != "APPROVED":
        raise errors.err_invalid_state("Return request is not APPROVED")
    line = db.order_lines[ret["order_line_id"]]
    product = db.products[line["product_id"]]
    order = db.orders[ret["order_id"]]

    line["returned_qty"] += ret["quantity"]
    helpers.touch(line)
    product["distributed_units"] -= ret["quantity"]
    if disposition == "RESTOCKABLE":
        product["restocked_units"] += ret["quantity"]
        ret["status"] = "RECEIVED_RESTOCKED"
    else:
        product["written_off_units"] += ret["quantity"]
        ret["status"] = "RECEIVED_WRITTEN_OFF"
    helpers.touch(product)
    helpers.touch(ret)

    debit = (Decimal(ret["quantity"])
             * Decimal(line["unit_price_cents"] - line["unit_cost_cents"])
             * Decimal(product["profit_share_bps"])) / Decimal(10000)
    debit_cents = services.round_half_up_cents(debit)
    services.post_ledger_entry(
        group_id=order["group_id"], campaign_id=order["campaign_id"],
        entry_type="RETURN_DEBIT", amount_cents=-debit_cents,
        reference_type="RETURN_REQUEST", reference_id=ret["id"],
        memo=f"Return debit for received return {ret['id']}",
    )
    services.recompute_order_fulfillment(order)
    seller = db.sellers[order["seller_id"]]
    services.recompute_seller_metrics(seller)
    services.evaluate_prizes_for_seller(seller)
    services.recompute_campaign_totals(db.campaigns[order["campaign_id"]])
    return success_object(serialize_return(ret))
