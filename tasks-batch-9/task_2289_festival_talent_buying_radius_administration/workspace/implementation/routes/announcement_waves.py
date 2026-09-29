"""Announcement waves: plan, assign, lock and publish."""

from datetime import datetime, time, timezone

from flask import Blueprint

from db import db, iso_instant, new_row, public, public_list, touch
from errors import fail
from middleware import endpoint
from response import paginate, respond_array, respond_object
from services import calc, derive
from validators import (
    body,
    body_fk,
    check_version,
    load,
    pagination,
    query_enum,
    query_string,
    req_enum,
    req_instant,
    req_int,
    req_string,
    stored_date,
    stored_instant,
)

bp = Blueprint("announcement_waves", __name__)

WAVE_STATUSES = ("PLANNED", "LOCKED", "PUBLISHED")
READ_ROLES = [
    "TalentBuyer",
    "ArtistRep",
    "BusinessAffairs",
    "ProductionManager",
    "FinanceController",
]


def _event_start_instant(festival):
    return datetime.combine(
        stored_date(festival["event_start_date"]), time(0, 0), tzinfo=timezone.utc
    )


def _check_reveal_before_event(festival, reveal):
    if reveal >= _event_start_instant(festival):
        fail(
            "ERR_REVEAL_AFTER_EVENT_START",
            "the reveal must precede midnight UTC of the first show date",
        )


@bp.post("/announcement-waves")
@endpoint(["TalentBuyer"])
def create_wave():
    payload = body()
    req_string(payload, "festival_id", 1)
    wave_number = req_int(payload, "wave_number", 1, 20)
    phase = req_enum(payload, "phase", calc.PHASE_LADDER)
    scheduled_reveal_utc = req_instant(payload, "scheduled_reveal_utc")

    festival = body_fk(payload, "festival_id", "festivals")

    for wave in db.announcement_waves.values():
        if wave["festival_id"] == festival["id"] and wave["wave_number"] == wave_number:
            fail("ERR_DUPLICATE_WAVE_NUMBER", "wave_number must be unique per edition")

    _check_reveal_before_event(festival, scheduled_reveal_utc)

    row = new_row(
        festival_id=festival["id"],
        wave_number=wave_number,
        phase=phase,
        scheduled_reveal_utc=iso_instant(scheduled_reveal_utc),
        status="PLANNED",
        assignment_count=0,
        headliner_count=0,
        published_at=None,
    )
    db.announcement_waves[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/announcement-waves/<wave_id>")
@endpoint(READ_ROLES)
def get_wave(wave_id):
    return respond_object(public(load("announcement_waves", wave_id)))


@bp.get("/announcement-waves")
@endpoint(READ_ROLES)
def list_waves():
    festival_id = query_string("festival_id")
    phase = query_enum("phase", calc.PHASE_LADDER)
    status = query_enum("status", WAVE_STATUSES)
    limit, offset = pagination()

    rows = list(db.announcement_waves.values())
    if festival_id is not None:
        rows = [r for r in rows if r["festival_id"] == festival_id]
    if phase is not None:
        rows = [r for r in rows if r["phase"] == phase]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = calc.sorted_rows(rows, [("wave_number", False)])
    window, meta = paginate(rows, limit, offset)
    return respond_array(public_list(window), pagination=meta)


@bp.post("/announcement-waves/<wave_id>/assignments")
@endpoint(["TalentBuyer"])
def assign_booking(wave_id):
    payload = body()
    req_string(payload, "booking_id", 1)
    req_int(payload, "expected_announcement_wave_version")

    wave = load("announcement_waves", wave_id)
    booking = body_fk(payload, "booking_id", "bookings")
    if booking["festival_id"] != wave["festival_id"]:
        fail("ERR_FESTIVAL_MISMATCH", "the booking belongs to another edition")
    check_version(
        payload,
        "expected_announcement_wave_version",
        wave,
        "ERR_STALE_WAVE_VERSION",
    )

    if wave["status"] != "PLANNED":
        fail("ERR_INVALID_WAVE_STATE", "only a planned wave accepts assignments")
    if booking["announcement_wave_id"] is not None:
        fail("ERR_BOOKING_ALREADY_ASSIGNED", "the booking already sits in a wave")

    booking["announcement_wave_id"] = wave["id"]
    derive.recompute_wave(wave)
    booking["reveal_order"] = wave["assignment_count"]
    touch(booking)
    touch(wave)
    return respond_object(public(wave))


@bp.post("/announcement-waves/<wave_id>/lock")
@endpoint(["TalentBuyer", "BusinessAffairs"])
def lock_wave(wave_id):
    wave = load("announcement_waves", wave_id)
    festival = db.festivals.get(wave["festival_id"])

    if wave["status"] != "PLANNED":
        fail("ERR_INVALID_WAVE_STATE", "only a planned wave may be locked")
    if festival is None or wave["phase"] != festival["announcement_phase"]:
        fail("ERR_WAVE_PHASE_MISMATCH", "the wave phase does not match the edition")

    members = [
        b
        for b in db.bookings.values()
        if b["announcement_wave_id"] == wave["id"]
        and b["contract_status"] != "CANCELLED"
    ]
    if any(
        b["contract_status"] not in ("COUNTERSIGNED", "CLOSED_OUT") for b in members
    ):
        fail(
            "ERR_WAVE_BOOKING_NOT_COUNTERSIGNED",
            "every assigned booking must be countersigned",
        )

    _check_reveal_before_event(festival, stored_instant(wave["scheduled_reveal_utc"]))

    if len(members) < 1:
        fail("ERR_EMPTY_WAVE", "an empty wave may not be locked")

    wave["status"] = "LOCKED"
    derive.recompute_wave(wave)
    touch(wave)
    return respond_object(public(wave))


@bp.post("/announcement-waves/<wave_id>/publish")
@endpoint(["TalentBuyer"])
def publish_wave(wave_id):
    wave = load("announcement_waves", wave_id)
    festival = db.festivals.get(wave["festival_id"])

    if wave["status"] != "LOCKED":
        fail("ERR_INVALID_WAVE_STATE", "only a locked wave may be published")
    if festival is None or wave["phase"] != festival["announcement_phase"]:
        fail("ERR_WAVE_PHASE_MISMATCH", "the wave phase does not match the edition")
    if db.clock < stored_instant(wave["scheduled_reveal_utc"]):
        fail("ERR_REVEAL_NOT_DUE", "the reveal instant has not arrived")

    wave["status"] = "PUBLISHED"
    wave["published_at"] = iso_instant(db.clock)
    touch(wave)
    return respond_object(public(wave))
