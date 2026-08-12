"""Participant endpoints: register, list, read, submit, vet, check-in, withdraw."""

from flask import Blueprint, request

import db
import serializers
from errors import fail
from middleware import (
    authenticate,
    get_event,
    get_participant,
    own_participant_scope,
)
from response import success
from services import cascades
from services.common import new_record, paginate, touch
from services.derived import sorted_all
from util import body, opt_int, opt_str, req_enum, req_int, req_str

bp = Blueprint("participants", __name__)

IMPRESSION_CLASSES = ("COMBATANT", "CIVILIAN", "ARTILLERY_CREW")
PARTICIPANT_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "CHANGES_REQUESTED",
    "VETTED",
    "CHECKED_IN",
    "REJECTED",
    "WITHDRAWN",
)
READ_ROLES = ["EventOrganizer", "AuthenticityOfficer", "SafetyOfficer", "UnitCommander", "Participant"]
INSPECTABLE_TYPES = ("FIREARM", "EDGED", "CANNON", "CAMP_FLAME")


@bp.post("/participants")
def create_participant():
    uid, role = authenticate(["UnitCommander", "Participant", "EventOrganizer"], creation=True)
    data = body(request)
    unit_id = data.get("unit_id")
    # Role-path ownership (priority 2): UC registers members of its own unit;
    # Participant self-registers as an independent; EO may register anyone.
    if role == "UnitCommander":
        if unit_id != uid:
            fail("ERR_FORBIDDEN", "unit commander registers members of its own unit only")
    elif role == "Participant":
        if unit_id is not None:
            fail("ERR_FORBIDDEN", "participant-role callers self-register as independents")
    # Existence (priority 3): event, unit, supervisor.
    ev = get_event(data["event_id"]) if data.get("event_id") else None
    if ev is None:
        fail("ERR_VALIDATION", "missing required field: event_id")
    unit = None
    if unit_id is not None:
        unit = db.units.get(unit_id)
        if unit is None:
            fail("ERR_UNIT_NOT_FOUND", f"unit {unit_id} not found")
    supervisor_id = data.get("supervisor_participant_id")
    if supervisor_id is not None and supervisor_id not in db.participants:
        fail("ERR_PARTICIPANT_NOT_FOUND", f"supervisor {supervisor_id} not found")
    # Posture (priority 5)
    if ev["event_posture"] not in ("REGISTRATION_OPEN", "PUBLISHED"):
        fail("ERR_INVALID_EVENT_POSTURE", "participant registration requires REGISTRATION_OPEN or PUBLISHED")
    # Body shape (priority 7)
    full_name = req_str(data, "full_name")
    age = req_int(data, "age_at_event", minimum=0)
    impression = req_enum(data, "impression_class", IMPRESSION_CLASSES)
    persona = opt_str(data, "persona_description", "")
    # Bootstrap: a Participant-role caller's X-User-ID becomes the record id.
    new_id = uid if (role == "Participant" and uid) else None
    rec_probe_id = new_id or "(generated)"
    if supervisor_id is not None and supervisor_id == rec_probe_id:
        fail("ERR_VALIDATION", "supervisor_participant_id must differ from the participant's own id")
    if unit is not None and unit["event_id"] != ev["id"]:
        fail("ERR_UNIT_NOT_IN_EVENT", "unit belongs to a different event")
    rec = new_record(record_id=new_id)
    rec.update(
        event_id=ev["id"],
        unit_id=unit_id,
        supervisor_participant_id=supervisor_id,
        full_name=full_name,
        age_at_event=age,
        impression_class=impression,
        persona_description=persona,
        status="DRAFT",
        vet_notes=None,
        checked_in_at=None,
    )
    db.participants[rec["id"]] = rec
    return success(serializers.participant(rec), 201)


def _scope_filtered_participants(uid, role):
    items = db.participants.values()
    if role == "UnitCommander":
        items = [p for p in items if p["unit_id"] == uid]
    elif role == "Participant":
        items = [p for p in items if p["id"] == uid]
    else:
        items = list(items)
    return items


