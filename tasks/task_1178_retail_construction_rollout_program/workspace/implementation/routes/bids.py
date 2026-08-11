"""Bid endpoints (§3.4): identity ownership, window gates, responsiveness."""
from flask import Blueprint, g

import clock
from db import store
from errors import ApiError, forbidden_identity, invalid_request
from middleware import ALL_ROLES, authed
from response import ok, paginate
from routes import apply_filters, require_state
from routes.bid_packages import live_score
from util import bump, iso_ms, new_entity, serialize, sort_key
from validate import body_fk, get_or_404, is_int, json_body

bp = Blueprint("bids", __name__)

TERMINAL = ("WITHDRAWN", "AWARDED", "REJECTED")


def serialize_bid(bid):
    data = serialize(bid)
    package = store.packages.get(bid["bid_package_id"])
    if package is not None and package["status"] != "AWARDED":
        data["evaluation_score"] = live_score(package, bid)
    return data


@bp.route("/rollout/bids", methods=["POST"], strict_slashes=False)
@authed(["GCVendor"])
def create_bid():
    body = json_body()
    # Step 3 — identity ownership: contractor_id must equal X-User-ID.
    contractor_id = body.get("contractor_id")
    if contractor_id != g.user_id:
        forbidden_identity("contractor_id must equal X-User-ID")
    # Step 4 — existence of body-referenced identifiers.
    package = body_fk(body, "bid_package_id", store.packages)
    contractor = body_fk(body, "contractor_id", store.contractors)
    # Step 5 — domain state gates (contractor, then package, per §3.4 order).
    if contractor is not None and contractor["status"] != "PREQUALIFIED":
        raise ApiError("ERR_CONTRACTOR_NOT_PREQUALIFIED", 409,
                       "contractor is SUSPENDED")
    if package is not None and package["status"] != "OPEN":
        raise ApiError("ERR_BID_PACKAGE_NOT_OPEN", 409, "package is not OPEN")
    # Step 9 — submissions at/after bid_close_at are refused.
    if package is not None:
        from util import parse_datetime
        if clock.now() >= parse_datetime(package["bid_close_at"]):
            raise ApiError("ERR_BID_WINDOW_CLOSED", 409,
                           "bid_close_at has been reached")
        # Step 10 — one SUBMITTED bid per contractor per package.
        duplicate = any(
            b["bid_package_id"] == package["id"]
            and b["contractor_id"] == contractor_id
            and b["status"] == "SUBMITTED"
            for b in store.bids.values()
        )
        if duplicate:
            raise ApiError("ERR_DUPLICATE_BID", 409,
                           "contractor already holds a SUBMITTED bid on this package")
    # Step 12 — request shape.
    if package is None:
        invalid_request("field 'bid_package_id' is required")
    amount = body.get("amount_cents")
    if not is_int(amount):
        invalid_request("field 'amount_cents' is required and must be an integer")
    duration = body.get("duration_days")
    if not is_int(duration):
        invalid_request("field 'duration_days' is required and must be an integer")
    tech = body.get("tech_score")
    if not is_int(tech) or tech < 0 or tech > 100:
        invalid_request("field 'tech_score' must be an integer in 0..100")

    bid = new_entity(store)
    bid.update({
        "bid_package_id": package["id"],
        "contractor_id": contractor_id,
        "amount_cents": amount,
        "duration_days": duration,
        "tech_score": tech,
        "is_responsive": (amount > 0 and duration > 0
                          and duration <= package["max_duration_days"]),
        "evaluation_score": None,
        "submitted_at": iso_ms(clock.now()),
        "status": "SUBMITTED",
    })
    store.bids[bid["id"]] = bid
    return ok(serialize_bid(bid), status=201)


@bp.route("/rollout/bids", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def list_bids():
    items = sorted(store.bids.values(), key=sort_key)
    items = apply_filters(items, [
        ("bid_package_id", "bid_package_id", "str"),
        ("contractor_id", "contractor_id", "str"),
        ("status", "status", "str"),
    ])
    return paginate([serialize_bid(b) for b in items])


@bp.route("/rollout/bids/<bidId>", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def get_bid(bidId):
    return ok(serialize_bid(get_or_404(store.bids, bidId, "bid")))


@bp.route("/rollout/bids/<bidId>/withdraw", methods=["POST"], strict_slashes=False)
@authed(["GCVendor"])
def withdraw_bid(bidId):
    bid = get_or_404(store.bids, bidId, "bid")
    # Step 3 — own bids only.
    if bid["contractor_id"] != g.user_id:
        forbidden_identity("only the owning contractor may withdraw this bid")
    require_state(bid, ("SUBMITTED",), TERMINAL)
    package = store.packages.get(bid["bid_package_id"])
    if package is not None and package["status"] == "AWARDED":
        raise ApiError("ERR_INVALID_STATE", 409, "package is already AWARDED")
    bid["status"] = "WITHDRAWN"
    bump(bid)
    return ok(serialize_bid(bid))
