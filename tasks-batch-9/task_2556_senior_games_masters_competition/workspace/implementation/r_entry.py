"""Qualifying results and sport entries: filing, review, revision, withdrawal."""
from flask import Blueprint

import calc
import domain
import store
import web
from core import Field, as_dt, authenticate, fail, parse_body
from web import PREFIX

bp = Blueprint("entry", __name__)

QUALIFYING_FIELDS = [
    Field("athlete_id", "id"),
    Field("sport_id", "id"),
    Field("event_code", "str"),
    Field("mark_value", "num", exclusive_min=0),
    Field("meet_date", "date"),
    Field("meet_level", "str", enum=("LOCAL", "STATE")),
    Field("sanctioned", "bool"),
]


@bp.post(PREFIX + "/qualifying-results")
def create_qualifying_result():
    authenticate("GamesAdmin", "RegistrationOfficer")
    body = parse_body(QUALIFYING_FIELDS)
    store.must_get("athlete", body["athlete_id"])
    store.must_get("sport", body["sport_id"])
    row = store.insert(
        "qualifying_result",
        {
            "athlete_id": body["athlete_id"],
            "sport_id": body["sport_id"],
            "event_code": body["event_code"],
            "mark_value": body["mark_value"],
            "meet_date": body["meet_date"],
            "meet_level": body["meet_level"],
            "sanctioned": body["sanctioned"],
        },
        versioned=False,
    )
    return web.obj(row, 201)


@bp.get(PREFIX + "/qualifying-results/<qualifying_result_id>")
def read_qualifying_result(qualifying_result_id):
    return web.single("qualifying_result", qualifying_result_id)


@bp.get(PREFIX + "/qualifying-results")
def list_qualifying_results():
    return web.collection("qualifying_result", ("athlete_id", "sport_id", "meet_level"))


ENTRY_FIELDS = [
    Field("athlete_id", "id"),
    Field("sport_event_id", "id"),
    Field("qualification_source", "str",
          enum=("STATE_QUALIFIER", "LOCAL_QUALIFIER", "AGE_EXEMPT", "ORGANIZER_INVITE")),
    Field("qualifying_result_id", "id", required=False, default=None, nullable=True),
]
CITING_SOURCES = ("STATE_QUALIFIER", "LOCAL_QUALIFIER")


def _citation_gate(athlete, event, source, cited):
    """Step 21: the cited mark must support the entry in every respect."""
    if source in CITING_SOURCES:
        if cited is None:
            fail("ERR_QUALIFYING_RESULT_INVALID")
    else:
        if cited is not None:
            fail("ERR_QUALIFYING_RESULT_INVALID")
        return
    if cited["athlete_id"] != athlete["id"]:
        fail("ERR_QUALIFYING_RESULT_INVALID")
    if cited["sport_id"] != event["sport_id"]:
        fail("ERR_QUALIFYING_RESULT_INVALID")
    if cited["event_code"] != event["event_code"]:
        fail("ERR_QUALIFYING_RESULT_INVALID")
    if not cited["sanctioned"]:
        fail("ERR_QUALIFYING_RESULT_INVALID")
    if source == "STATE_QUALIFIER" and cited["meet_level"] != "STATE":
        fail("ERR_QUALIFYING_RESULT_INVALID")


def _age_gate(athlete, event, source, basis):
    """Step 22: the band, the sport floor and the exemption floor."""
    if event["age_group_code"] != athlete["age_group_code"]:
        fail("ERR_AGE_GROUP_MISMATCH")
    sport = domain.sport_of_event(event)
    if sport is not None and sport["min_age"] > basis:
        fail("ERR_AGE_GROUP_MISMATCH")
    if source == "AGE_EXEMPT" and basis < calc.AGE_EXEMPT_FLOOR:
        fail("ERR_AGE_GROUP_MISMATCH")


