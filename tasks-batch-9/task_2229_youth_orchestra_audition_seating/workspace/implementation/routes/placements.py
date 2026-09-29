"""Offers, the waitlist, acceptance seating and the chair vacate cascade."""

from flask import Blueprint, request

import calc
import services as svc
from auth import ALL_ROLES, endpoint, require_guardian_owns
from envelope import ok, ok_list
from errors import ApiError
from store import clock_now, db
from validate import Body, bad, pagination

bp = Blueprint("placements", __name__)

NON_TERMINAL = ("OFFERED", "WAITLISTED", "ACCEPTED")


@bp.route("/placements", methods=["POST"])
@endpoint("ArtisticDirector")
def create_placement():
    body = Body()
    audition_id = body.string("audition_id", required=True)
    ensemble_id = body.string("ensemble_id", required=True)
    offer_kind = body.enum("offer_kind", ("OFFER", "WAITLIST"), required=True)
    expected = body.integer("expected_ensemble_version", required=True)
    offer_expires_at = body.datetime("offer_expires_at", required=False)
    if offer_kind == "OFFER":
        if offer_expires_at is None:
            bad("offer_expires_at is required when offer_kind is OFFER.")
        if not offer_expires_at > clock_now():
            bad("offer_expires_at must be strictly later than the logical clock.")

    audition = svc.audition_or_404(audition_id)
    ensemble = svc.ensemble_or_404(ensemble_id)

    if expected != ensemble["version"]:
        raise ApiError("ERR_STALE_ENSEMBLE_VERSION",
                       "The ensemble has moved on since your last read.")

    season = svc.season_of_ensemble(ensemble)
    if season["status"] != "PLACEMENT" or ensemble["roster_state"] != "FORMING":
        raise ApiError("ERR_ENSEMBLE_NOT_ACCEPTING_PLACEMENTS",
                       "This ensemble is not accepting placements.")

    if (audition["status"] != "ADJUDICATED"
            or audition["tier_recommendation"] in (None, "NOT_PLACED")
            or audition["season_id"] != ensemble["season_id"]):
        raise ApiError("ERR_AUDITION_NOT_ADJUDICATED",
                       "The referenced audition cannot justify a placement.")

    member = db.members[audition["member_id"]]
    for other in db.placements.values():
        if other["status"] not in NON_TERMINAL:
            continue
        if other["ensemble_id"] != ensemble["id"]:
            continue
        if other["member_id"] == member["id"] or other["audition_id"] == audition["id"]:
            raise ApiError("ERR_DUPLICATE_PLACEMENT",
                           "An open placement already exists for this pairing.")

    if calc.TIER_ORDER[ensemble["tier"]] > calc.TIER_ORDER[audition["tier_recommendation"]]:
        raise ApiError("ERR_TIER_ABOVE_RECOMMENDATION",
                       "The ensemble's tier is above the audition's recommendation.")

    quota = svc.quota_for(ensemble["id"], member["primary_instrument"])
    if quota is None:
        raise ApiError("ERR_NO_SECTION_FOR_INSTRUMENT",
                       "This ensemble seats no %s." % member["primary_instrument"])

    if offer_kind == "OFFER":
        section_offers = len([p for p in db.placements.values()
                              if p["ensemble_id"] == ensemble["id"]
                              and p["status"] == "OFFERED"
                              and db.members[p["member_id"]]["primary_instrument"]
                              == member["primary_instrument"]])
        if svc.filled_count(quota) + section_offers >= quota["max_count"]:
            raise ApiError("ERR_SECTION_CAPACITY_EXCEEDED",
                           "The section has no room for another offer.")
        if (svc.seated_count(ensemble) + svc.offered_count(ensemble)
                >= ensemble["max_total_size"]):
            raise ApiError("ERR_SECTION_CAPACITY_EXCEEDED",
                           "The ensemble has no room for another offer.")

    row = svc.new_row()
    row.update({
        "audition_id": audition["id"],
        "member_id": member["id"],
        "ensemble_id": ensemble["id"],
        "offer_kind": offer_kind,
        "status": "OFFERED" if offer_kind == "OFFER" else "WAITLISTED",
        "waitlist_rank": None,
        "offer_expires_at": offer_expires_at if offer_kind == "OFFER" else None,
        "accepted_at": None,
        "instrument_loan_requested": False,
        "instrument_class_loaned": None,
    })

    if offer_kind == "WAITLIST":
        already = len([p for p in db.placements.values()
                       if p["ensemble_id"] == ensemble["id"]
                       and p["status"] == "WAITLISTED"
                       and db.members[p["member_id"]]["primary_instrument"]
                       == member["primary_instrument"]])
        row["waitlist_rank"] = already + 1

    db.placements[row["id"]] = row
    svc.touch(ensemble)
    if offer_kind == "OFFER":
        svc.ensure_tuition_account(member["id"], ensemble["season_id"],
                                   ensemble["tier"])
    return ok(svc.placement_json(row), 201)


