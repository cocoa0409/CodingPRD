import db
from errors import raise_error
from flask import Blueprint, request
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from serializers import serialize
from services import calculations as calc
from util import (apply_filters, get_json_body, get_pagination, opt_number,
                  opt_string, paginate, req_enum, req_int, req_number,
                  req_string as _req_string, sorted_by_created, stamp_new, touch)

bp = Blueprint("bids", __name__)

EXCLUSIVITY_REQUESTS = {"MATCH_PACKAGE", "NARROWER", "BROADER"}


def _get_package_or_404(package_id):
    p = db.packages.get(package_id)
    if p is None:
        raise_error("ERR_PACKAGE_NOT_FOUND")
    return p


def _get_bid_or_404(bid_id):
    b = db.bids.get(bid_id)
    if b is None:
        raise_error("ERR_BID_NOT_FOUND")
    return b


def _get_bid_scoped(package_id, bid_id):
    _get_package_or_404(package_id)
    bid = db.bids.get(bid_id)
    if bid is None or bid["package_id"] != package_id:
        raise_error("ERR_BID_NOT_FOUND")
    return bid


def _validate_bid_business(package, bidder, body):
    """Filing business checks in fixed order (§3.3):
    1. BROADER exclusivity requires INVESTMENT_GRADE.
    2. offered_fee_cents >= package.minimum_bid_cents.
    3. production_commitment_games >= package.games_committed."""
    exclusivity_request = body.get("exclusivity_request")
    if exclusivity_request == "BROADER" and bidder["credit_rating"] != "INVESTMENT_GRADE":
        raise_error("ERR_BIDDER_NOT_GRADE_FOR_BROADER")
    offered_fee_cents = body.get("offered_fee_cents")
    if not isinstance(offered_fee_cents, int) or isinstance(offered_fee_cents, bool) or offered_fee_cents < 0:
        raise_error("ERR_INVALID_REQUEST", "offered_fee_cents must be an integer >= 0")
    if offered_fee_cents < package["minimum_bid_cents"]:
        raise_error("ERR_BID_BELOW_FLOOR")
    production_commitment_games = body.get("production_commitment_games")
    if not isinstance(production_commitment_games, int) or isinstance(production_commitment_games, bool) or production_commitment_games < 0:
        raise_error("ERR_INVALID_REQUEST", "production_commitment_games must be an integer >= 0")
    if production_commitment_games < package["games_committed"]:
        raise_error("ERR_COMMITMENT_BELOW_PACKAGE")
    return offered_fee_cents, production_commitment_games


@bp.route("/packages/<packageId>/bids", methods=["POST"])
def create_bid(packageId):
    user_id, _ = require_roles({"BidCoordinator"})
    package = _get_package_or_404(packageId)
    body = get_json_body()
    bidder_id = body.get("bidder_id")
    if not isinstance(bidder_id, str) or bidder_id not in db.broadcasters:
        raise_error("ERR_BROADCASTER_NOT_FOUND")
    bidder = db.broadcasters[bidder_id]
    exclusivity_request = req_enum(body, "exclusivity_request", EXCLUSIVITY_REQUESTS)
    offered_fee_cents, production_commitment_games = _validate_bid_business(package, bidder, {
        "exclusivity_request": exclusivity_request,
        "offered_fee_cents": body.get("offered_fee_cents"),
        "production_commitment_games": body.get("production_commitment_games"),
    })
    upfront_pct = req_number(body, "upfront_pct")
    if not (0.0 <= upfront_pct <= 1.0):
        raise_error("ERR_INVALID_REQUEST", "upfront_pct must be within [0.0, 1.0]")
    escalator_rate_pct = req_number(body, "escalator_rate_pct")
    if not (0.0 <= escalator_rate_pct <= 0.25):
        raise_error("ERR_INVALID_REQUEST", "escalator_rate_pct must be within [0.0, 0.25]")
    minimum_growth_pct = opt_number(body, "minimum_growth_pct", default=0.0)
    fee_cap_cents = req_int(body, "fee_cap_cents", minimum=0)
    if fee_cap_cents < package["minimum_bid_cents"]:
        raise_error("ERR_INVALID_REQUEST", "fee_cap_cents must be >= the package minimum_bid_cents")
    audience_commitment_pct = req_number(body, "audience_commitment_pct")
    if not (0.0 < audience_commitment_pct <= 1.5):
        raise_error("ERR_INVALID_REQUEST", "audience_commitment_pct must be within (0.0, 1.5]")

    parent_bid_id = opt_string(body, "parent_bid_id")
    round_number = 1
    if parent_bid_id:
        parent = db.bids.get(parent_bid_id)
        if parent is None:
            raise_error("ERR_BID_NOT_FOUND")
        round_number = parent["round_number"] + 1

    bid = {
        "package_id": packageId,
        "bidder_id": bidder_id,
        "round_number": round_number,
        "offered_fee_cents": offered_fee_cents,
        "upfront_pct": upfront_pct,
        "escalator_rate_pct": escalator_rate_pct,
        "minimum_growth_pct": minimum_growth_pct,
        "fee_cap_cents": fee_cap_cents,
        "production_commitment_games": production_commitment_games,
        "audience_commitment_pct": audience_commitment_pct,
        "exclusivity_request": exclusivity_request,
        "parent_bid_id": parent_bid_id,
        "status": "DRAFT",
    }
    stamp_new(bid)
    db.bids[bid["id"]] = bid
    return success_object(serialize(bid), status_code=201)


