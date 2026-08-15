from datetime import timedelta

from flask import Blueprint, request

import errors
from db import DB, CLOCK, new_id, stamp_new, touch, iso_now
from middleware import (
    get_context, require_role, get_json_body, require_fields, reject_unexpected,
    require_int, parse_limit_offset,
)
from response import success_object, success_list
from services import bids as bid_svc
from services import prequal as prequal_svc

bp = Blueprint("bids", __name__)

ESTIMATORS = {"LeadEstimator", "ChiefEstimator", "PrequalReviewer"}
ALL_READERS = ESTIMATORS | {"Subcontractor"}

TERMINAL_BID_STATES = {"AWARDED", "NOT_AWARDED", "DISQUALIFIED", "WITHDRAWN"}
LAST_MINUTE_WINDOW = timedelta(minutes=60)


def serialize_bid(bid):
    return {
        "id": bid["id"],
        "bid_package_id": bid["bid_package_id"],
        "subcontractor_id": bid["subcontractor_id"],
        "base_bid_cents": bid["base_bid_cents"],
        "bond_amount_cents": bid["bond_amount_cents"],
        "submitted_at": bid["submitted_at"],
        "addendum_ack_complete": bid["addendum_ack_complete"],
        "disqualification_reason": bid["disqualification_reason"],
        "status": bid["status"],
        "created_at": bid["created_at"],
        "updated_at": bid["updated_at"],
        "version": bid["version"],
    }


def serialize_revision(rev):
    # BidRevision carries only id + created_at from the common set; no updated_at/version
    return {
        "id": rev["id"],
        "bid_id": rev["bid_id"],
        "sequence": rev["sequence"],
        "amount_cents": rev["amount_cents"],
        "note": rev["note"],
        "is_last_minute": rev["is_last_minute"],
        "revised_at": rev["revised_at"],
        "created_at": rev["created_at"],
    }


def get_bid_or_404(bid_id):
    bid = DB.bids.get(bid_id)
    if bid is None:
        raise errors.err_bid_not_found()
    return bid


def _is_last_minute(pkg, when_dt):
    return (pkg["_bid_due_at_dt"] - when_dt) <= LAST_MINUTE_WINDOW


@bp.post("/bids")
def create_bid():
    user_id, role = get_context()
    require_role(role, {"Subcontractor"})
    body = get_json_body()
    reject_unexpected(body, {"bid_package_id", "base_bid_cents", "bond_amount_cents"})
    require_fields(body, ["bid_package_id", "base_bid_cents", "bond_amount_cents"])
    pkg_id = body["bid_package_id"]
    if not isinstance(pkg_id, str):
        raise errors.err_invalid_request("bid_package_id must be a string")
    # Existence (priority 3)
    pkg = DB.bid_packages.get(pkg_id)
    if pkg is None:
        raise errors.err_package_not_found()
    base = require_int(body, "base_bid_cents", strict_minimum=0)
    bond = require_int(body, "bond_amount_cents", minimum=0)

    # State gate (priority 5): package PUBLISHED
    if pkg["status"] != "PUBLISHED":
        raise errors.err_package_not_accepting_bids()
    # Business-safety (priority 6): prequal gate — lazy expiry applied first
    # Uniqueness/eligibility (priority 7): invitation BIDDING, no duplicate bid
    inv = next(
        (i for i in DB.invitations.values()
         if i["bid_package_id"] == pkg_id and i["subcontractor_id"] == user_id),
        None,
    )
    if inv is None or inv["status"] != "BIDDING":
        raise errors.err_invitation_not_bidding()
    if bid_svc.submitted_bid(pkg_id, user_id) is not None:
        raise errors.err_duplicate_bid()
    if not prequal_svc.has_approved_prequal(user_id):
        raise errors.err_prequal_not_approved()
    # Deadline gate (priority 8): strict now < bid_due_at
    now = CLOCK.now()
    if now >= pkg["_bid_due_at_dt"]:
        raise errors.err_deadline_passed()
    # Bond gate (priority 9)
    required = bid_svc.required_bid_bond(base, pkg["bid_bond_required_pct"])
    if bond < required:
        raise errors.err_bond_insufficient()

    bid = {
        "id": new_id(),
        "bid_package_id": pkg_id,
        "subcontractor_id": user_id,
        "base_bid_cents": base,
        "bond_amount_cents": bond,
        "submitted_at": iso_now(),
        "_submitted_at_dt": now,
        "addendum_ack_complete": bid_svc.pending_ack_count(pkg_id, user_id) == 0,
        "disqualification_reason": None,
        "status": "SUBMITTED",
    }
    stamp_new(bid)  # version starts at 1
    bid["_created_at_dt"] = now
    DB.bids[bid["id"]] = bid

    rev = {
        "id": new_id(),
        "bid_id": bid["id"],
        "sequence": 1,
        "amount_cents": base,
        "note": None,
        "is_last_minute": _is_last_minute(pkg, now),
        "revised_at": iso_now(),
    }
    stamp_new(rev, with_version=False)
    rev["_created_at_dt"] = now
    DB.bid_revisions[rev["id"]] = rev

    pkg["submitted_bid_count"] += 1
    touch(pkg)
    return success_object(serialize_bid(bid), 201)


