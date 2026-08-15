from flask import Blueprint, request

import db
from db import new_entity, touch
from errors import (
    ApiError,
    ERR_BIB_NUMBER_TAKEN,
    ERR_CHIP_ALREADY_ASSIGNED,
    ERR_CHIP_NOT_AVAILABLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PAYMENT_REQUIRED,
    ERR_RACE_ALREADY_STARTED,
    ERR_RACE_REGISTRATION_CLOSED,
    ERR_WAVE_CAPACITY_FULL,
)
from middleware import endpoint, ALL_ROLES, STAFF_ROLES
from response import ok
from serializers import ser_award, ser_registration
from validators import (
    get_body,
    get_or_404,
    list_page,
    v_date,
    v_enum,
    v_str,
)

bp = Blueprint("registrations", __name__)

_POST_START_STATES = ("IN_PROGRESS", "PROVISIONAL_PUBLISHED", "FINALIZED", "AMENDMENT_OPEN")


def _compute_age(birth, race_dt):
    age = race_dt.year - birth.year
    if (race_dt.month, race_dt.day) < (birth.month, birth.day):
        age -= 1
    return age


def _age_group(age):
    if age < 20:
        return "1-19"
    if age >= 80:
        return "80+"
    lo = 5 * (age // 5)
    return "{}-{}".format(lo, lo + 4)


@bp.post("/race-timing/registrations")
@endpoint("RegistrationClerk")
def create_registration():
    body = get_body(
        ("race_id", "wave_id", "bib_number", "participant_name", "birth_date", "gender")
    )
    # body identifiers resolve left to right
    race = get_or_404(db.races, body.get("race_id"))
    wave = get_or_404(db.waves, body.get("wave_id"))
    # coherence: the wave must belong to the race
    if wave["race_id"] != race["id"]:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "wave_id does not belong to race_id"
        )
    bib_number = v_str(body, "bib_number")
    participant_name = v_str(body, "participant_name")
    birth_date = v_date(body, "birth_date")
    gender = v_enum(body, "gender", ("M", "F"))
    if birth_date >= race["race_date"].date():
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "birth_date must fall strictly before the race date",
        )
    # intake gate before uniqueness and capacity
    if race["status"] != "REGISTRATION_OPEN":
        raise ApiError(
            ERR_RACE_REGISTRATION_CLOSED,
            409,
            "Registration intake is closed for this race",
        )
    if any(
        r["race_id"] == race["id"] and r["bib_number"] == bib_number
        for r in db.registrations.values()
    ):
        raise ApiError(
            ERR_BIB_NUMBER_TAKEN, 409, "bib_number is already used in this race"
        )
    occupancy = sum(
        1
        for r in db.registrations.values()
        if r["wave_id"] == wave["id"] and r["lifecycle_status"] != "WITHDRAWN"
    )
    if occupancy >= wave["max_capacity"]:
        raise ApiError(ERR_WAVE_CAPACITY_FULL, 409, "The wave is at full capacity")

    age = _compute_age(birth_date, race["race_date"])
    reg = new_entity()
    reg.update(
        {
            "race_id": race["id"],
            "wave_id": wave["id"],
            "chip_id": None,
            "bib_number": bib_number,
            "participant_name": participant_name,
            "birth_date": birth_date.strftime("%Y-%m-%d"),
            "gender": gender,
            "lifecycle_status": "REGISTERED",
            "payment_status": "UNPAID",
            "age_on_race_day": age,
            "age_group": _age_group(age),
        }
    )
    db.registrations[reg["id"]] = reg
    return ok(ser_registration(reg), 201)


@bp.get("/race-timing/registrations/<reg_id>")
@endpoint(*STAFF_ROLES)
def get_registration(reg_id):
    return ok(ser_registration(get_or_404(db.registrations, reg_id)))


