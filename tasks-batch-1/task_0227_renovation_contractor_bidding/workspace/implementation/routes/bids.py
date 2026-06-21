"""Bid routes: CRUD, line-items, submit/revise/withdraw state machine."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles
from services import common, lookups, calculations

bp = Blueprint("bids", __name__)


def _owner_check_bid(bid, user_id, role):
    if role == "Contractor" and bid["contractor_id"] != user_id:
        raise errors.not_owner("Contractor does not own this bid.")


@bp.route("/bids", methods=["POST"])
def create_bid():
    user_id, role = require_roles("Contractor")
    body = common.get_body()
    project_id = common.as_str(common.require_field(body, "project_id"), "project_id")
    contractor_id = common.as_str(common.require_field(body, "contractor_id"), "contractor_id")
    duration_days = common.as_int(common.require_field(body, "duration_days"), "duration_days")
    if duration_days <= 0:
        raise errors.invalid_request("duration_days must be > 0.")
    # existence
    lookups.get_project(project_id)
    lookups.get_contractor(contractor_id)
    # ownership: contractor creates bids under their own id
    if contractor_id != user_id:
        raise errors.not_owner("Contractor can only create bids for themselves.")

    rec = {
        "project_id": project_id,
        "contractor_id": contractor_id,
        "total_cents": 0,
        "duration_days": duration_days,
        "status": "DRAFT",
        "rank_score": 0,
    }
    common.stamp_new(rec)
    db.bids[rec["id"]] = rec
    return response.success(common.public(rec), 201)


@bp.route("/bids/<rid>", methods=["GET"])
def get_bid(rid):
    require_roles("Contractor", "Homeowner", "PlatformAdmin")
    rec = lookups.get_bid(rid)
    return response.success(common.public(rec), 200)


@bp.route("/bids", methods=["GET"])
def list_bids():
    require_roles("Contractor", "Homeowner", "PlatformAdmin")
    items = list(db.bids.values())
    pid = request.args.get("project_id")
    if pid is not None:
        items = [b for b in items if b["project_id"] == pid]
    cid = request.args.get("contractor_id")
    if cid is not None:
        items = [b for b in items if b["contractor_id"] == cid]
    st = request.args.get("status")
    if st is not None:
        items = [b for b in items if b["status"] == st]
    page, limit, offset, total = common.paginate(items)
    return response.success_list(page, limit, offset, total, 200)


@bp.route("/bids/<rid>/line-items", methods=["POST"])
def add_line_item(rid):
    user_id, role = require_roles("Contractor")
    bid = lookups.get_bid(rid)
    _owner_check_bid(bid, user_id, role)
    if bid["status"] not in ("DRAFT", "REVISING"):
        raise errors.invalid_state("Line items can only be added to a DRAFT/REVISING bid.")
    body = common.get_body()
    scope_line_item_id = common.as_str(
        common.require_field(body, "scope_line_item_id"), "scope_line_item_id")
    quantity = common.as_number(common.require_field(body, "quantity"), "quantity")
    if quantity <= 0:
        raise errors.invalid_request("quantity must be > 0.")
    unit_price = common.as_int(common.require_field(body, "unit_price_cents"), "unit_price_cents")
    if unit_price < 0:
        raise errors.invalid_request("unit_price_cents must be >= 0.")
    scope = lookups.get_scope_line_item(scope_line_item_id)
    # scope line must belong to the bid's project (referential integrity)
    if scope["project_id"] != bid["project_id"]:
        raise errors.not_found("scope_line_item does not belong to this bid's project.")

    rec = {
        "bid_id": rid,
        "scope_line_item_id": scope_line_item_id,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "line_total_cents": calculations.line_total(quantity, unit_price),
    }
    common.stamp_new(rec)
    db.bid_line_items[rec["id"]] = rec
    # recompute bid total
    calculations.recompute_bid_total(bid)
    common.touch(bid)
    return response.success(common.public(rec), 201)


@bp.route("/bids/<rid>/line-items", methods=["GET"])
def list_line_items(rid):
    require_roles("Contractor", "Homeowner", "PlatformAdmin")
    lookups.get_bid(rid)
    items = lookups.line_items_for_bid(rid)
    page, limit, offset, total = common.paginate(items)
    return response.success_list(page, limit, offset, total, 200)


def _scope_coverage_ok(bid):
    """Every ScopeLineItem of the project is priced by exactly one BidLineItem."""
    scope_ids = {s["id"] for s in lookups.scope_items_for_project(bid["project_id"])}
    lines = lookups.line_items_for_bid(bid["id"])
    if not lines:
        return False
    counts = {}
    for li in lines:
        counts[li["scope_line_item_id"]] = counts.get(li["scope_line_item_id"], 0) + 1
    priced = set(counts.keys())
    # no missing, no duplicate
    if priced != scope_ids:
        return False
    if any(c != 1 for c in counts.values()):
        return False
    return True


@bp.route("/bids/<rid>/submit", methods=["POST"])
def submit_bid(rid):
    user_id, role = require_roles("Contractor")
    bid = lookups.get_bid(rid)
    _owner_check_bid(bid, user_id, role)
    project = lookups.get_project(bid["project_id"])
    contractor = lookups.get_contractor(bid["contractor_id"])

    # state (priority 5): DRAFT or REVISING -> SUBMITTED; project OPEN_FOR_BIDS
    if bid["status"] not in ("DRAFT", "REVISING"):
        raise errors.invalid_state("Only a DRAFT or REVISING bid can be submitted.")
    if project["status"] != "OPEN_FOR_BIDS":
        raise errors.invalid_state("Project must be OPEN_FOR_BIDS to submit a bid.")
    # deadline (priority 7)
    if db.clock.now() >= project["_bid_deadline_dt"]:
        raise errors.ApiError(errors.ERR_BID_DEADLINE_PASSED, 409,
                              "Bid deadline has passed.")
    # qualification (priority 8): QUALIFIED + trade match + license_expiry > bid_deadline
    if (contractor["qualification_status"] != "QUALIFIED"
            or contractor["trade"] != project["required_trade"]
            or contractor["_license_expiry_dt"] <= project["_bid_deadline_dt"]):
        raise errors.ApiError(errors.ERR_CONTRACTOR_NOT_QUALIFIED, 409,
                              "Contractor is not qualified to bid.")
    # rating floor (priority 9)
    if contractor["average_rating"] < project["min_rating"]:
        raise errors.ApiError(errors.ERR_RATING_BELOW_MINIMUM, 409,
                              "Contractor average_rating below project min_rating.")
    # scope coverage (priority 10)
    if not _scope_coverage_ok(bid):
        raise errors.ApiError(errors.ERR_INCOMPLETE_SCOPE_COVERAGE, 422,
                              "Bid must price every scope line exactly once.")

    calculations.recompute_bid_total(bid)
    bid["status"] = "SUBMITTED"
    common.touch(bid)
    return response.success(common.public(bid), 200)


@bp.route("/bids/<rid>/revise", methods=["POST"])
def revise_bid(rid):
    user_id, role = require_roles("Contractor")
    bid = lookups.get_bid(rid)
    _owner_check_bid(bid, user_id, role)
    project = lookups.get_project(bid["project_id"])
    if bid["status"] != "SUBMITTED":
        raise errors.invalid_state("Only a SUBMITTED bid can be revised.")
    if project["status"] != "OPEN_FOR_BIDS":
        raise errors.invalid_state("Project must be OPEN_FOR_BIDS to revise a bid.")
    if db.clock.now() >= project["_bid_deadline_dt"]:
        raise errors.ApiError(errors.ERR_BID_DEADLINE_PASSED, 409,
                              "Bid deadline has passed.")
    bid["status"] = "REVISING"
    common.touch(bid)
    return response.success(common.public(bid), 200)


@bp.route("/bids/<rid>/withdraw", methods=["POST"])
def withdraw_bid(rid):
    user_id, role = require_roles("Contractor")
    bid = lookups.get_bid(rid)
    _owner_check_bid(bid, user_id, role)
    project = lookups.get_project(bid["project_id"])
    if bid["status"] != "SUBMITTED":
        raise errors.invalid_state("Only a SUBMITTED bid can be withdrawn.")
    # allowed as long as project not yet AWARDED
    if project["status"] == "AWARDED":
        raise errors.invalid_state("Cannot withdraw after the project is awarded.")
    bid["status"] = "WITHDRAWN"
    common.touch(bid)
    return response.success(common.public(bid), 200)