@bp.get("/bids")
def list_bids():
    user_id, role = get_context()
    require_role(role, ALL_READERS)
    limit, offset = parse_limit_offset(request.args)
    pkg_f = request.args.get("bid_package_id")
    sub_f = request.args.get("subcontractor_id")
    status_f = request.args.get("status")
    items = sorted(DB.bids.values(), key=lambda b: (b["_created_at_dt"], b["id"]))
    if role == "Subcontractor":
        items = [b for b in items if b["subcontractor_id"] == user_id]
    if pkg_f is not None:
        items = [b for b in items if b["bid_package_id"] == pkg_f]
    if sub_f is not None:
        items = [b for b in items if b["subcontractor_id"] == sub_f]
    if status_f is not None:
        items = [b for b in items if b["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_bid(b) for b in page], limit, offset, total)


@bp.get("/bids/<bid_id>")
def read_bid(bid_id):
    user_id, role = get_context()
    require_role(role, ALL_READERS)
    bid = get_bid_or_404(bid_id)
    if role == "Subcontractor" and bid["subcontractor_id"] != user_id:
        raise errors.err_forbidden_ownership()
    return success_object(serialize_bid(bid))


@bp.post("/bids/<bid_id>/revisions")
def revise_bid(bid_id):
    user_id, role = get_context()
    require_role(role, {"Subcontractor"})
    bid = get_bid_or_404(bid_id)
    body = get_json_body()
    reject_unexpected(body, {"new_base_bid_cents", "expected_bid_version", "note"})
    require_fields(body, ["new_base_bid_cents", "expected_bid_version"])
    new_base = require_int(body, "new_base_bid_cents", strict_minimum=0)
    expected = require_int(body, "expected_bid_version")
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise errors.err_invalid_request("note must be a string")

    # Ownership (priority 4)
    if bid["subcontractor_id"] != user_id:
        raise errors.err_forbidden_ownership()
    # State gate (priority 5): bid non-terminal and package PUBLISHED
    if bid["status"] != "SUBMITTED":
        raise errors.err_bid_invalid_state()
    pkg = DB.bid_packages.get(bid["bid_package_id"])
    if pkg is None or pkg["status"] != "PUBLISHED":
        raise errors.err_package_not_accepting_bids()
    # Deadline gate (priority 8)
    now = CLOCK.now()
    if now >= pkg["_bid_due_at_dt"]:
        raise errors.err_deadline_passed()
    # Bond gate (priority 9) re-checked against the new amount
    required = bid_svc.required_bid_bond(new_base, pkg["bid_bond_required_pct"])
    if bid["bond_amount_cents"] < required:
        raise errors.err_bond_insufficient()
    # OCC
    if expected != bid["version"]:
        raise errors.err_stale_version()

    bid["base_bid_cents"] = new_base
    touch(bid)  # version += 1

    max_seq = max(
        (r["sequence"] for r in DB.bid_revisions.values() if r["bid_id"] == bid["id"]),
        default=0,
    )
    rev = {
        "id": new_id(),
        "bid_id": bid["id"],
        "sequence": max_seq + 1,
        "amount_cents": new_base,
        "note": note,
        "is_last_minute": _is_last_minute(pkg, now),
        "revised_at": iso_now(),
    }
    stamp_new(rev, with_version=False)
    rev["_created_at_dt"] = now
    DB.bid_revisions[rev["id"]] = rev
    return success_object(serialize_bid(bid))


@bp.get("/bids/<bid_id>/revisions")
def list_revisions(bid_id):
    user_id, role = get_context()
    require_role(role, ALL_READERS)
    bid = get_bid_or_404(bid_id)
    if role == "Subcontractor" and bid["subcontractor_id"] != user_id:
        raise errors.err_forbidden_ownership()
    limit, offset = parse_limit_offset(request.args)
    items = sorted(
        (r for r in DB.bid_revisions.values() if r["bid_id"] == bid_id),
        key=lambda r: r["sequence"],
    )
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_revision(r) for r in page], limit, offset, total)


