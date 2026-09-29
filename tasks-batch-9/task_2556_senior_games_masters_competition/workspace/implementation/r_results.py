"""Competition marks, protests and age-group records."""
from flask import Blueprint

import calc
import domain
import store
import web
from core import Field, authenticate, fail, no_body, parse_body
from web import PREFIX

bp = Blueprint("results", __name__)

RESULT_FIELDS = [
    Field("sport_entry_id", "id"),
    Field("session_slot_id", "id"),
    Field("submitted_by_personnel_id", "id"),
    Field("mark_value", "num", exclusive_min=0),
    Field("placement", "int", minimum=1),
]
LIVE_MARK_STATES = ("SUBMITTED", "VERIFIED", "RECORD_PENDING", "PUBLISHED")


@bp.post(PREFIX + "/competition-results")
def create_competition_result():
    user_id, _role = authenticate("SportOfficial")
    body = parse_body(RESULT_FIELDS)
    entry = store.must_get("sport_entry", body["sport_entry_id"])
    slot = store.must_get("session_slot", body["session_slot_id"])
    store.must_get("personnel", body["submitted_by_personnel_id"])
    if user_id != body["submitted_by_personnel_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if slot["status"] not in ("IN_PROGRESS", "COMPLETED"):
        fail("ERR_SLOT_NOT_COMPETED")
    if domain.results_of_entry(entry["id"], LIVE_MARK_STATES):
        fail("ERR_RESULT_ALREADY_RECORDED")
    row = store.insert(
        "competition_result",
        {
            "sport_entry_id": entry["id"],
            "session_slot_id": slot["id"],
            "submitted_by_personnel_id": body["submitted_by_personnel_id"],
            "mark_value": body["mark_value"],
            "placement": body["placement"],
            "verified_by_user_id": None,
            "national_qualifying": False,
            "protest_round": 0,
            "status": "SUBMITTED",
        },
    )
    return web.obj(row, 201)


@bp.get(PREFIX + "/competition-results/<competition_result_id>")
def read_competition_result(competition_result_id):
    return web.single("competition_result", competition_result_id)


@bp.get(PREFIX + "/competition-results")
def list_competition_results():
    return web.collection(
        "competition_result",
        ("sport_entry_id", "session_slot_id", "submitted_by_personnel_id", "status"),
    )


def _event_of_result(result):
    entry = store.get("sport_entry", result["sport_entry_id"])
    if entry is None:
        return None, None
    return entry, domain.event_of_entry(entry)


@bp.post(PREFIX + "/competition-results/<competition_result_id>/verify")
def verify_competition_result(competition_result_id):
    user_id, _role = authenticate("RegistrationOfficer")
    no_body()
    result = store.must_get("competition_result", competition_result_id)
    web.guard_state(result["status"], ("SUBMITTED",))
    web.guard_terminal("competition_result", result)
    slot = store.get("session_slot", result["session_slot_id"])
    if slot is None or slot["status"] != "COMPLETED":
        fail("ERR_SLOT_NOT_COMPETED")
    _entry, event = _event_of_result(result)
    sport = domain.sport_of_event(event) if event is not None else None
    direction = sport["mark_direction"] if sport is not None else "LOWER_IS_BETTER"
    standing = None
    if event is not None and event["current_record_id"] is not None:
        standing = store.get("age_group_record", event["current_record_id"])
    if standing is None:
        record_branch = True
    else:
        record_branch = calc.beats_record(
            result["mark_value"], standing["mark_value"], direction
        )
    standard = event["national_qualifying_standard"] if event is not None else None
    result["verified_by_user_id"] = user_id
    result["national_qualifying"] = calc.national_qualifying(
        result["mark_value"], standard, direction
    )
    result["status"] = "RECORD_PENDING" if record_branch else "VERIFIED"
    store.touch(result)
    return web.obj(result)


@bp.post(PREFIX + "/competition-results/<competition_result_id>/publish")
def publish_competition_result(competition_result_id):
    authenticate("RegistrationOfficer")
    no_body()
    result = store.must_get("competition_result", competition_result_id)
    web.guard_state(result["status"], ("VERIFIED", "RECORD_PENDING"))
    web.guard_terminal("competition_result", result)
    if result["status"] == "RECORD_PENDING":
        claims = domain.records_citing(
            result["id"], ("PENDING_RATIFICATION", "RATIFIED")
        )
        if not claims:
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "A record-pending mark needs a filed record claim",
            )
    result["status"] = "PUBLISHED"
    store.touch(result)
    return web.obj(result)