@bp.route("/placements", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_placements():
    limit, offset = pagination()
    rows = svc.apply_filters(svc.ordered(list(db.placements.values())), request.args,
                             ["audition_id", "member_id", "ensemble_id", "status"])
    page = svc.paginate(rows, limit, offset)
    return ok_list([svc.placement_json(r) for r in page], limit, offset, len(rows))


@bp.route("/placements/<placement_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_placement(placement_id):
    return ok(svc.placement_json(svc.placement_or_404(placement_id)))


@bp.route("/placements/<placement_id>/accept", methods=["POST"])
@endpoint("Guardian")
def accept_placement(placement_id):
    placement = svc.placement_or_404(placement_id)
    require_guardian_owns(placement["member_id"])
    body = Body()
    loan_requested = body.boolean("instrument_loan_requested", default=False)

    if placement["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "Only an OFFERED placement may be accepted.")
    now = clock_now()
    if placement["offer_expires_at"] is not None and not now < placement["offer_expires_at"]:
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION", "This offer has lapsed.")

    member = db.members[placement["member_id"]]
    ensemble = db.ensembles[placement["ensemble_id"]]
    if member["standing_status"] == "FINANCIAL_HOLD":
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "A financial hold blocks the acceptance.")
    account = svc.account_for(member["id"], ensemble["season_id"])
    if account is not None and account["billing_status"] == "DELINQUENT":
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "A delinquent account blocks the acceptance.")

    quota = svc.quota_for(ensemble["id"], member["primary_instrument"])
    if quota is None:
        raise ApiError("ERR_NO_SECTION_FOR_INSTRUMENT",
                       "This ensemble seats no %s." % member["primary_instrument"])
    if svc.filled_count(quota) >= quota["max_count"]:
        raise ApiError("ERR_SECTION_FULL_AT_ACCEPTANCE",
                       "The section filled up while the offer sat open.")
    if svc.seated_count(ensemble) >= ensemble["max_total_size"]:
        raise ApiError("ERR_SECTION_FULL_AT_ACCEPTANCE",
                       "The ensemble filled up while the offer sat open.")

    audition = db.auditions.get(placement["audition_id"])
    placement["status"] = "ACCEPTED"
    placement["accepted_at"] = now
    placement["instrument_loan_requested"] = bool(loan_requested)
    placement["instrument_class_loaned"] = (member["instrument_class"]
                                           if loan_requested else None)
    placement["waitlist_rank"] = None
    svc.touch(placement)

    seat = svc.new_row()
    seat.update({
        "placement_id": placement["id"],
        "section_quota_id": quota["id"],
        "member_id": member["id"],
        "predecessor_assignment_id": None,
        "chair_number": 1,
        "is_principal": False,
        "ranking_score": audition["composite_final_score"] if audition else None,
        "rotation_cycle_index": quota["rotation_cycle_index"],
        "status": "ACTIVE",
    })
    db.seat_assignments[seat["id"]] = seat

    svc.rank_chairs(quota)
    svc.touch(quota)
    svc.recompute_quota_balance(quota)
    svc.touch(ensemble)
    svc.recompute_ensemble_roster(ensemble)

    if member["enrollment_status"] == "PROSPECT":
        member["enrollment_status"] = "ENROLLED"
        svc.touch(member)

    account = svc.ensure_tuition_account(member["id"], ensemble["season_id"],
                                        ensemble["tier"])
    svc.preliminary_assessment(account, placement)

    for other in svc.ordered(list(db.placements.values())):
        if other["id"] == placement["id"] or other["member_id"] != member["id"]:
            continue
        if other["status"] not in ("OFFERED", "WAITLISTED"):
            continue
        other_ensemble = db.ensembles[other["ensemble_id"]]
        if other_ensemble["season_id"] != ensemble["season_id"]:
            continue
        was_waitlisted = other["status"] == "WAITLISTED"
        other["status"] = "WITHDRAWN"
        other["waitlist_rank"] = None
        svc.touch(other)
        svc.touch(other_ensemble)
        if was_waitlisted:
            svc.rerank_waitlist(other_ensemble, member["primary_instrument"])

    return ok(svc.placement_json(placement))


@bp.route("/placements/<placement_id>/decline", methods=["POST"])
@endpoint("Guardian")
def decline_placement(placement_id):
    placement = svc.placement_or_404(placement_id)
    require_guardian_owns(placement["member_id"])
    Body()

    if placement["status"] not in ("OFFERED", "WAITLISTED"):
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "Only an open placement may be declined.")

    ensemble = db.ensembles[placement["ensemble_id"]]
    member = db.members[placement["member_id"]]
    if placement["status"] == "OFFERED":
        placement["status"] = "DECLINED"
        svc.touch(placement)
        svc.touch(ensemble)
        svc.waitlist_promotion(ensemble, member["primary_instrument"])
    else:
        placement["status"] = "WITHDRAWN"
        placement["waitlist_rank"] = None
        svc.touch(placement)
        svc.touch(ensemble)
        svc.rerank_waitlist(ensemble, member["primary_instrument"])
    return ok(svc.placement_json(placement))


# ------------------------------------------------------------- seat assignments
@bp.route("/seat-assignments", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_seats():
    limit, offset = pagination()
    rows = svc.apply_filters(svc.ordered(list(db.seat_assignments.values())),
                             request.args,
                             ["section_quota_id", "placement_id", "member_id",
                              "predecessor_assignment_id", "status"])
    page = svc.paginate(rows, limit, offset)
    return ok_list([svc.seat_json(r) for r in page], limit, offset, len(rows))


@bp.route("/seat-assignments/<seat_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_seat(seat_id):
    return ok(svc.seat_json(svc.seat_or_404(seat_id)))


@bp.route("/seat-assignments/<seat_id>/vacate", methods=["POST"])
@endpoint("ArtisticDirector")
def vacate_seat(seat_id):
    seat = svc.seat_or_404(seat_id)
    placement = db.placements.get(seat["placement_id"])
    if seat["status"] != "ACTIVE" or placement is None or placement["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "Only an ACTIVE chair on an ACCEPTED placement may be vacated.")
    svc.vacate_seat(seat)
    return ok(svc.seat_json(seat))
