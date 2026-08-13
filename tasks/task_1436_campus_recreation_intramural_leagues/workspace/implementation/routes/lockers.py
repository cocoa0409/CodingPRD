"""Lockers and rentals."""

from flask import Blueprint, g, request

import errors as E
from domain import locker_out, get_or_404, eligibility_gate, LOCKER_SIZES, LOCKER_FEE_CENTS
from store import DB
from util import (body_json, req_str, req_int, req_enum, envelope_object,
                  list_response, require_role, stamp_new, touch)

bp = Blueprint("lockers", __name__)

TERMS = {"FALL_2026", "SPRING_2027", "SUMMER_2027"}


@bp.route("/v1/lockers", methods=["POST"])
def create_locker():
    require_role("RecAdmin")
    body = body_json()
    number = req_int(body, "locker_number")
    size = req_enum(body, "size", LOCKER_SIZES)
    if number < 1:
        raise E.err_validation("locker_number must be >= 1")
    for lk in DB.lockers.values():
        if lk["locker_number"] == number:
            raise E.err_validation("locker_number must be unique")
    locker = stamp_new({
        "locker_number": number,
        "size": size,
        "status": "AVAILABLE",
        "rented_by_member_id": None,
        "rental_term": None,
        "rental_fee_cents": None,
    })
    DB.lockers[locker["id"]] = locker
    return envelope_object(locker_out(locker), 201)


@bp.route("/v1/lockers/<locker_id>", methods=["GET"])
def get_locker(locker_id):
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    locker = get_or_404(DB.lockers, locker_id)
    return envelope_object(locker_out(locker))


@bp.route("/v1/lockers", methods=["GET"])
def list_lockers():
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    renter = request.args.get("rented_by_member_id")
    status = request.args.get("status")
    size = request.args.get("size")
    records = [lk for lk in DB.lockers.values()
               if (renter is None or lk["rented_by_member_id"] == renter)
               and (status is None or lk["status"] == status)
               and (size is None or lk["size"] == size)]
    return list_response(records, locker_out)


@bp.route("/v1/lockers/<locker_id>/rent", methods=["POST"])
def rent_locker(locker_id):
    require_role("Member")
    locker = get_or_404(DB.lockers, locker_id)
    body = body_json()
    if body.get("member_id") is not None and body["member_id"] != g.user_id:
        raise E.err_forbidden("Members may only rent lockers for themselves")
    member_id = req_str(body, "member_id")
    if member_id != g.user_id:
        raise E.err_forbidden("Members may only rent lockers for themselves")
    member = get_or_404(DB.members, member_id)
    term = req_enum(body, "term", TERMS)
    # State gate: member must be ACTIVE; then waiver, then membership.
    eligibility_gate(member)  # locker rental is explicitly NOT fine-gated
    for lk in DB.lockers.values():
        if lk["status"] == "RENTED" and lk["rented_by_member_id"] == member_id:
            raise E.err_rental_exists()
    if locker["status"] != "AVAILABLE":
        raise E.err_locker_unavailable()
    locker["status"] = "RENTED"
    locker["rented_by_member_id"] = member_id
    locker["rental_term"] = term
    locker["rental_fee_cents"] = LOCKER_FEE_CENTS[member["affiliation"]]
    touch(locker)
    return envelope_object(locker_out(locker))


@bp.route("/v1/lockers/<locker_id>/release", methods=["POST"])
def release_locker(locker_id):
    require_role("Member", "FacilityManager")
    locker = get_or_404(DB.lockers, locker_id)
    if g.role == "Member" and locker["rented_by_member_id"] != g.user_id:
        raise E.err_forbidden("Only the current renter may release the locker")
    if locker["status"] != "RENTED":
        raise E.err_invalid_state("Only a RENTED locker can be released")
    locker["status"] = "AVAILABLE"
    locker["rented_by_member_id"] = None
    locker["rental_term"] = None
    locker["rental_fee_cents"] = None
    touch(locker)
    return envelope_object(locker_out(locker))