@bp.post(PREFIX + "/sport-entries")
def create_sport_entry():
    user_id, role = authenticate("Athlete", "RegistrationOfficer")
    body = parse_body(ENTRY_FIELDS)
    athlete = store.must_get("athlete", body["athlete_id"])
    event = store.must_get("sport_event", body["sport_event_id"])
    cited = None
    if body["qualifying_result_id"] is not None:
        cited = store.must_get("qualifying_result", body["qualifying_result_id"])
    web.guard_owner(role, user_id, athlete["id"])
    edition = domain.edition_of_athlete(athlete)
    if edition is None or edition["status"] != "REGISTRATION_OPEN":
        fail("ERR_EDITION_STATE_INVALID")
    if athlete["medical_status"] == "SCREENED_HOLD":
        fail("ERR_ATHLETE_MEDICAL_HOLD")
    source = body["qualification_source"]
    _citation_gate(athlete, event, source, cited)
    _age_gate(athlete, event, source, domain.basis_age(athlete, edition))
    if store.CLOCK.now() >= as_dt(edition["registration_deadline_utc"]):
        fail("ERR_REGISTRATION_DEADLINE_PASSED")
    for other in domain.entries_of_athlete(athlete["id"], domain.LIVE_ENTRY_STATES):
        if other["sport_event_id"] == event["id"]:
            fail("ERR_DUPLICATE_ENTRY")
    row = store.insert(
        "sport_entry",
        {
            "athlete_id": athlete["id"],
            "sport_event_id": event["id"],
            "qualifying_result_id": body["qualifying_result_id"],
            "qualification_source": source,
            "qualification_priority": calc.QUALIFICATION_PRIORITY[source],
            "qualifying_mark": cited["mark_value"] if cited is not None else None,
            "revision_round": 0,
            "review_note": None,
            "status": "SUBMITTED",
        },
    )
    return web.obj(row, 201)


@bp.get(PREFIX + "/sport-entries/<sport_entry_id>")
def read_sport_entry(sport_entry_id):
    return web.single("sport_entry", sport_entry_id)


@bp.get(PREFIX + "/sport-entries")
def list_sport_entries():
    return web.collection(
        "sport_entry",
        ("athlete_id", "sport_event_id", "qualifying_result_id", "status"),
    )


REVIEW_DECISIONS = ("TAKE_UP", "ACCEPT", "WAITLIST", "REQUEST_REVISION", "REJECT")
REVIEW_ORIGIN = {
    "TAKE_UP": ("SUBMITTED",),
    "ACCEPT": ("UNDER_REVIEW",),
    "WAITLIST": ("UNDER_REVIEW",),
    "REQUEST_REVISION": ("UNDER_REVIEW",),
    "REJECT": ("UNDER_REVIEW",),
}


@bp.post(PREFIX + "/sport-entries/<sport_entry_id>/review")
def review_sport_entry(sport_entry_id):
    authenticate("RegistrationOfficer")
    body = parse_body(
        [
            Field("decision", "str", enum=REVIEW_DECISIONS),
            Field("review_note", "str", required=False, default=None, allow_empty=True),
        ]
    )
    entry = store.must_get("sport_entry", sport_entry_id)
    decision = body["decision"]
    web.guard_state(entry["status"], REVIEW_ORIGIN[decision])
    web.guard_terminal("sport_entry", entry)
    event = domain.event_of_entry(entry)
    athlete = store.get("athlete", entry["athlete_id"])
    if decision == "TAKE_UP":
        if event is None or event["status"] not in ("OPEN", "UNDERSUBSCRIBED"):
            fail("ERR_INVALID_STATE_TRANSITION", "The event is not taking up entries")
    if decision == "ACCEPT":
        if athlete is None or athlete["registration_status"] != "REGISTERED":
            fail("ERR_ATHLETE_NOT_REGISTERED")
    if athlete is not None and athlete["medical_status"] == "SCREENED_HOLD":
        fail("ERR_ATHLETE_MEDICAL_HOLD")
    if decision == "ACCEPT":
        if athlete["medical_status"] not in domain.CLEARED_MEDICAL_STATES:
            fail("ERR_ATHLETE_MEDICAL_HOLD")
        domain.acceptance_recovery_gate(entry, event)
    if decision == "REQUEST_REVISION":
        if entry["revision_round"] >= calc.MAX_REVISION_ROUNDS:
            fail("ERR_REVISION_LIMIT_REACHED")
    if decision == "ACCEPT":
        if event["available_slots"] <= 0:
            fail("ERR_EVENT_CAPACITY_FULL")
    if body["review_note"] is not None:
        entry["review_note"] = body["review_note"]
    if decision == "TAKE_UP":
        entry["status"] = "UNDER_REVIEW"
    elif decision == "ACCEPT":
        entry["status"] = "ACCEPTED"
    elif decision == "WAITLIST":
        entry["status"] = "WAITLISTED"
    elif decision == "REQUEST_REVISION":
        entry["status"] = "REVISION_REQUESTED"
    else:
        entry["status"] = "REJECTED"
    store.touch(entry)
    if decision == "ACCEPT":
        domain.event_consume_capacity(event)
    return web.obj(entry)


