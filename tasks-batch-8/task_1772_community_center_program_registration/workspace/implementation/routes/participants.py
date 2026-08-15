"""Participant endpoints (PRD 3.4)."""
from flask import Blueprint, request

import store
from auth import authenticate, authorize
from errors import raise_err
from util import (
    body_json,
    get_or_404,
    list_response,
    new_record,
    req_datetime,
    req_str,
    serialize,
    success_object,
)

bp = Blueprint("participants", __name__)

FIELDS = ["id", "household_id", "full_name", "birth_date", "created_at", "updated_at", "version"]

ROLES = ["HouseholdManager", "FrontDeskStaff", "ProgramCoordinator"]


def participant_out(rec):
    return serialize(rec, FIELDS)


@bp.route("/participants", methods=["POST"])
def create_participant():
    uid, role = authenticate()
    authorize(role, ["HouseholdManager"])
    body = body_json()
    household_id = req_str(body, "household_id")
    full_name = req_str(body, "full_name")
    birth_date = req_datetime(body, "birth_date")
    get_or_404(store.households, household_id, "Household")
    if household_id != uid:
        raise_err("ERR_NOT_HOUSEHOLD_MEMBER", "Participants may only be added to the caller's household")
    rec = new_record()
    rec.update(household_id=household_id, full_name=full_name, birth_date=birth_date)
    store.participants[rec["id"]] = rec
    return success_object(participant_out(rec), 201)


@bp.route("/participants", methods=["GET"])
def list_participants():
    _, role = authenticate()
    authorize(role, ROLES)
    household_id = request.args.get("household_id")
    records = list(store.participants.values())
    if household_id is not None:
        records = [r for r in records if r["household_id"] == household_id]
    return list_response(records, participant_out)


@bp.route("/participants/<participant_id>", methods=["GET"])
def get_participant(participant_id):
    _, role = authenticate()
    authorize(role, ROLES)
    rec = get_or_404(store.participants, participant_id, "Participant")
    return success_object(participant_out(rec), 200)
