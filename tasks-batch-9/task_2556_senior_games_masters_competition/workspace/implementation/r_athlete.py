"""Athletes: registration, fee settlement, arrival, withdrawal, medical appeal."""
from flask import Blueprint

import calc
import domain
import store
import web
from core import Field, as_date, as_dt, authenticate, fail, no_body, parse_body
from web import PREFIX

bp = Blueprint("athlete", __name__)

ATHLETE_FIELDS = [
    Field("games_edition_id", "id"),
    Field("full_name", "str"),
    Field("email", "str"),
    Field("date_of_birth", "date"),
    Field("residency_state_code", "str", regex=r"^[A-Z]{2}$"),
]


def _fee_settlement(athlete):
    """The six pinned steps, recomputed from scratch at payment time."""
    entries = domain.entries_of_athlete(athlete["id"], domain.FEE_ENTRY_STATES)
    event_fees_cents = 0
    for entry in entries:
        event = domain.event_of_entry(entry)
        if event is not None:
            event_fees_cents += event["entry_fee_cents"]
    return calc.settle_fee(len(entries), event_fees_cents)


@bp.post(PREFIX + "/athletes")
def create_athlete():
    authenticate("GamesAdmin", "RegistrationOfficer")
    body = parse_body(ATHLETE_FIELDS)
    edition = store.must_get("games_edition", body["games_edition_id"])
    if edition["status"] != "REGISTRATION_OPEN":
        fail("ERR_EDITION_STATE_INVALID")
    if store.CLOCK.now() >= as_dt(edition["registration_deadline_utc"]):
        fail("ERR_REGISTRATION_DEADLINE_PASSED")
    for other in domain.athletes_of_edition(edition["id"]):
        if other["email"] == body["email"]:
            fail("ERR_ATHLETE_EMAIL_TAKEN")
    born = as_date(body["date_of_birth"])
    age_at_reference = calc.whole_years(born, as_date(edition["age_reference_date"]))
    age_at_first_day = calc.whole_years(born, as_date(edition["competition_start_date"]))
    basis = (
        age_at_first_day
        if edition["age_basis"] == "FIRST_COMPETITION_DAY"
        else age_at_reference
    )
    age_group_code = calc.age_band_code(basis)
    if age_group_code is None:
        fail("ERR_ATHLETE_UNDER_MINIMUM_AGE")
    row = store.insert(
        "athlete",
        {
            "games_edition_id": edition["id"],
            "full_name": body["full_name"],
            "email": body["email"],
            "date_of_birth": body["date_of_birth"],
            "residency_state_code": body["residency_state_code"],
            "age_at_reference": age_at_reference,
            "age_at_first_day": age_at_first_day,
            "age_group_code": age_group_code,
            "registration_status": "PENDING_PAYMENT",
            "medical_status": "NOT_SCREENED",
            "fee_total_cents": 0,
            "fee_paid_cents": 0,
            "fee_breakdown": {},
        },
    )
    return web.obj(row, 201)


@bp.get(PREFIX + "/athletes/<athlete_id>")
def read_athlete(athlete_id):
    return web.single("athlete", athlete_id)


@bp.get(PREFIX + "/athletes")
def list_athletes():
    return web.collection(
        "athlete",
        ("games_edition_id", "registration_status", "medical_status", "age_group_code"),
    )


@bp.post(PREFIX + "/athletes/<athlete_id>/pay-fees")
def pay_fees(athlete_id):
    user_id, role = authenticate("Athlete", "GamesAdmin")
    body = parse_body([Field("amount_cents", "int")])
    athlete = store.must_get("athlete", athlete_id)
    web.guard_owner(role, user_id, athlete["id"])
    edition = domain.edition_of_athlete(athlete)
    if edition is None or edition["status"] != "REGISTRATION_OPEN":
        fail("ERR_EDITION_STATE_INVALID")
    web.guard_state(athlete["registration_status"], ("PENDING_PAYMENT",))
    web.guard_athlete_terminal(athlete)
    fee_total_cents, breakdown = _fee_settlement(athlete)
    if body["amount_cents"] != fee_total_cents:
        fail("ERR_FEE_AMOUNT_MISMATCH")
    athlete["fee_total_cents"] = fee_total_cents
    athlete["fee_breakdown"] = breakdown
    athlete["fee_paid_cents"] = fee_total_cents
    athlete["registration_status"] = "REGISTERED"
    store.touch(athlete)
    return web.obj(athlete)


