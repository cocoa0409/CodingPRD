"""Games edition, checkpoint runs, impact and the logical clock."""
from flask import Blueprint

import calc
import domain
import store
import web
from core import (
    ALL_ROLES,
    Field,
    as_date,
    as_dt,
    authenticate,
    bad_request,
    fail,
    no_body,
    parse_body,
    parse_datetime,
)
from web import PREFIX

bp = Blueprint("edition", __name__)

EDITION_STATUSES = (
    "DRAFT",
    "REGISTRATION_OPEN",
    "REGISTRATION_CLOSED",
    "IN_PROGRESS",
    "COMPLETED",
    "IMPACT_FINALIZED",
)

CREATE_FIELDS = [
    Field("name", "str"),
    Field("host_city", "str"),
    Field("host_state_code", "str", regex=r"^[A-Z]{2}$"),
    Field("competition_start_date", "date"),
    Field("competition_end_date", "date"),
    Field("age_reference_date", "date"),
    Field("registration_deadline_utc", "datetime"),
    Field("age_basis", "str", required=False, default="REFERENCE_DATE",
          enum=("REFERENCE_DATE", "FIRST_COMPETITION_DAY")),
    Field("municipal_support_cents", "int", required=False, default=0, minimum=0),
]


@bp.post(PREFIX + "/games-editions")
def create_edition():
    authenticate("GamesAdmin")
    body = parse_body(CREATE_FIELDS)
    start = as_date(body["competition_start_date"])
    end = as_date(body["competition_end_date"])
    reference = as_date(body["age_reference_date"])
    if end < start:
        bad_request("competition_end_date must be on or after competition_start_date")
    if reference < end:
        bad_request("age_reference_date must be on or after competition_end_date")
    row = store.insert(
        "games_edition",
        {
            "name": body["name"],
            "host_city": body["host_city"],
            "host_state_code": body["host_state_code"],
            "competition_start_date": body["competition_start_date"],
            "competition_end_date": body["competition_end_date"],
            "age_reference_date": body["age_reference_date"],
            "age_basis": body["age_basis"],
            "registration_deadline_utc": body["registration_deadline_utc"],
            "municipal_support_cents": body["municipal_support_cents"],
            "status": "DRAFT",
            "ops_epoch": 0,
            "sponsorship_recognized_cents": 0,
            "provisional_impact_cents": 0,
            "final_impact_cents": None,
        },
    )
    return web.obj(row, 201)


@bp.get(PREFIX + "/games-editions/<games_edition_id>")
def read_edition(games_edition_id):
    return web.single("games_edition", games_edition_id)


@bp.get(PREFIX + "/games-editions")
def list_editions():
    return web.collection("games_edition", ("status", "host_state_code"))


@bp.post(PREFIX + "/games-editions/<games_edition_id>/open-registration")
def open_registration(games_edition_id):
    authenticate("GamesAdmin")
    no_body()
    edition = store.must_get("games_edition", games_edition_id)
    web.guard_state(edition["status"], ("DRAFT",))
    open_events = [
        e
        for e in store.rows("sport_event")
        if e["games_edition_id"] == edition["id"] and e["status"] == "OPEN"
    ]
    if not open_events:
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "At least one OPEN sport event is required before registration may open",
        )
    if store.CLOCK.now() >= as_dt(edition["registration_deadline_utc"]):
        fail("ERR_REGISTRATION_DEADLINE_PASSED")
    edition["status"] = "REGISTRATION_OPEN"
    store.touch(edition)
    return web.obj(edition)


def _slots_of_edition(edition_id):
    out = []
    for slot in store.rows("session_slot"):
        event = store.get("sport_event", slot["sport_event_id"])
        venue = store.get("venue", slot["venue_id"])
        if (event is not None and event["games_edition_id"] == edition_id) or (
            venue is not None and venue["games_edition_id"] == edition_id
        ):
            out.append(slot)
    return out


def _expire_unpaid(edition):
    deadline = as_dt(edition["registration_deadline_utc"])
    if store.CLOCK.now() < deadline:
        return
    for athlete in domain.athletes_of_edition(edition["id"], ("PENDING_PAYMENT",)):
        athlete["registration_status"] = "EXPIRED"
        store.touch(athlete)
        for entry in domain.entries_of_athlete(athlete["id"], domain.LIVE_ENTRY_STATES):
            domain.withdraw_entry(entry)