@bp.get("/race-timing/registrations")
@endpoint(*STAFF_ROLES)
def list_registrations():
    items = list(db.registrations.values())
    for param in ("race_id", "wave_id", "chip_id", "lifecycle_status", "bib_number"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    return list_page(items, ser_registration)


@bp.get("/race-timing/registrations/<reg_id>/awards")
@endpoint(*ALL_ROLES)
def list_registration_awards(reg_id):
    get_or_404(db.registrations, reg_id)
    items = [a for a in db.awards.values() if a["registration_id"] == reg_id]
    return list_page(items, ser_award)


@bp.post("/race-timing/registrations/<reg_id>/pay")
@endpoint("RegistrationClerk")
def pay(reg_id):
    reg = get_or_404(db.registrations, reg_id)
    if reg["lifecycle_status"] == "WITHDRAWN" or reg["payment_status"] != "UNPAID":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Registration cannot transition to PAID"
        )
    race = db.races.get(reg["race_id"])
    if race is None or race["status"] != "REGISTRATION_OPEN":
        raise ApiError(
            ERR_RACE_REGISTRATION_CLOSED,
            409,
            "Registration intake is closed for this race",
        )
    reg["payment_status"] = "PAID"
    touch(reg)
    return ok(ser_registration(reg))


@bp.post("/race-timing/registrations/<reg_id>/confirm")
@endpoint("RegistrationClerk")
def confirm(reg_id):
    reg = get_or_404(db.registrations, reg_id)
    if reg["lifecycle_status"] != "REGISTERED":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Registration is not in REGISTERED"
        )
    race = db.races.get(reg["race_id"])
    if race is None or race["status"] != "REGISTRATION_OPEN":
        raise ApiError(
            ERR_RACE_REGISTRATION_CLOSED,
            409,
            "Registration intake is closed for this race",
        )
    if reg["payment_status"] != "PAID":
        raise ApiError(
            ERR_PAYMENT_REQUIRED, 409, "Confirmation requires payment_status PAID"
        )
    reg["lifecycle_status"] = "CONFIRMED"
    touch(reg)
    return ok(ser_registration(reg))


@bp.post("/race-timing/registrations/<reg_id>/assign-chip")
@endpoint("RegistrationClerk")
def assign_chip(reg_id):
    reg = get_or_404(db.registrations, reg_id)
    body = get_body(("chip_id",))
    chip = get_or_404(db.chips, body.get("chip_id"))
    race = db.races.get(reg["race_id"])
    # state first: race in TIMING_LOCKED / IN_PROGRESS and lifecycle from which
    # check-in exists — CONFIRMED, or CHECKED_IN without a chip (re-check-in on
    # the RETURNED deassign path; a held chip then fails ERR_CHIP_ALREADY_ASSIGNED)
    if reg["lifecycle_status"] not in ("CONFIRMED", "CHECKED_IN") or race is None or race[
        "status"
    ] not in ("TIMING_LOCKED", "IN_PROGRESS"):
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Registration must be CONFIRMED and the race in TIMING_LOCKED or IN_PROGRESS",
        )
    if chip["status"] != "AVAILABLE":
        raise ApiError(ERR_CHIP_NOT_AVAILABLE, 409, "Chip is not AVAILABLE")
    if reg["chip_id"] is not None:
        raise ApiError(
            ERR_CHIP_ALREADY_ASSIGNED, 409, "Registration already holds a chip"
        )
    reg["lifecycle_status"] = "CHECKED_IN"
    reg["chip_id"] = chip["id"]
    touch(reg)
    chip["status"] = "ASSIGNED"
    chip["current_registration_id"] = reg["id"]
    touch(chip)
    return ok(ser_registration(reg))


@bp.post("/race-timing/registrations/<reg_id>/withdraw")
@endpoint("RegistrationClerk")
def withdraw(reg_id):
    reg = get_or_404(db.registrations, reg_id)
    if reg["lifecycle_status"] == "WITHDRAWN":
        raise ApiError(ERR_INVALID_STATE, 409, "Registration is already WITHDRAWN")
    race = db.races.get(reg["race_id"])
    if race is not None and race["status"] in _POST_START_STATES:
        raise ApiError(
            ERR_RACE_ALREADY_STARTED,
            409,
            "Withdrawal is blocked once the race is in progress",
        )
    if reg["lifecycle_status"] == "CHECKED_IN" and reg["chip_id"] is not None:
        chip = db.chips.get(reg["chip_id"])
        if chip is not None:
            chip["status"] = "AVAILABLE"
            chip["current_registration_id"] = None
            touch(chip)
        reg["chip_id"] = None
    if reg["payment_status"] == "PAID":
        reg["payment_status"] = "REFUNDED"
    reg["lifecycle_status"] = "WITHDRAWN"
    touch(reg)
    return ok(ser_registration(reg))