@bp.post(PREFIX + "/athletes/<athlete_id>/check-in")
def check_in_athlete(athlete_id):
    authenticate("GamesAdmin")
    no_body()
    athlete = store.must_get("athlete", athlete_id)
    edition = domain.edition_of_athlete(athlete)
    if edition is None or edition["status"] not in ("REGISTRATION_CLOSED", "IN_PROGRESS"):
        fail("ERR_EDITION_STATE_INVALID")
    web.guard_state(athlete["registration_status"], ("REGISTERED",))
    web.guard_athlete_terminal(athlete)
    if athlete["medical_status"] not in domain.CLEARED_MEDICAL_STATES:
        fail("ERR_ATHLETE_MEDICAL_HOLD")
    athlete["registration_status"] = "CHECKED_IN"
    store.touch(athlete)
    today = store.CLOCK.now().date()
    for stay in domain.stays_of_athlete(athlete["id"], ("RESERVED",)):
        arrival = as_date(stay["check_in_date"])
        if arrival is not None and arrival <= today:
            stay["status"] = "CHECKED_IN"
            store.touch(stay)
    return web.obj(athlete)


WITHDRAW_ENTRY_STATES = {
    "PENDING_PAYMENT": domain.NO_CAPACITY_ENTRY_STATES,
    "REGISTERED": domain.LIVE_ENTRY_STATES,
    "CHECKED_IN": domain.LIVE_ENTRY_STATES,
}
WITHDRAW_STAY_STATES = {
    "PENDING_PAYMENT": ("RESERVED",),
    "REGISTERED": ("RESERVED", "CHECKED_IN"),
    "CHECKED_IN": ("RESERVED", "CHECKED_IN"),
}


@bp.post(PREFIX + "/athletes/<athlete_id>/withdraw")
def withdraw_athlete(athlete_id):
    user_id, role = authenticate("Athlete", "GamesAdmin")
    parse_body([Field("reason", "str", required=False, default=None, allow_empty=True)])
    athlete = store.must_get("athlete", athlete_id)
    web.guard_owner(role, user_id, athlete["id"])
    origin = athlete["registration_status"]
    web.guard_state(origin, ("PENDING_PAYMENT", "REGISTERED", "CHECKED_IN"))
    web.guard_athlete_terminal(athlete)
    if origin == "CHECKED_IN":
        for entry in domain.entries_of_athlete(athlete["id"]):
            if domain.results_of_entry(entry["id"], domain.LIVE_RESULT_STATES):
                fail(
                    "ERR_INVALID_STATE_TRANSITION",
                    "A verified result already cites this athlete",
                )
    athlete["registration_status"] = "WITHDRAWN"
    store.touch(athlete)
    domain.withdraw_athlete_cascade(
        athlete, WITHDRAW_ENTRY_STATES[origin], WITHDRAW_STAY_STATES[origin]
    )
    return web.obj(athlete)


@bp.post(PREFIX + "/athletes/<athlete_id>/medical-appeal")
def medical_appeal(athlete_id):
    authenticate("MedicalDirector")
    body = parse_body(
        [
            Field("decision", "str", enum=("GRANT", "DENY")),
            Field("note", "str", required=False, default=None, allow_empty=True),
        ]
    )
    athlete = store.must_get("athlete", athlete_id)
    decision = body["decision"]
    origins = ("SCREENED_HOLD", "SCREENED_RESTRICTED") if decision == "GRANT" else ("SCREENED_HOLD",)
    web.guard_state(athlete["medical_status"], origins)
    web.guard_athlete_terminal(athlete)
    if decision == "GRANT":
        if athlete["medical_status"] == "SCREENED_HOLD":
            screenings = [
                s
                for s in store.rows("medical_screening")
                if s["athlete_id"] == athlete["id"]
            ]
            if not screenings:
                fail(
                    "ERR_INVALID_STATE_TRANSITION",
                    "No screening exists for this athlete",
                )
        athlete["medical_status"] = "CLEARED_BY_APPEAL"
        store.touch(athlete)
        for entry in domain.entries_of_athlete(athlete["id"], ("MEDICAL_HOLD",)):
            event = domain.event_of_entry(entry)
            if event is not None and event["available_slots"] > 0:
                entry["status"] = "ACCEPTED"
                store.touch(entry)
                domain.event_consume_capacity(event)
            else:
                entry["status"] = "WAITLISTED"
                store.touch(entry)
    else:
        store.touch(athlete)
    return web.obj(athlete)
