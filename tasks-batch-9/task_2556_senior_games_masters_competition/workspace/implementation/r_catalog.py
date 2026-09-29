"""Sports and sport events."""
from flask import Blueprint

import calc
import domain
import store
import web
from core import Field, authenticate, bad_request, fail, no_body, parse_body
from web import PREFIX

bp = Blueprint("catalog", __name__)

SPORT_FIELDS = [
    Field("sport_code", "str", regex=r"^[A-Z]{2,8}$"),
    Field("name", "str"),
    Field("contact_class", "str", enum=("LOW", "MEDIUM", "HIGH")),
    Field("mark_direction", "str", enum=("LOWER_IS_BETTER", "HIGHER_IS_BETTER")),
    Field("required_certification_level", "int", minimum=0, maximum=4),
    Field("min_age", "int", required=False, default=50, minimum=50),
    Field("equipment_profile", "obj", required=False, default=None),
    Field("format_modifications", "obj", required=False, default=None),
]


@bp.post(PREFIX + "/sports")
def create_sport():
    authenticate("GamesAdmin")
    body = parse_body(SPORT_FIELDS)
    for existing in store.rows("sport"):
        if existing["sport_code"] == body["sport_code"]:
            fail("ERR_SPORT_CODE_TAKEN")
    row = store.insert(
        "sport",
        {
            "sport_code": body["sport_code"],
            "name": body["name"],
            "contact_class": body["contact_class"],
            "mark_direction": body["mark_direction"],
            "required_certification_level": body["required_certification_level"],
            "min_age": body["min_age"],
            "equipment_profile": body["equipment_profile"] or {},
            "format_modifications": body["format_modifications"] or {},
        },
    )
    return web.obj(row, 201)


@bp.get(PREFIX + "/sports/<sport_id>")
def read_sport(sport_id):
    return web.single("sport", sport_id)


@bp.get(PREFIX + "/sports")
def list_sports():
    return web.collection("sport", ("contact_class",))


EVENT_FIELDS = [
    Field("sport_id", "id"),
    Field("games_edition_id", "id"),
    Field("event_code", "str"),
    Field("age_group_code", "str"),
    Field("gender_division", "str", enum=("MEN", "WOMEN", "MIXED")),
    Field("entry_fee_cents", "int", minimum=0),
    Field("capacity", "int", minimum=1),
    Field("min_entries_to_stage", "int", required=False, default=3, minimum=1),
    Field("national_qualifying_standard", "num", required=False, default=None,
          nullable=True, exclusive_min=0),
]


@bp.post(PREFIX + "/sport-events")
def create_sport_event():
    authenticate("GamesAdmin")
    body = parse_body(EVENT_FIELDS)
    if not calc.valid_age_group_code(body["age_group_code"]):
        bad_request("age_group_code must be a five-year band or the open band 100+")
    store.must_get("sport", body["sport_id"])
    store.must_get("games_edition", body["games_edition_id"])
    if body["capacity"] < body["min_entries_to_stage"]:
        bad_request("capacity must be at least min_entries_to_stage")
    row = store.insert(
        "sport_event",
        {
            "sport_id": body["sport_id"],
            "games_edition_id": body["games_edition_id"],
            "event_code": body["event_code"],
            "age_group_code": body["age_group_code"],
            "gender_division": body["gender_division"],
            "entry_fee_cents": body["entry_fee_cents"],
            "capacity": body["capacity"],
            "min_entries_to_stage": body["min_entries_to_stage"],
            "national_qualifying_standard": body["national_qualifying_standard"],
            "accepted_entry_count": 0,
            "available_slots": body["capacity"],
            "current_record_id": None,
            "status": "OPEN",
            "seeded_at_utc": None,
        },
    )
    return web.obj(row, 201)


@bp.get(PREFIX + "/sport-events/<sport_event_id>")
def read_sport_event(sport_event_id):
    return web.single("sport_event", sport_event_id)


@bp.get(PREFIX + "/sport-events")
def list_sport_events():
    return web.collection(
        "sport_event", ("sport_id", "games_edition_id", "current_record_id", "status")
    )


@bp.post(PREFIX + "/sport-events/<sport_event_id>/seed")
def seed_sport_event(sport_event_id):
    authenticate("RegistrationOfficer")
    no_body()
    event = store.must_get("sport_event", sport_event_id)
    web.guard_state(event["status"], ("OPEN",))
    accepted = domain.entries_of_event(event["id"], ("ACCEPTED",))
    if not accepted:
        fail("ERR_NO_ELIGIBLE_ENTRIES")
    if event["accepted_entry_count"] < event["min_entries_to_stage"]:
        fail("ERR_MIN_ENTRIES_NOT_MET")
    event["status"] = "SEEDED"
    event["seeded_at_utc"] = store.now_iso()
    store.touch(event)
    return web.obj(event)


@bp.post(PREFIX + "/sport-events/<sport_event_id>/cancel")
def cancel_sport_event(sport_event_id):
    authenticate("GamesAdmin")
    body = parse_body([Field("reason", "str", allow_empty=True)])
    event = store.must_get("sport_event", sport_event_id)
    web.guard_state(event["status"], ("UNDERSUBSCRIBED",))
    for entry in domain.entries_of_event(event["id"], domain.LIVE_ENTRY_STATES):
        entry["status"] = "WITHDRAWN"
        store.touch(entry)
    event["status"] = "CANCELLED"
    event["accepted_entry_count"] = 0
    event["available_slots"] = event["capacity"]
    store.touch(event)
    for slot in domain.slots_of_event(event["id"], ("SCHEDULED",)):
        domain.release_slot(slot)
    return web.obj(event)