def _complete_departed_stays(edition):
    block_ids = {b["id"] for b in domain.blocks_of_edition(edition["id"])}
    today = store.CLOCK.now().date()
    for stay in store.rows("village_stay"):
        if stay["accommodation_block_id"] not in block_ids:
            continue
        if stay["status"] != "CHECKED_IN":
            continue
        if today >= as_date(stay["check_out_date"]):
            stay["status"] = "COMPLETED"
            store.touch(stay)


def _advance_edition_status(edition):
    """At most one step per checkpoint run. DRAFT is never advanced here."""
    moment = store.CLOCK.now()
    today = moment.date()
    status = edition["status"]
    if status == "REGISTRATION_OPEN":
        if moment >= as_dt(edition["registration_deadline_utc"]):
            edition["status"] = "REGISTRATION_CLOSED"
    elif status == "REGISTRATION_CLOSED":
        if today >= as_date(edition["competition_start_date"]):
            edition["status"] = "IN_PROGRESS"
    elif status == "IN_PROGRESS":
        if today > as_date(edition["competition_end_date"]):
            edition["status"] = "COMPLETED"
            for slot in _slots_of_edition(edition["id"]):
                if slot["status"] == "IN_PROGRESS":
                    domain.complete_slot(slot)


@bp.post(PREFIX + "/games-editions/<games_edition_id>/ops-run")
def ops_run(games_edition_id):
    authenticate("GamesAdmin")
    no_body()
    edition = store.must_get("games_edition", games_edition_id)
    if edition["final_impact_cents"] is not None:
        fail("ERR_IMPACT_ALREADY_FINALIZED")
    edition["ops_epoch"] += 1
    _expire_unpaid(edition)
    domain.promote_waitlist(edition["id"])
    _complete_departed_stays(edition)
    _advance_edition_status(edition)
    heads = domain.registered_head_count(edition["id"])
    edition["provisional_impact_cents"] = calc.provisional_impact(heads)[1]
    store.touch(edition)
    return web.obj(edition)


@bp.post(PREFIX + "/games-editions/<games_edition_id>/finalize-impact")
def finalize_impact(games_edition_id):
    authenticate("SponsorLiaison")
    no_body()
    edition = store.must_get("games_edition", games_edition_id)
    if edition["status"] != "COMPLETED":
        fail("ERR_EDITION_STATE_INVALID")
    if edition["final_impact_cents"] is not None:
        fail("ERR_IMPACT_ALREADY_FINALIZED")
    heads = domain.checked_in_head_count(edition["id"])
    nights = domain.actual_room_nights(edition["id"])
    edition["final_impact_cents"] = calc.final_impact(heads, nights)[1]
    edition["status"] = "IMPACT_FINALIZED"
    store.touch(edition)
    return web.obj(edition)


@bp.get(PREFIX + "/games-editions/<games_edition_id>/economic-impact")
def economic_impact(games_edition_id):
    authenticate("GamesAdmin", "SponsorLiaison")
    edition = store.must_get("games_edition", games_edition_id)
    registered_heads = domain.registered_head_count(edition["id"])
    checked_in_heads = domain.checked_in_head_count(edition["id"])
    room_nights = domain.actual_room_nights(edition["id"])
    if edition["final_impact_cents"] is None:
        provisional = calc.provisional_impact(registered_heads)[1]
    else:
        provisional = edition["provisional_impact_cents"]
    return web.payload(
        {
            "provisional_impact_cents": provisional,
            "final_impact_cents": edition["final_impact_cents"],
            "sponsorship_recognized_cents": edition["sponsorship_recognized_cents"],
            "municipal_support_cents": edition["municipal_support_cents"],
            "registered_heads": registered_heads,
            "checked_in_heads": checked_in_heads,
            "actual_room_nights": room_nights,
        }
    )


@bp.post(PREFIX + "/_clock/set_current_utc")
def set_clock():
    authenticate("GamesAdmin")
    body = parse_body([Field("to_iso8601", "datetime")])
    moment = parse_datetime(body["to_iso8601"])
    store.CLOCK.set(moment)
    return web.payload({"current_utc": store.CLOCK.iso()})