@bp.post(PREFIX + "/sport-entries/<sport_entry_id>/resubmit")
def resubmit_sport_entry(sport_entry_id):
    user_id, role = authenticate("Athlete")
    body = parse_body(
        [
            Field("qualification_source", "str",
                  enum=("STATE_QUALIFIER", "LOCAL_QUALIFIER", "AGE_EXEMPT",
                        "ORGANIZER_INVITE")),
            Field("qualifying_result_id", "id", required=False, default=None,
                  nullable=True),
        ]
    )
    entry = store.must_get("sport_entry", sport_entry_id)
    cited = None
    if body["qualifying_result_id"] is not None:
        cited = store.must_get("qualifying_result", body["qualifying_result_id"])
    web.guard_owner(role, user_id, entry["athlete_id"])
    web.guard_state(entry["status"], ("REVISION_REQUESTED",))
    web.guard_terminal("sport_entry", entry)
    athlete = store.get("athlete", entry["athlete_id"])
    event = domain.event_of_entry(entry)
    edition = domain.edition_of_athlete(athlete) if athlete else None
    source = body["qualification_source"]
    _citation_gate(athlete, event, source, cited)
    _age_gate(athlete, event, source, domain.basis_age(athlete, edition))
    if edition is not None and store.CLOCK.now() >= as_dt(
        edition["registration_deadline_utc"]
    ):
        fail("ERR_REGISTRATION_DEADLINE_PASSED")
    if entry["revision_round"] >= calc.MAX_REVISION_ROUNDS:
        fail("ERR_REVISION_LIMIT_REACHED")
    entry["qualifying_result_id"] = body["qualifying_result_id"]
    entry["qualification_source"] = source
    entry["qualification_priority"] = calc.QUALIFICATION_PRIORITY[source]
    entry["qualifying_mark"] = cited["mark_value"] if cited is not None else None
    entry["revision_round"] += 1
    entry["status"] = "SUBMITTED"
    store.touch(entry)
    return web.obj(entry)


@bp.post(PREFIX + "/sport-entries/<sport_entry_id>/withdraw")
def withdraw_sport_entry(sport_entry_id):
    user_id, role = authenticate("Athlete", "RegistrationOfficer")
    parse_body([Field("reason", "str", required=False, default=None, allow_empty=True)])
    entry = store.must_get("sport_entry", sport_entry_id)
    web.guard_owner(role, user_id, entry["athlete_id"])
    web.guard_state(entry["status"], domain.LIVE_ENTRY_STATES)
    web.guard_terminal("sport_entry", entry)
    if entry["status"] == "ACCEPTED":
        if domain.results_of_entry(entry["id"], domain.LIVE_RESULT_STATES):
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "A verified result already cites this entry",
            )
    domain.withdraw_entry(entry)
    return web.obj(entry)
