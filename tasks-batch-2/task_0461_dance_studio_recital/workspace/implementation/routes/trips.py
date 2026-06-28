"""TravelTrip / TripParticipant routes (PRD 3.7)."""
import math

from flask import Blueprint, request

from db import common_fields, db, new_id, touch
from errors import err
from helpers import (lookup, optional_int, paginate, parse_date,
                     require_fields, require_int, require_str, sort_by_created)
from middleware import authenticate, get_json, require_owner
from response import success
from services.billing import add_fee_line, remove_fee_or_credit
from views import public, public_list

bp = Blueprint("trips", __name__)


def recompute_participant_count(trip):
    count = sum(
        1 for p in db.participants.values()
        if p["trip_id"] == trip["id"] and p["status"] == "GOING"
    )
    if trip["participant_count"] != count:
        trip["participant_count"] = count
        touch(trip)


@bp.route("/teams/<tid>/trips", methods=["POST"])
def propose_trip(tid):
    authenticate({"StudioAdmin"})
    team = lookup(db.teams, tid)
    body = get_json()
    require_fields(body, ["destination", "depart_date", "return_date",
                          "per_member_cost_cents", "chaperone_ratio"])
    destination = require_str(body, "destination")
    depart = parse_date(body, "depart_date")
    ret = parse_date(body, "return_date")
    if ret < depart:
        raise err("ERR_INVALID_REQUEST", "return_date must be >= depart_date.")
    cost = require_int(body, "per_member_cost_cents", lo=0)
    ratio = require_int(body, "chaperone_ratio", lo=1)
    chaperones = optional_int(body, "chaperone_count", default=0, lo=0)
    trip = {
        "id": new_id(),
        "team_id": team["id"],
        "destination": destination,
        "depart_date": body["depart_date"],
        "return_date": body["return_date"],
        "per_member_cost_cents": cost,
        "chaperone_ratio": ratio,
        "chaperone_count": chaperones,
        "participant_count": 0,
        "status": "PROPOSED",
        **common_fields(),
    }
    db.trips[trip["id"]] = trip
    return success(public(trip), status=201)


@bp.route("/teams/<tid>/trips", methods=["GET"])
def list_team_trips(tid):
    authenticate({"StudioAdmin", "Parent"})
    team = lookup(db.teams, tid)
    items = [t for t in db.trips.values() if t["team_id"] == team["id"]]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


@bp.route("/trips/<tid>", methods=["GET"])
def get_trip(tid):
    authenticate({"StudioAdmin", "Parent"})
    trip = lookup(db.trips, tid)
    return success(public(trip), status=200)


@bp.route("/trips/<tid>/participants", methods=["POST"])
def add_participant(tid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    trip = lookup(db.trips, tid)
    body = get_json()
    require_fields(body, ["membership_id"])
    membership = lookup(db.memberships, body["membership_id"])
    student = db.students.get(membership["student_id"])
    if student is None:
        raise err("ERR_NOT_FOUND", "Membership references a missing student.")
    family_id = student["family_id"]
    require_owner(role, user_id, family_id)

    # State: signups allowed only on PROPOSED trips.
    if trip["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Trip is not accepting signups.")
    # Membership must be ROSTERED on the trip's team.
    if membership["status"] != "ROSTERED" or membership["team_id"] != trip["team_id"]:
        raise err("ERR_INVALID_STATE", "Membership is not rostered on the trip's team.")
    # Delinquency gate.
    family = db.families.get(family_id)
    if family is not None and family["status"] == "DELINQUENT":
        raise err("ERR_FAMILY_DELINQUENT", "Delinquent family cannot sign up for trips.")

    participant = {
        "id": new_id(),
        "trip_id": trip["id"],
        "membership_id": membership["id"],
        "family_id": family_id,
        "status": "GOING",
        **common_fields(),
    }
    db.participants[participant["id"]] = participant
    trip["participant_count"] += 1
    touch(trip)
    return success(public(participant), status=201)


@bp.route("/trips/<tid>/participants", methods=["GET"])
def list_trip_participants(tid):
    authenticate({"StudioAdmin", "Parent"})
    trip = lookup(db.trips, tid)
    items = [p for p in db.participants.values() if p["trip_id"] == trip["id"]]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


@bp.route("/participants", methods=["GET"])
def list_participants():
    authenticate({"StudioAdmin", "Parent"})
    items = list(db.participants.values())
    for key in ("family_id", "membership_id", "trip_id"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p[key] == val]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


@bp.route("/participants/<pid>", methods=["GET"])
def get_participant(pid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    participant = lookup(db.participants, pid)
    require_owner(role, user_id, participant["family_id"])
    return success(public(participant), status=200)


@bp.route("/participants/<pid>/withdraw", methods=["POST"])
def withdraw_participant(pid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    participant = lookup(db.participants, pid)
    require_owner(role, user_id, participant["family_id"])
    if participant["status"] != "GOING":
        raise err("ERR_INVALID_STATE", "Participant is not GOING.")
    trip = db.trips.get(participant["trip_id"])
    participant["status"] = "WITHDRAWN"
    touch(participant)
    if trip is not None:
        trip["participant_count"] -= 1
        touch(trip)
        # Refund if trip already CONFIRMED.
        if trip["status"] == "CONFIRMED":
            remove_fee_or_credit(participant["family_id"], trip["per_member_cost_cents"])
    return success(public(participant), status=200)


@bp.route("/trips/<tid>/confirm", methods=["POST"])
def confirm_trip(tid):
    authenticate({"StudioAdmin"})
    trip = lookup(db.trips, tid)
    if trip["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Trip is not PROPOSED.")
    team = db.teams.get(trip["team_id"])
    if team is None or team["status"] != "LOCKED":
        raise err("ERR_INVALID_STATE", "Parent team is not LOCKED.")
    if trip["participant_count"] < 1:
        raise err("ERR_INVALID_STATE", "Trip has no participants.")
    required = math.ceil(trip["participant_count"] / trip["chaperone_ratio"])
    if required > trip["chaperone_count"]:
        raise err("ERR_INSUFFICIENT_CHAPERONES", "Not enough chaperones.")
    trip["status"] = "CONFIRMED"
    touch(trip)
    # Charge each GOING participant's family.
    going = [p for p in db.participants.values()
             if p["trip_id"] == trip["id"] and p["status"] == "GOING"]
    for p in sorted(going, key=lambda x: (x["created_at"], x["_seq"])):
        add_fee_line(p["family_id"], trip["per_member_cost_cents"])
    return success(public(trip), status=200)


@bp.route("/trips/<tid>/cancel", methods=["POST"])
def cancel_trip(tid):
    authenticate({"StudioAdmin"})
    trip = lookup(db.trips, tid)
    if trip["status"] not in {"PROPOSED", "CONFIRMED"}:
        raise err("ERR_INVALID_STATE", "Trip cannot be cancelled.")
    was_confirmed = trip["status"] == "CONFIRMED"
    going = [p for p in db.participants.values()
             if p["trip_id"] == trip["id"] and p["status"] == "GOING"]
    for p in sorted(going, key=lambda x: (x["created_at"], x["_seq"])):
        p["status"] = "WITHDRAWN"
        touch(p)
        if was_confirmed:
            remove_fee_or_credit(p["family_id"], trip["per_member_cost_cents"])
    trip["participant_count"] = 0
    trip["status"] = "CANCELLED"
    touch(trip)
    return success(public(trip), status=200)
