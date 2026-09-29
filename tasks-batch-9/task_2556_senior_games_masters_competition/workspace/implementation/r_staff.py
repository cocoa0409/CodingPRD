"""Officials, volunteers and the staffing of a competition block."""
from flask import Blueprint

import domain
import store
import web
from core import Field, as_dt, authenticate, bad_request, fail, no_body, parse_body
from web import PREFIX

bp = Blueprint("staff", __name__)

PERSONNEL_FIELDS = [
    Field("games_edition_id", "id"),
    Field("full_name", "str"),
    Field("personnel_type", "str", enum=("OFFICIAL", "VOLUNTEER")),
    Field("certification_level", "int", required=False, default=0, minimum=0, maximum=4),
    Field("certified_sport_codes", "arr_str", required=False, default=None),
]


@bp.post(PREFIX + "/personnel")
def create_personnel():
    authenticate("GamesAdmin")
    body = parse_body(PERSONNEL_FIELDS)
    store.must_get("games_edition", body["games_edition_id"])
    codes = body["certified_sport_codes"]
    row = store.insert(
        "personnel",
        {
            "games_edition_id": body["games_edition_id"],
            "full_name": body["full_name"],
            "personnel_type": body["personnel_type"],
            "certification_level": body["certification_level"],
            "certified_sport_codes": list(codes) if codes is not None else [],
            "assigned_minutes_total": 0,
            "no_show_count": 0,
        },
    )
    return web.obj(row, 201)


@bp.get(PREFIX + "/personnel/<personnel_id>")
def read_personnel(personnel_id):
    return web.single("personnel", personnel_id)


@bp.get(PREFIX + "/personnel")
def list_personnel():
    return web.collection("personnel", ("games_edition_id", "personnel_type"))


ASSIGNMENT_FIELDS = [
    Field("personnel_id", "id"),
    Field("session_slot_id", "id"),
    Field("role_at_event", "str",
          enum=("CHIEF_JUDGE", "JUDGE", "TIMER", "MARSHAL", "RUNNER")),
]


def _slot_duration_minutes(slot):
    start = as_dt(slot["start_utc"])
    end = as_dt(slot["end_utc"])
    return int((end - start).total_seconds() // 60)


@bp.post(PREFIX + "/personnel-assignments")
def create_personnel_assignment():
    authenticate("GamesAdmin")
    body = parse_body(ASSIGNMENT_FIELDS)
    person = store.must_get("personnel", body["personnel_id"])
    slot = store.must_get("session_slot", body["session_slot_id"])
    event = store.get("sport_event", slot["sport_event_id"])
    sport = domain.sport_of_event(event) if event is not None else None
    if person["personnel_type"] == "OFFICIAL" and sport is not None:
        if person["certification_level"] < sport["required_certification_level"]:
            fail("ERR_CERTIFICATION_INSUFFICIENT")
        if sport["sport_code"] not in person["certified_sport_codes"]:
            fail("ERR_CERTIFICATION_INSUFFICIENT")
    domain.personnel_conflict_gate(person, slot)
    duration_minutes = _slot_duration_minutes(slot)
    domain.personnel_daily_gate(person, slot, duration_minutes)
    for other in domain.assignments_of_person(
        person["id"], domain.LEDGER_ASSIGNMENT_STATES
    ):
        if other["session_slot_id"] == slot["id"]:
            fail("ERR_ASSIGNMENT_DUPLICATE")
    if event is not None and person["games_edition_id"] != event["games_edition_id"]:
        bad_request("The person and the slot belong to different editions")
    row = store.insert(
        "personnel_assignment",
        {
            "personnel_id": person["id"],
            "session_slot_id": slot["id"],
            "role_at_event": body["role_at_event"],
            "duration_minutes": duration_minutes,
            "status": "ASSIGNED",
        },
    )
    person["assigned_minutes_total"] += duration_minutes
    store.touch(person)
    return web.obj(row, 201)


@bp.get(PREFIX + "/personnel-assignments/<personnel_assignment_id>")
def read_personnel_assignment(personnel_assignment_id):
    return web.single("personnel_assignment", personnel_assignment_id)


@bp.get(PREFIX + "/personnel-assignments")
def list_personnel_assignments():
    return web.collection(
        "personnel_assignment", ("personnel_id", "session_slot_id", "status")
    )


@bp.post(PREFIX + "/personnel-assignments/<personnel_assignment_id>/confirm")
def confirm_personnel_assignment(personnel_assignment_id):
    user_id, _role = authenticate("SportOfficial")
    no_body()
    assignment = store.must_get("personnel_assignment", personnel_assignment_id)
    if user_id != assignment["personnel_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    web.guard_state(assignment["status"], ("ASSIGNED",))
    slot = store.get("session_slot", assignment["session_slot_id"])
    if slot is None or slot["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE_TRANSITION", "The slot no longer accepts confirmations")
    assignment["status"] = "CONFIRMED"
    store.touch(assignment)
    person = store.get("personnel", assignment["personnel_id"])
    if person is not None and person["personnel_type"] == "OFFICIAL":
        slot["confirmed_official_count"] += 1
        store.touch(slot)
    return web.obj(assignment)


@bp.post(PREFIX + "/personnel-assignments/<personnel_assignment_id>/release")
def release_personnel_assignment(personnel_assignment_id):
    authenticate("GamesAdmin")
    parse_body([Field("reason", "str", required=False, default=None, allow_empty=True)])
    assignment = store.must_get("personnel_assignment", personnel_assignment_id)
    web.guard_state(assignment["status"], domain.LIVE_ASSIGNMENT_STATES)
    slot = store.get("session_slot", assignment["session_slot_id"])
    if assignment["status"] == "CONFIRMED":
        if slot is not None and slot["status"] == "IN_PROGRESS":
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "A confirmed official cannot be released from a running block",
            )
    domain.release_assignment(assignment)
    return web.obj(assignment)
