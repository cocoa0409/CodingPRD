"""Bid endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    bids_of,
    ensure_no_open_life_safety_gap,
    get_bid,
    get_package,
    ser_bid,
    sorted_created,
    stamp,
    touch,
)
from util import (
    as_int,
    as_iso_dt,
    as_list,
    as_str,
    body,
    pagination_args,
    parse_dt,
    required,
)

bp = Blueprint("bids", __name__)


def _validate_alternates(value):
    items = as_list(value, "alternates")
    for i, entry in enumerate(items):
        if not isinstance(entry, dict):
            raise ApiError("ERR_VALIDATION", 422, f"alternates[{i}] must be an object")
        as_str(required(entry, "alternate_id"), "alternate_id")
        as_int(required(entry, "price_delta_cents"), "price_delta_cents")
    return items


def _validate_allowances(value):
    items = as_list(value, "allowances")
    for i, entry in enumerate(items):
        if not isinstance(entry, dict):
            raise ApiError("ERR_VALIDATION", 422, f"allowances[{i}] must be an object")
        as_str(required(entry, "allowance_id"), "allowance_id")
        as_int(required(entry, "amount_cents"), "amount_cents")
    return items


@bp.post("/trade-packages/<pkg_id>/bids")
def create_bid(pkg_id):
    auth(["BuyoutLead", "Estimator"])
    pkg = get_package(pkg_id)
    data = body()
    bidder_name = as_str(required(data, "bidder_name"), "bidder_name")
    contact_email = as_str(required(data, "contact_email"), "contact_email")
    base_bid_cents = as_int(required(data, "base_bid_cents"), "base_bid_cents")
    bid_received_at = as_iso_dt(required(data, "bid_received_at"), "bid_received_at")
    alternates = data.get("alternates")
    if alternates is not None:
        _validate_alternates(alternates)
    allowances = data.get("allowances")
    if allowances is not None:
        _validate_allowances(allowances)
    if pkg["status"] not in ("PUBLISHED", "UNDER_LEVELING"):
        raise ApiError(
            "ERR_TRADE_PACKAGE_NOT_ACCEPTING_BIDS",
            409,
            "Package not in a state that accepts bids",
        )
    for b in bids_of(pkg):
        if b["bidder_name"] == bidder_name and b["status"] in ("PLACED", "AWARDED"):
            raise ApiError(
                "ERR_DUPLICATE_BIDDER",
                409,
                "Another PLACED/AWARDED bid with the same bidder_name exists on the package",
            )
    bid_due_at = pkg.get("bid_due_at")
    if bid_due_at is not None and parse_dt(bid_received_at) > parse_dt(bid_due_at):
        raise ApiError(
            "ERR_BID_AFTER_DEADLINE",
            409,
            "bid_received_at strictly after package bid_due_at",
        )
    rec = {
        "id": new_id(),
        "trade_package_id": pkg["id"],
        "bidder_name": bidder_name,
        "contact_email": contact_email,
        "base_bid_cents": base_bid_cents,
        "alternates": alternates or [],
        "allowances": allowances or [],
        "bid_received_at": bid_received_at,
        "leveled_value_cents": base_bid_cents,
        "status": "PLACED",
    }
    stamp(rec)
    DB["bids"][rec["id"]] = rec
    return ok(ser_bid(rec), status=201)


@bp.get("/trade-packages/<pkg_id>/bids")
def list_bids(pkg_id):
    auth(ALL_ROLES)
    pkg = get_package(pkg_id)
    limit, offset = pagination_args()
    status = request.args.get("status")
    items = sorted_created(bids_of(pkg))
    if status is not None:
        items = [b for b in items if b["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_bid(b) for b in page], total, limit, offset)


@bp.get("/bids/<bid_id>")
def get_one_bid(bid_id):
    auth(ALL_ROLES)
    return ok(ser_bid(get_bid(bid_id)))


@bp.post("/trade-packages/<pkg_id>/bids/<bid_id>/withdraw")
def withdraw_bid(pkg_id, bid_id):
    auth(["BuyoutLead", "OperationsManager"])
    pkg = get_package(pkg_id)
    bid = get_bid(bid_id, pkg["id"])
    if bid["status"] != "PLACED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Bid is not in PLACED"
        )
    bid["status"] = "WITHDRAWN"
    touch(bid)
    return ok(ser_bid(bid))


@bp.post("/trade-packages/<pkg_id>/bids/<bid_id>/award")
def award_bid(pkg_id, bid_id):
    auth(["BuyoutLead"])
    pkg = get_package(pkg_id)
    bid = get_bid(bid_id, pkg["id"])
    if pkg["status"] != "UNDER_LEVELING":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Trade package is not UNDER_LEVELING"
        )
    # Empty candidate set is evaluated BEFORE the target-bid status check.
    if not any(b["status"] in ("PLACED", "AWARDED") for b in bids_of(pkg)):
        raise ApiError(
            "ERR_NO_AWARDABLE_BID",
            409,
            "No bid on the package is PLACED or AWARDED",
        )
    if bid["status"] != "PLACED":
        raise ApiError("ERR_BID_NOT_AWARDABLE", 409, "Target bid not PLACED")
    ensure_no_open_life_safety_gap(pkg)
    bid["status"] = "AWARDED"
    touch(bid)
    return ok(ser_bid(bid))


@bp.post("/bids/<bid_id>/un-award")
def un_award_bid(bid_id):
    auth(["BuyoutLead", "OperationsManager"])
    bid = get_bid(bid_id)
    if bid["status"] != "AWARDED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Bid is not in AWARDED"
        )
    linked = [s for s in DB["subcontracts"].values() if s["source_bid_id"] == bid["id"]]
    if linked:
        sub = sorted_created(linked)[0]
        if sub["status"] != "PENDING_AWARD":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                "Linked subcontract has already left PENDING_AWARD",
            )
        sub["status"] = "DRAFT"
        sub["contract_value_cents"] = 0
        touch(sub)
    bid["status"] = "PLACED"
    touch(bid)
    return ok(ser_bid(bid))
