"""Auction execution (PRD §3.5) and auction-record endpoints (§3.6)."""

from flask import Blueprint, request

from db import store
from errors import (
    not_found, invalid_request, ApiError,
    ERR_ALREADY_CONFIRMED, ERR_ALREADY_VOIDED, ERR_VOID_AFTER_SETTLEMENT,
)
from middleware import (
    require_roles, ALL_ROLES, ROLE_DEMAND_SIDE, ROLE_EXCHANGE_ADMIN,
)
from response import success_object, success_list, paginate
from util import get_body
from services.core import (
    touch, serialize_record, execute_auction, recompute_publisher_accruals, _sorted,
)

bp = Blueprint("auctions", __name__)


@bp.route("/auctions/execute", methods=["POST"])
def execute():
    require_roles([ROLE_DEMAND_SIDE])
    body = get_body()
    publisher_id = body.get("publisher_id")
    if not isinstance(publisher_id, str) or publisher_id == "":
        raise invalid_request("publisher_id is required and must be a non-empty string")
    bids = body.get("bids")
    if not isinstance(bids, list) or len(bids) == 0:
        raise invalid_request("bids must be a non-empty array")
    for i, b in enumerate(bids):
        if not isinstance(b, dict):
            raise invalid_request(f"bids[{i}] must be an object")
        v = b.get("bid_cpm_micros")
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise invalid_request(f"bids[{i}].bid_cpm_micros must be a positive integer")
        v = b.get("impression_count")
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise invalid_request(f"bids[{i}].impression_count must be a positive integer")
        v = b.get("creative_domain")
        if not isinstance(v, str) or v == "":
            raise invalid_request(f"bids[{i}].creative_domain must be a non-empty string")
    if publisher_id not in store.publishers:
        raise not_found("Publisher not found")
    outcome, record, throttled_deal_count = execute_auction(publisher_id, bids)
    return success_object({
        "outcome": outcome,
        "auction_record": serialize_record(record) if record is not None else None,
        "throttled_deal_count": throttled_deal_count,
    })


@bp.route("/auction-records", methods=["GET"])
def list_records():
    require_roles(ALL_ROLES)
    deal_id = request.args.get("deal_id")
    publisher_id = request.args.get("publisher_id")
    demand_partner_id = request.args.get("demand_partner_id")
    voided = request.args.get("voided")
    items = list(store.records.values())
    if deal_id is not None:
        items = [r for r in items if r["deal_id"] == deal_id]
    if publisher_id is not None:
        items = [r for r in items if r["publisher_id"] == publisher_id]
    if demand_partner_id is not None:
        items = [r for r in items if r["demand_partner_id"] == demand_partner_id]
    if voided is not None:
        if voided == "true":
            items = [r for r in items if r["voided"]]
        elif voided == "false":
            items = [r for r in items if not r["voided"]]
        else:
            items = []
    page, limit, offset, total = paginate(_sorted(items), request.args)
    return success_list([serialize_record(r) for r in page], limit, offset, total)


@bp.route("/auction-records/<recordId>", methods=["GET"])
def get_record(recordId):
    require_roles(ALL_ROLES)
    r = store.records.get(recordId)
    if r is None:
        raise not_found("AuctionRecord not found")
    return success_object(serialize_record(r))


@bp.route("/auction-records/<recordId>/confirm-billing", methods=["POST"])
def confirm_billing(recordId):
    require_roles([ROLE_DEMAND_SIDE])
    r = store.records.get(recordId)
    if r is None:
        raise not_found("AuctionRecord not found")
    if r["_confirmed_dt"] is not None:
        raise ApiError(ERR_ALREADY_CONFIRMED, 409,
                       "AuctionRecord billing is already confirmed")
    # weightless on the ledger: only the payable basis moves (§3.6); records
    # carry no version, so there is nothing to bump
    r["_confirmed_dt"] = store.now()
    return success_object(serialize_record(r))


@bp.route("/auction-records/<recordId>/void", methods=["POST"])
def void_record(recordId):
    require_roles([ROLE_EXCHANGE_ADMIN])
    r = store.records.get(recordId)
    if r is None:
        raise not_found("AuctionRecord not found")
    if r["voided"]:
        raise ApiError(ERR_ALREADY_VOIDED, 409, "AuctionRecord is already voided")
    # settlement protection (stage 16): a record whose creation UTC date falls
    # inside a SETTLED batch's period can never be voided
    created_date = r["_created_dt"].date()
    for b in store.payout_batches.values():
        if b["status"] == "SETTLED" and b["period_start"] <= created_date < b["period_end"]:
            raise ApiError(ERR_VOID_AFTER_SETTLEMENT, 409,
                           "Record's creation date falls inside a SETTLED batch period")
    r["voided"] = True
    r["_voided_dt"] = store.now()
    # reverse everything the fill created (spend_conservation /
    # publisher_accrual)
    partner = store.partners[r["demand_partner_id"]]
    partner["lifetime_spend_micros"] -= r["gross_micros"]
    if created_date == store.now().date():
        partner["spend_today_micros"] -= r["gross_micros"]
    touch(partner)
    deal = store.deals.get(r["deal_id"])
    if deal is not None:
        deal["delivered_impressions"] -= r["impressions"]
        touch(deal)
    pub = store.publishers.get(r["publisher_id"])
    if pub is not None:
        recompute_publisher_accruals(pub)
    return success_object(serialize_record(r))