@bp.post(PREFIX + "/competition-results/<competition_result_id>/protest")
def protest_competition_result(competition_result_id):
    user_id, _role = authenticate("Athlete")
    parse_body([Field("grounds", "str")])
    result = store.must_get("competition_result", competition_result_id)
    entry = store.get("sport_entry", result["sport_entry_id"])
    if entry is None or user_id != entry["athlete_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    web.guard_state(result["status"], ("VERIFIED", "PUBLISHED"))
    web.guard_terminal("competition_result", result)
    if result["protest_round"] >= calc.MAX_PROTEST_ROUNDS:
        fail("ERR_PROTEST_LIMIT_REACHED")
    was_published = result["status"] == "PUBLISHED"
    result["status"] = "PROTESTED"
    store.touch(result)
    if was_published:
        for claim in domain.records_citing(result["id"], ("PENDING_RATIFICATION",)):
            claim["status"] = "REJECTED"
            store.touch(claim)
    return web.obj(result)


def _unwind_records(result):
    """A voided mark discredits every record built on it."""
    for claim in domain.records_citing(result["id"], ("PENDING_RATIFICATION", "RATIFIED")):
        was_ratified = claim["status"] == "RATIFIED"
        claim["status"] = "REJECTED"
        store.touch(claim)
        if not was_ratified:
            continue
        event = store.get("sport_event", claim["sport_event_id"])
        if event is not None:
            event["current_record_id"] = claim["superseded_record_id"]
            store.touch(event)
        prior_id = claim["superseded_record_id"]
        if prior_id is None:
            continue
        prior = store.get("age_group_record", prior_id)
        if prior is not None and prior["status"] == "SUPERSEDED":
            prior["status"] = "RATIFIED"
            store.touch(prior)


@bp.post(PREFIX + "/competition-results/<competition_result_id>/resolve-protest")
def resolve_protest(competition_result_id):
    authenticate("RegistrationOfficer")
    body = parse_body(
        [
            Field("decision", "str", enum=("REMEASURE", "VOID")),
            Field("mark_value", "num", required=False, default=None, exclusive_min=0),
            Field("placement", "int", required=False, default=None, minimum=1),
        ]
    )
    result = store.must_get("competition_result", competition_result_id)
    web.guard_state(result["status"], ("PROTESTED",))
    web.guard_terminal("competition_result", result)
    if body["decision"] == "REMEASURE":
        if body["mark_value"] is not None:
            result["mark_value"] = body["mark_value"]
        if body["placement"] is not None:
            result["placement"] = body["placement"]
        result["verified_by_user_id"] = None
        result["national_qualifying"] = False
        result["protest_round"] += 1
        result["status"] = "SUBMITTED"
        store.touch(result)
    else:
        result["status"] = "VOIDED"
        store.touch(result)
        _unwind_records(result)
    return web.obj(result)


RECORD_FIELDS = [
    Field("sport_event_id", "id"),
    Field("competition_result_id", "id"),
    Field("claimed_by_user_id", "str"),
    Field("expected_sport_event_version", "int"),
]
RECORD_ELIGIBLE_STATES = ("RECORD_PENDING", "PUBLISHED")


@bp.post(PREFIX + "/age-group-records")
def create_age_group_record():
    authenticate("RecordsRatifier")
    body = parse_body(RECORD_FIELDS)
    event = store.must_get("sport_event", body["sport_event_id"])
    result = store.must_get("competition_result", body["competition_result_id"])
    if body["expected_sport_event_version"] != event["version"]:
        fail("ERR_STALE_SPORT_EVENT_VERSION")
    if result["status"] not in RECORD_ELIGIBLE_STATES:
        fail("ERR_RESULT_NOT_RECORD_ELIGIBLE")
    entry = store.get("sport_entry", result["sport_entry_id"])
    row = store.insert(
        "age_group_record",
        {
            "sport_event_id": event["id"],
            "competition_result_id": result["id"],
            "holder_athlete_id": entry["athlete_id"] if entry is not None else None,
            "superseded_record_id": event["current_record_id"],
            "age_group_code": event["age_group_code"],
            "mark_value": result["mark_value"],
            "claimed_by_user_id": body["claimed_by_user_id"],
            "ratified_by_user_id": None,
            "status": "PENDING_RATIFICATION",
        },
    )
    store.touch(event)
    return web.obj(row, 201)


@bp.get(PREFIX + "/age-group-records/<age_group_record_id>")
def read_age_group_record(age_group_record_id):
    return web.single("age_group_record", age_group_record_id)


@bp.get(PREFIX + "/age-group-records")
def list_age_group_records():
    return web.collection(
        "age_group_record",
        (
            "sport_event_id",
            "competition_result_id",
            "holder_athlete_id",
            "superseded_record_id",
            "status",
        ),
    )


@bp.post(PREFIX + "/age-group-records/<age_group_record_id>/ratify")
def ratify_age_group_record(age_group_record_id):
    user_id, _role = authenticate("RecordsRatifier")
    body = parse_body([Field("decision", "str", enum=("RATIFY", "REJECT"))])
    claim = store.must_get("age_group_record", age_group_record_id)
    web.guard_state(claim["status"], ("PENDING_RATIFICATION",))
    web.guard_terminal("age_group_record", claim)
    result = store.get("competition_result", claim["competition_result_id"])
    if body["decision"] == "RATIFY":
        if result is None or result["status"] not in RECORD_ELIGIBLE_STATES:
            fail("ERR_RESULT_NOT_RECORD_ELIGIBLE")
        if user_id == claim["claimed_by_user_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES")
        if result["verified_by_user_id"] is not None and (
            user_id == result["verified_by_user_id"]
        ):
            fail("ERR_SEGREGATION_OF_DUTIES")
        claim["status"] = "RATIFIED"
        claim["ratified_by_user_id"] = user_id
        store.touch(claim)
        event = store.get("sport_event", claim["sport_event_id"])
        if event is not None:
            event["current_record_id"] = claim["id"]
            store.touch(event)
        prior_id = claim["superseded_record_id"]
        if prior_id is not None:
            prior = store.get("age_group_record", prior_id)
            if prior is not None and prior["status"] == "RATIFIED":
                prior["status"] = "SUPERSEDED"
                store.touch(prior)
    else:
        claim["status"] = "REJECTED"
        claim["ratified_by_user_id"] = user_id
        store.touch(claim)
    return web.obj(claim)