@bp.get("/participants")
def list_participants():
    uid, role = authenticate(READ_ROLES)
    items = _scope_filtered_participants(uid, role)
    # A unit_id filter must resolve (ERR_UNIT_NOT_FOUND per validations table).
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        if unit_id not in db.units:
            fail("ERR_UNIT_NOT_FOUND", f"unit {unit_id} not found")
        items = [p for p in items if p["unit_id"] == unit_id]
    event_id = request.args.get("event_id")
    if event_id is not None:
        items = [p for p in items if p["event_id"] == event_id]
    supervisor_id = request.args.get("supervisor_participant_id")
    if supervisor_id is not None:
        items = [p for p in items if p["supervisor_participant_id"] == supervisor_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(sorted_all(items))
    return success([serializers.participant(p) for p in page], 200, pagination=meta)


@bp.get("/participants/<participant_id>")
def read_participant(participant_id):
    uid, role = authenticate(READ_ROLES)
    p = get_participant(participant_id)
    if role == "UnitCommander" and p["unit_id"] != uid:
        fail("ERR_FORBIDDEN", "unit commander may read only its own unit's participants")
    if role == "Participant":
        own_participant_scope(uid, p)
    return success(serializers.participant(p), 200)


@bp.post("/participants/<participant_id>/submit")
def submit_participant(participant_id):
    uid, role = authenticate(["UnitCommander", "Participant"])
    p = get_participant(participant_id)
    if role == "UnitCommander" and p["unit_id"] != uid:
        fail("ERR_FORBIDDEN", "unit commander may submit only its own unit's participants")
    if role == "Participant":
        own_participant_scope(uid, p)
    # Unit must be APPROVED when affiliated (PRD §3.3 order: unit, then from-state).
    if p["unit_id"] is not None:
        u = db.units.get(p["unit_id"])
        if u is None or u["status"] != "APPROVED":
            fail("ERR_INVALID_UNIT_STATUS", "the participant's unit must be APPROVED")
    if p["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        fail("ERR_INVALID_PARTICIPANT_STATUS", f"participant in {p['status']} cannot be submitted")
    p["status"] = "SUBMITTED"
    touch(p)
    return success(serializers.participant(p), 200)


@bp.post("/participants/<participant_id>/vet")
def vet_participant(participant_id):
    authenticate(["AuthenticityOfficer"])
    p = get_participant(participant_id)
    if p["status"] != "SUBMITTED":
        fail("ERR_INVALID_PARTICIPANT_STATUS", "only a SUBMITTED participant can be vetted")
    data = body(request)
    decision = req_enum(data, "decision", ("APPROVE", "REQUEST_CHANGES", "REJECT"))
    notes = opt_str(data, "notes")
    p["status"] = {
        "APPROVE": "VETTED",
        "REQUEST_CHANGES": "CHANGES_REQUESTED",
        "REJECT": "REJECTED",
    }[decision]
    p["vet_notes"] = notes
    touch(p)
    return success(serializers.participant(p), 200)


@bp.post("/participants/<participant_id>/check-in")
def check_in_participant(participant_id):
    authenticate(["EventOrganizer", "SafetyOfficer"])
    p = get_participant(participant_id)
    ev = get_event(p["event_id"])
    # PRD §3.3 gate order: posture -> unit -> participant status -> equipment
    # -> supervisor presence -> supervisor eligibility -> ratio.
    if ev["event_posture"] != "EVENT_OPEN":
        fail("ERR_INVALID_EVENT_POSTURE", "check-in requires EVENT_OPEN posture")
    if p["unit_id"] is not None:
        u = db.units.get(p["unit_id"])
        if u is None or u["status"] != "APPROVED":
            fail("ERR_INVALID_UNIT_STATUS", "the participant's unit must be APPROVED")
    if p["status"] != "VETTED":
        fail("ERR_INVALID_PARTICIPANT_STATUS", "only a VETTED participant can check in")
    for it in db.equipment.values():
        if (
            it["participant_id"] == p["id"]
            and it["item_type"] in INSPECTABLE_TYPES
            and it["status"] in ("DECLARED", "INSPECTION_DUE", "FAILED")
        ):
            fail("ERR_UNINSPECTED_EQUIPMENT", "an inspectable item has not passed inspection")
    if p["age_at_event"] < 18:
        if not p["supervisor_participant_id"]:
            fail("ERR_SUPERVISOR_REQUIRED", "a minor requires a supervisor_participant_id")
        sup = db.participants.get(p["supervisor_participant_id"])
        if (
            sup is None
            or sup["age_at_event"] < 18
            or sup["unit_id"] != p["unit_id"]
            or sup["status"] != "CHECKED_IN"
        ):
            fail("ERR_SUPERVISOR_INELIGIBLE", "supervisor must be a checked-in adult of the same unit")
        if p["unit_id"] is not None:
            adults = minors = 0
            for q in db.participants.values():
                if q["unit_id"] == p["unit_id"] and q["status"] == "CHECKED_IN":
                    if q["age_at_event"] >= 18:
                        adults += 1
                    else:
                        minors += 1
            if minors + 1 > ev["max_minor_per_adult"] * adults:
                fail("ERR_SUPERVISION_RATIO_EXCEEDED", "supervision ratio would be exceeded")
    p["status"] = "CHECKED_IN"
    p["checked_in_at"] = db.now()
    touch(p)
    return success(serializers.participant(p), 200)


@bp.post("/participants/<participant_id>/withdraw")
def withdraw_participant(participant_id):
    uid, role = authenticate(["Participant", "UnitCommander", "EventOrganizer"])
    p = get_participant(participant_id)
    if role == "UnitCommander" and p["unit_id"] != uid:
        fail("ERR_FORBIDDEN", "unit commander may withdraw only its own unit's participants")
    if role == "Participant":
        own_participant_scope(uid, p)
    if p["status"] in ("REJECTED", "WITHDRAWN"):
        fail("ERR_INVALID_PARTICIPANT_STATUS", "a terminal participant cannot be withdrawn")
    cascades.withdraw_participant(p)
    return success(serializers.participant(p), 200)