@bp.route("/packages/<packageId>/bids", methods=["GET"])
def list_bids(packageId):
    require_roles(ALL_ROLES)
    _get_package_or_404(packageId)
    limit, offset = get_pagination()
    items = [b for b in db.bids.values() if b["package_id"] == packageId]
    items = sorted_by_created(items)
    items = apply_filters(items, [
        ("status", request.args.get("status")),
        ("bidder_id", request.args.get("bidder_id")),
        ("package_id", request.args.get("package_id")),
        ("parent_bid_id", request.args.get("parent_bid_id")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(b) for b in page], limit, offset, total)


@bp.route("/packages/<packageId>/bids/<bidId>", methods=["GET"])
def get_bid(packageId, bidId):
    require_roles(ALL_ROLES)
    return success_object(serialize(_get_bid_scoped(packageId, bidId)))


@bp.route("/bids", methods=["GET"])
def list_bids_flat():
    require_roles(ALL_ROLES)
    limit, offset = get_pagination()
    items = sorted_by_created(list(db.bids.values()))
    items = apply_filters(items, [
        ("package_id", request.args.get("package_id")),
        ("bidder_id", request.args.get("bidder_id")),
        ("parent_bid_id", request.args.get("parent_bid_id")),
        ("status", request.args.get("status")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(b) for b in page], limit, offset, total)


@bp.route("/bids/<bidId>", methods=["GET"])
def get_bid_flat(bidId):
    require_roles(ALL_ROLES)
    return success_object(serialize(_get_bid_or_404(bidId)))


@bp.route("/packages/<packageId>/bids/<bidId>/submit", methods=["POST"])
def submit_bid(packageId, bidId):
    require_roles({"BidCoordinator"})
    bid = _get_bid_scoped(packageId, bidId)
    package = db.packages[packageId]
    if bid["status"] != "DRAFT":
        raise_error("ERR_BID_NOT_DRAFT")
    if package["status"] not in ("OPEN_FOR_BIDS", "UNDER_NEGOTIATION"):
        raise_error("ERR_PACKAGE_NOT_ACCEPTING_BIDS")
    bidder = db.broadcasters.get(bid["bidder_id"])
    if bidder is None or bidder["status"] != "ACCREDITED":
        raise_error("ERR_BROADCASTER_NOT_ACCREDITED")
    # Submission re-runs the fee-floor and production-commitment checks.
    if bid["offered_fee_cents"] < package["minimum_bid_cents"]:
        raise_error("ERR_BID_BELOW_FLOOR")
    if bid["production_commitment_games"] < package["games_committed"]:
        raise_error("ERR_COMMITMENT_BELOW_PACKAGE")
    bid["status"] = "SUBMITTED"
    touch(bid)
    if package["status"] == "OPEN_FOR_BIDS":
        package["status"] = "UNDER_NEGOTIATION"
        touch(package)
    # A successor submission ends the countered parent's lifecycle (state already COUNTERED).
    parent_id = bid.get("parent_bid_id")
    if parent_id:
        parent = db.bids.get(parent_id)
        if parent is not None and parent["status"] == "COUNTERED":
            touch(parent)
    return success_object(serialize(bid))


@bp.route("/packages/<packageId>/bids/<bidId>/start-review", methods=["POST"])
def start_review(packageId, bidId):
    require_roles({"RightsManager"})
    bid = _get_bid_scoped(packageId, bidId)
    if bid["status"] != "SUBMITTED":
        raise_error("ERR_BID_NOT_SUBMITTED")
    bid["status"] = "UNDER_REVIEW"
    touch(bid)
    return success_object(serialize(bid))


@bp.route("/packages/<packageId>/bids/<bidId>/shortlist", methods=["POST"])
def shortlist_bid(packageId, bidId):
    require_roles({"RightsManager"})
    bid = _get_bid_scoped(packageId, bidId)
    if bid["status"] != "UNDER_REVIEW":
        raise_error("ERR_BID_NOT_UNDER_REVIEW")
    bid["status"] = "SHORTLISTED"
    touch(bid)
    return success_object(serialize(bid))


@bp.route("/packages/<packageId>/bids/<bidId>/counter", methods=["POST"])
def counter_bid(packageId, bidId):
    require_roles({"RightsManager"})
    bid = _get_bid_scoped(packageId, bidId)
    if bid["status"] != "SHORTLISTED":
        raise_error("ERR_BID_NOT_SHORTLISTED")
    bid["status"] = "COUNTERED"
    touch(bid)
    return success_object(serialize(bid))


@bp.route("/packages/<packageId>/bids/<bidId>/reject", methods=["POST"])
def reject_bid(packageId, bidId):
    require_roles({"RightsManager"})
    bid = _get_bid_scoped(packageId, bidId)
    if bid["status"] not in ("UNDER_REVIEW", "SHORTLISTED", "COUNTERED"):
        raise_error("ERR_BID_NOT_REJECTABLE")
    bid["status"] = "REJECTED"
    touch(bid)
    return success_object(serialize(bid))


@bp.route("/packages/<packageId>/bids/<bidId>/withdraw", methods=["POST"])
def withdraw_bid(packageId, bidId):
    require_roles({"BidCoordinator"})
    bid = _get_bid_scoped(packageId, bidId)
    if bid["status"] not in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "SHORTLISTED", "COUNTERED"):
        raise_error("ERR_BID_NOT_WITHDRAWABLE")
    bid["status"] = "WITHDRAWN"
    touch(bid)
    return success_object(serialize(bid))


@bp.route("/packages/<packageId>/bids/<bidId>/accept", methods=["POST"])
def accept_bid(packageId, bidId):
    require_roles({"RightsManager"})
    bid = _get_bid_scoped(packageId, bidId)
    package = db.packages[packageId]
    body = get_json_body()
    if "expected_package_version" not in body:
        raise_error("ERR_INVALID_REQUEST", "expected_package_version is required")
    expected = body["expected_package_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error("ERR_INVALID_REQUEST", "expected_package_version must be an integer")
    if expected != package["version"]:
        raise_error("ERR_STALE_PACKAGE_VERSION")
    if package["status"] != "UNDER_NEGOTIATION":
        raise_error("ERR_PACKAGE_NOT_NEGOTIATING")
    if bid["status"] != "SHORTLISTED":
        raise_error("ERR_BID_NOT_SHORTLISTED")
    for other in db.bids.values():
        if other["package_id"] == packageId and other["id"] != bid["id"] and other["status"] == "ACCEPTED":
            raise_error("ERR_PACKAGE_ALREADY_AWARDED")

    bid["status"] = "ACCEPTED"
    touch(bid)
    from services.system import bid_terminal_statuses
    for other in db.bids.values():
        if other["package_id"] == packageId and other["id"] != bid["id"] and other["status"] not in bid_terminal_statuses():
            other["status"] = "REJECTED"
            touch(other)
    package["status"] = "AWARDED"

    deal = {
        "asset_id": package["asset_id"],
        "package_id": package["id"],
        "winning_bid_id": bid["id"],
        "broadcaster_id": bid["bidder_id"],
        "executed_at": None,
        "term_start": None,
        "term_end": None,
        "base_fee_cents": bid["offered_fee_cents"],
        "escalator_rate_pct": bid["escalator_rate_pct"],
        "minimum_growth_pct": bid["minimum_growth_pct"],
        "fee_cap_cents": bid["fee_cap_cents"],
        "total_contracted_fee_cents": 0,
        "audience_commitment_basis_points": 0,
        "cumulative_rating_basis_points": 0,
        "accrued_shortfall_liability_cents": 0,
        "accrued_make_good_credit_cents": 0,
        "payment_delinquency_count": 0,
        "posture": "CLEAN",
        "status": "DRAFT",
    }
    stamp_new(deal)
    db.deals[deal["id"]] = deal

    package["awarded_bid_id"] = bid["id"]
    package["awarded_deal_id"] = deal["id"]
    touch(package)

    calc.run_exclusivity_scan(package["asset_id"])
    return success_object(serialize(deal))
