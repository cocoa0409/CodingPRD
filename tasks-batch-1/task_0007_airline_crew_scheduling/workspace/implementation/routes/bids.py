"""Bid routes (PRD §3.2)."""
from flask import Blueprint, request

import db
from errors import (
    not_found, forbidden, invalid_state, rank_seat_mismatch,
    duplicate_bid, cross_entity_state, invalid_request,
)
from middleware import require_roles, ROLE_PLANNER, ROLE_CREW
from response import success, paginated
from routes.common import (
    get_json_body, parse_pagination, sort_by_created_at, slice_page,
)
from services.constants import SEATS, rank_seat_compatible
from services import validate
from services.entity import stamp_new, touch


bp = Blueprint("bids", __name__)


BID_REQUIRED = ("pairing_id", "crew_member_id", "requested_seat")
BID_ALLOWED = set(BID_REQUIRED)


@bp.route("/bids", methods=["POST"])
def create_bid():
    user_id, role = require_roles({ROLE_CREW})
    body = validate.ensure_dict(get_json_body())
    validate.require_fields(body, BID_REQUIRED)
    validate.reject_extra(body, BID_ALLOWED)
    pairing_id = validate.check_string(body, "pairing_id")
    crew_member_id = validate.check_string(body, "crew_member_id")
    requested_seat = validate.check_enum(body, "requested_seat", SEATS)

    # FK existence (priority 4).
    p = db.pairings.get(pairing_id)
    if p is None:
        raise not_found("pairing_id does not resolve")
    cm = db.crew_members.get(crew_member_id)
    if cm is None:
        raise not_found("crew_member_id does not resolve")

    # Ownership: the bidder must be the acting user (PRD §2.1).
    if crew_member_id != user_id:
        raise forbidden("CrewMember can only bid using their own crew_member_id")

    # State eligibility: pairing must be BID_OPEN.
    if p["state"] != "BID_OPEN":
        raise invalid_state(f"Pairing is in state {p['state']!r}; cannot accept bids")

    # Rank-seat compatibility (PRD §3.2).
    if not rank_seat_compatible(cm["rank"], requested_seat):
        raise rank_seat_mismatch(
            f"Rank {cm['rank']!r} cannot bid for seat {requested_seat!r}"
        )

    # Bid uniqueness (priority 13).
    for b in db.bids.values():
        if (
            b["pairing_id"] == pairing_id
            and b["crew_member_id"] == crew_member_id
            and b["state"] in {"SUBMITTED", "AWARDED"}
        ):
            raise duplicate_bid("Crew member already has a non-terminal Bid on this Pairing")

    record = {
        "pairing_id": pairing_id,
        "crew_member_id": crew_member_id,
        "requested_seat": requested_seat,
        "state": "SUBMITTED",
    }
    stamp_new(record)
    db.bids[record["id"]] = record
    return success(record, status=201)


@bp.route("/bids", methods=["GET"])
def list_bids():
    user_id, role = require_roles({ROLE_PLANNER, ROLE_CREW})
    limit, offset = parse_pagination()
    rows = list(db.bids.values())
    pairing_id = request.args.get("pairing_id")
    crew_member_id = request.args.get("crew_member_id")
    state = request.args.get("state")
    if pairing_id:
        rows = [r for r in rows if r["pairing_id"] == pairing_id]
    if crew_member_id:
        rows = [r for r in rows if r["crew_member_id"] == crew_member_id]
    if state:
        rows = [r for r in rows if r["state"] == state]
    # CrewMember sees only their own (RBAC shared-ops).
    if role == ROLE_CREW:
        rows = [r for r in rows if r["crew_member_id"] == user_id]
    rows = sort_by_created_at(rows)
    page, total = slice_page(rows, limit, offset)
    return paginated(page, limit, offset, total)


@bp.route("/bids/<bid_id>", methods=["GET"])
def get_bid(bid_id):
    user_id, role = require_roles({ROLE_PLANNER, ROLE_CREW})
    b = db.bids.get(bid_id)
    if b is None:
        raise not_found("Bid not found")
    return success(b, status=200)


@bp.route("/bids/<bid_id>/withdraw", methods=["POST"])
def withdraw_bid(bid_id):
    user_id, role = require_roles({ROLE_CREW})
    b = db.bids.get(bid_id)
    if b is None:
        raise not_found("Bid not found")
    if b["crew_member_id"] != user_id:
        raise forbidden("Bid not owned by acting crew member")
    if b["state"] != "SUBMITTED":
        raise invalid_state(f"Cannot withdraw Bid in state {b['state']!r}")
    # Pairing must not yet be BID_CLOSED (PRD §3.2: "withdraw their own SUBMITTED
    # Bid before BID_CLOSED"). If BID_CLOSED or later, reject as cross-entity-state.
    p = db.pairings.get(b["pairing_id"])
    if p is None or p["state"] not in {"BID_OPEN"}:
        raise invalid_state("Pairing no longer accepts bid withdrawals")
    b["state"] = "WITHDRAWN"
    touch(b)
    return success(b, status=200)