@bp.post("/bids/<bid_id>/withdraw")
def withdraw_bid(bid_id):
    user_id, role = get_context()
    require_role(role, {"Subcontractor"})
    bid = get_bid_or_404(bid_id)
    if bid["subcontractor_id"] != user_id:
        raise errors.err_forbidden_ownership()
    if bid["status"] != "SUBMITTED":
        raise errors.err_bid_invalid_state()
    pkg = DB.bid_packages.get(bid["bid_package_id"])
    if pkg is None or pkg["status"] != "PUBLISHED":
        raise errors.err_package_not_accepting_bids()
    bid["status"] = "WITHDRAWN"
    touch(bid)
    pkg["submitted_bid_count"] -= 1
    touch(pkg)
    return success_object(serialize_bid(bid))


@bp.get("/bids/<bid_id>/leveling-sheet")
def leveling_sheet(bid_id):
    _, role = get_context()
    require_role(role, {"LeadEstimator", "ChiefEstimator"})
    bid = get_bid_or_404(bid_id)
    adjustments = sorted(
        (a for a in DB.leveling_adjustments.values() if a["bid_id"] == bid_id),
        key=lambda a: (a["_created_at_dt"], a["id"]),
    )
    from routes.leveling import serialize_adjustment
    pending = bid_svc.pending_ack_count(bid["bid_package_id"], bid["subcontractor_id"])
    is_compliant = (
        bid["status"] == "SUBMITTED"
        and pending == 0
        and prequal_svc.has_approved_prequal(bid["subcontractor_id"])
    )
    sheet = {
        "bid_id": bid["id"],
        "base_bid_cents": bid["base_bid_cents"],
        "adjustments": [serialize_adjustment(a) for a in adjustments],
        "leveled_amount_cents": bid_svc.leveled_amount(bid),
        "has_exclusions": bid_svc.has_exclusions(bid),
        "pending_addendum_ack_count": pending,
        "is_compliant": is_compliant,
    }
    return success_object(sheet)


@bp.get("/bids/<bid_id>/leveling-adjustments")
def list_bid_adjustments(bid_id):
    _, role = get_context()
    require_role(role, {"LeadEstimator", "ChiefEstimator"})
    get_bid_or_404(bid_id)
    limit, offset = parse_limit_offset(request.args)
    items = sorted(
        (a for a in DB.leveling_adjustments.values() if a["bid_id"] == bid_id),
        key=lambda a: (a["_created_at_dt"], a["id"]),
    )
    total = len(items)
    page = items[offset:offset + limit]
    from routes.leveling import serialize_adjustment
    return success_list([serialize_adjustment(a) for a in page], limit, offset, total)


@bp.get("/bids/<bid_id>/post-bid-interviews")
def list_bid_interviews(bid_id):
    _, role = get_context()
    require_role(role, ESTIMATORS)
    get_bid_or_404(bid_id)
    limit, offset = parse_limit_offset(request.args)
    items = sorted(
        (i for i in DB.interviews.values() if i["bid_id"] == bid_id),
        key=lambda i: (i["_created_at_dt"], i["id"]),
    )
    total = len(items)
    page = items[offset:offset + limit]
    from routes.interviews import serialize_interview
    return success_list([serialize_interview(i) for i in page], limit, offset, total)


@bp.get("/bids/<bid_id>/award-recommendations")
def list_bid_recommendations(bid_id):
    _, role = get_context()
    require_role(role, ESTIMATORS)
    get_bid_or_404(bid_id)
    limit, offset = parse_limit_offset(request.args)
    items = sorted(
        (r for r in DB.recommendations.values() if r["recommended_bid_id"] == bid_id),
        key=lambda r: (r["_created_at_dt"], r["id"]),
    )
    total = len(items)
    page = items[offset:offset + limit]
    from routes.recommendations import serialize_recommendation
    return success_list([serialize_recommendation(r) for r in page], limit, offset, total)


@bp.get("/bids/<bid_id>/bidder-feedbacks")
def list_bid_feedbacks(bid_id):
    user_id, role = get_context()
    require_role(role, {"LeadEstimator", "ChiefEstimator", "Subcontractor"})
    bid = get_bid_or_404(bid_id)
    if role == "Subcontractor" and bid["subcontractor_id"] != user_id:
        raise errors.err_forbidden_ownership()
    limit, offset = parse_limit_offset(request.args)
    items = sorted(
        (f for f in DB.feedbacks.values() if f["bid_id"] == bid_id),
        key=lambda f: (f["_created_at_dt"], f["id"]),
    )
    if role == "Subcontractor":
        # DRAFT feedback is never visible to a subcontractor
        items = [f for f in items if f["status"] == "SENT"]
    total = len(items)
    page = items[offset:offset + limit]
    from routes.feedbacks import serialize_feedback
    return success_list([serialize_feedback(f) for f in page], limit, offset, total)
