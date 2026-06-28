"""Employer + EmployerSeat endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
import errors
import response
import serialize
import validate
from middleware import authenticate, require_roles
from routes.helpers import get_or_404, require_employer_owns
from services import domain

bp = Blueprint("employers", __name__)


@bp.route("/employers", methods=["POST"])
def create_employer():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin"})
    data = validate.body()

    practice_id = validate.require(data, "practice_id", str)
    company_name = validate.require(data, "company_name", str)
    seat_limit = validate.require(data, "sponsored_seat_limit", int)
    sponsorship_pct = validate.optional(data, "sponsorship_pct", (int, float), 1.0)

    get_or_404("practice", practice_id)

    if seat_limit <= 0:
        raise errors.validation("sponsored_seat_limit must be > 0.")
    if not (0 < sponsorship_pct <= 1):
        raise errors.validation("sponsorship_pct must be in (0, 1].")

    e = dict(db.common_fields())
    e["id"] = db.new_id()
    e["_seq"] = db.next_seq()
    e["practice_id"] = practice_id
    e["company_name"] = company_name
    e["sponsored_seat_limit"] = seat_limit
    e["sponsorship_pct"] = sponsorship_pct
    e["occupied_seat_count"] = 0
    db.employers[e["id"]] = e
    return response.object_response(serialize.employer(e), 201)


@bp.route("/employers/<eid>", methods=["GET"])
def get_employer(eid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Employer"})
    e = get_or_404("employer", eid)
    require_employer_owns(caller, eid)
    return response.object_response(serialize.employer(e), 200)


@bp.route("/employers", methods=["GET"])
def list_employers():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Employer"})
    limit, offset = validate.pagination()
    practice_id = request.args.get("practice_id")

    rows = list(db.employers.values())
    if caller.role == "Employer":
        rows = [r for r in rows if r["id"] == caller.user_id]
    if practice_id is not None:
        rows = [r for r in rows if r["practice_id"] == practice_id]

    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.employer(r) for r in page], limit, offset, total, 200
    )


@bp.route("/employers/<eid>/seats", methods=["POST"])
def create_seat(eid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Employer"})
    get_or_404("employer", eid)
    require_employer_owns(caller, eid)

    e = dict(db.common_fields())
    e["id"] = db.new_id()
    e["_seq"] = db.next_seq()
    e["employer_id"] = eid
    e["member_id"] = None
    e["seat_status"] = "OPEN"
    db.employer_seats[e["id"]] = e
    return response.object_response(serialize.employer_seat(e), 201)


@bp.route("/employers/<eid>/seats", methods=["GET"])
def list_employer_seats(eid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Employer"})
    get_or_404("employer", eid)
    require_employer_owns(caller, eid)
    limit, offset = validate.pagination()
    seat_status = request.args.get("seat_status")

    rows = [s for s in db.employer_seats.values() if s["employer_id"] == eid]
    if seat_status is not None:
        rows = [r for r in rows if r["seat_status"] == seat_status]

    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.employer_seat(r) for r in page], limit, offset, total, 200
    )


@bp.route("/employer-seats/<sid>", methods=["GET"])
def get_seat(sid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Employer"})
    seat = get_or_404("employer_seat", sid)
    require_employer_owns(caller, seat["employer_id"])
    return response.object_response(serialize.employer_seat(seat), 200)


@bp.route("/employer-seats", methods=["GET"])
def list_seats():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Employer"})
    limit, offset = validate.pagination()
    employer_id = request.args.get("employer_id")
    member_id = request.args.get("member_id")
    seat_status = request.args.get("seat_status")

    rows = list(db.employer_seats.values())
    if caller.role == "Employer":
        rows = [r for r in rows if r["employer_id"] == caller.user_id]
    if employer_id is not None:
        rows = [r for r in rows if r["employer_id"] == employer_id]
    if member_id is not None:
        rows = [r for r in rows if r.get("member_id") == member_id]
    if seat_status is not None:
        rows = [r for r in rows if r["seat_status"] == seat_status]

    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.employer_seat(r) for r in page], limit, offset, total, 200
    )


@bp.route("/employers/<eid>/seats/<seat_id>/occupy", methods=["POST"])
def occupy_seat(eid, seat_id):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Employer"})
    # Existence validated left-to-right (PRD §2.5): employer then seat.
    employer = get_or_404("employer", eid)
    require_employer_owns(caller, eid)
    seat = get_or_404("employer_seat", seat_id)
    if seat["employer_id"] != eid:
        raise errors.not_found("Seat does not belong to this employer.")

    data = validate.body()
    member_id = validate.require(data, "member_id", str)
    expected_version = validate.require(data, "expected_employer_version", int)

    # member existence (body id) — priority 3.
    member = get_or_404("member", member_id)

    # State (priority 5): seat must be OPEN to be occupied.
    if seat["seat_status"] != "OPEN":
        raise errors.invalid_state("Seat is not OPEN.")

    # OCC (priority 6): expected version must match live employer version.
    if expected_version != employer["version"]:
        raise errors.stale_version("Employer version is stale.")

    # Business constraint (priority 12): OPEN seat present (this one) and room.
    if employer["occupied_seat_count"] >= employer["sponsored_seat_limit"]:
        raise errors.seat_limit_reached("Employer seat limit reached.")

    # Locate the member's membership (1:1).
    membership = _membership_for_member(member_id)
    if membership is None:
        raise errors.not_found("Membership for member does not exist.")

    seat["seat_status"] = "OCCUPIED"
    seat["member_id"] = member_id
    db.touch(seat)

    membership["employer_seat_id"] = seat["id"]
    domain.set_member_share(membership)
    db.touch(membership)

    domain.recompute_employer_seats(employer)  # increments occupied count + version
    return response.object_response(serialize.employer_seat(seat), 200)


def _membership_for_member(member_id):
    for ms in db.memberships.values():
        if ms["member_id"] == member_id:
            return ms
    return None
