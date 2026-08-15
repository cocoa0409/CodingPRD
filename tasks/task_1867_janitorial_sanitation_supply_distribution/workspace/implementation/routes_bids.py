"""Contract bid endpoints."""
from flask import Blueprint, request

import clock
import db
import services as svc
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_VALIDATION, ERR_PROTECTION_WINDOW_OVERLAP,
    not_found,
)
from middleware import require_roles
from response import success_object, success_list

bp = Blueprint("contract_bids", __name__)

READ_ROLES = ("DistributorAdmin", "SalesRep")


def _pagination():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise ApiError(ERR_VALIDATION, "limit/offset must be integers", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_VALIDATION, "limit must be 1..100, offset >= 0", 400)
    return limit, offset


@bp.post("/jansan/contract-bids")
def create_bid():
    require_roles("SalesRep")
    body = request.get_json(silent=True) or {}
    bid_reference = svc.as_str(svc.require_field(body, "bid_reference"), "bid_reference")
    group = svc.as_str(svc.require_field(body, "facility_group_code"), "facility_group_code")
    lines_raw = svc.require_field(body, "lines")
    if not isinstance(lines_raw, list) or len(lines_raw) == 0:
        raise ApiError(ERR_VALIDATION, "lines must be a non-empty array", 400)
    lines = []
    for i, entry in enumerate(lines_raw):
        if not isinstance(entry, dict):
            raise ApiError(ERR_VALIDATION, "lines[%d] must be an object" % i, 400)
        pid = svc.as_str(svc.require_field(entry, "product_id"), "lines[%d].product_id" % i)
        price = svc.as_int(svc.require_field(entry, "bid_price_cents"), "lines[%d].bid_price_cents" % i)
        if pid not in db.products:
            raise not_found("Product not found: %s" % pid)
        lines.append({"product_id": pid, "bid_price_cents": price})
    ps = svc.as_datetime(svc.require_field(body, "protection_start"), "protection_start")
    pe = svc.as_datetime(svc.require_field(body, "protection_end"), "protection_end")
    if pe <= ps:
        raise ApiError(ERR_VALIDATION, "protection_end must be > protection_start", 400)
    # bid_reference uniqueness
    for b in db.contract_bids.values():
        if b["bid_reference"] == bid_reference:
            raise ApiError(ERR_VALIDATION, "bid_reference must be unique", 400)

    b = svc.base_resource()
    b.update({
        "bid_reference": bid_reference,
        "facility_group_code": group,
        "lines": lines,
        "protection_start": clock.iso_format(ps),
        "protection_end": clock.iso_format(pe),
        "status": "DRAFT",
        "revision_number": 0,
        "submitted_at": None,
    })
    db.contract_bids[b["id"]] = b
    return success_object(dict(b), 201)


def get_bid_or_404(bid_id):
    b = db.contract_bids.get(bid_id)
    if b is None:
        raise not_found("Contract bid not found")
    return b


@bp.get("/jansan/contract-bids/<bid_id>")
def get_bid(bid_id):
    require_roles(*READ_ROLES)
    b = get_bid_or_404(bid_id)
    return success_object(dict(b))


@bp.get("/jansan/contract-bids")
def list_bids():
    require_roles(*READ_ROLES)
    group = request.args.get("facility_group_code")
    status = request.args.get("status")
    limit, offset = _pagination()
    items = list(db.contract_bids.values())
    if group:
        items = [b for b in items if b["facility_group_code"] == group]
    if status:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: clock.parse_iso(b["created_at"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([dict(b) for b in page], limit, offset, total)


@bp.post("/jansan/contract-bids/<bid_id>/submit")
def submit_bid(bid_id):
    require_roles("SalesRep")
    b = get_bid_or_404(bid_id)
    if b["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Bid is not DRAFT", 409)
    if not b["lines"]:
        raise ApiError(ERR_VALIDATION, "lines must be non-empty", 400)
    ps = clock.parse_iso(b["protection_start"])
    pe = clock.parse_iso(b["protection_end"])
    if pe <= ps:
        raise ApiError(ERR_VALIDATION, "protection_end must be > protection_start", 400)
    b["status"] = "SUBMITTED"
    b["submitted_at"] = clock.iso_now()
    svc.touch(b)
    return success_object(dict(b))


@bp.post("/jansan/contract-bids/<bid_id>/open-review")
def open_review_bid(bid_id):
    require_roles("SalesRep")
    b = get_bid_or_404(bid_id)
    if b["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Bid is not SUBMITTED", 409)
    b["status"] = "UNDER_REVIEW"
    svc.touch(b)
    return success_object(dict(b))


@bp.post("/jansan/contract-bids/<bid_id>/return-for-revision")
def return_for_revision(bid_id):
    require_roles("SalesRep")
    b = get_bid_or_404(bid_id)
    if b["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Bid is not UNDER_REVIEW", 409)
    b["status"] = "DRAFT"
    b["revision_number"] += 1
    svc.touch(b)
    return success_object(dict(b))


@bp.post("/jansan/contract-bids/<bid_id>/award")
def award_bid(bid_id):
    require_roles("DistributorAdmin")
    b = get_bid_or_404(bid_id)
    if b["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Bid is not UNDER_REVIEW", 409)
    # closed-window overlap check
    ps = clock.parse_iso(b["protection_start"])
    pe = clock.parse_iso(b["protection_end"])
    my_products = {l["product_id"] for l in b["lines"]}
    for other in db.contract_bids.values():
        if other["id"] == b["id"]:
            continue
        if other["status"] != "AWARDED":
            continue
        if other["facility_group_code"] != b["facility_group_code"]:
            continue
        other_products = {l["product_id"] for l in other["lines"]}
        if not (my_products & other_products):
            continue
        os_ = clock.parse_iso(other["protection_start"])
        oe = clock.parse_iso(other["protection_end"])
        # closed intervals: intersect iff ps <= oe AND os_ <= pe (touching endpoints intersect)
        if ps <= oe and os_ <= pe:
            raise ApiError(ERR_PROTECTION_WINDOW_OVERLAP,
                           "Protection window overlaps another AWARDED bid", 409)
    b["status"] = "AWARDED"
    svc.touch(b)
    svc.cascade_bid_to_standing_orders(b)
    return success_object(dict(b))


@bp.post("/jansan/contract-bids/<bid_id>/mark-lost")
def mark_lost_bid(bid_id):
    require_roles("SalesRep")
    b = get_bid_or_404(bid_id)
    if b["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Bid is not UNDER_REVIEW", 409)
    b["status"] = "LOST"
    svc.touch(b)
    return success_object(dict(b))


@bp.post("/jansan/contract-bids/<bid_id>/terminate")
def terminate_bid(bid_id):
    require_roles("DistributorAdmin")
    b = get_bid_or_404(bid_id)
    if b["status"] != "AWARDED":
        raise ApiError(ERR_INVALID_STATE, "Bid is not AWARDED", 409)
    b["status"] = "TERMINATED"
    svc.touch(b)
    svc.cascade_bid_to_standing_orders(b)
    return success_object(dict(b))
