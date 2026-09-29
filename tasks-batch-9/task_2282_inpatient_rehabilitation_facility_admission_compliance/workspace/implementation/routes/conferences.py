"""The weekly interdisciplinary team conference (PRD §3.7)."""

from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from db import store
from errors import ApiError
from queryargs import enum_arg, matches, str_arg
from response import envelope, paged, pagination_params
from services import (DISCIPLINE_CREDENTIAL, active_plan, by_seq, conferences_of_week,
                      propagate_admission, require, stamp_new)
from util import Body, iso, serialize

bp = Blueprint("conferences", __name__)

CONFERENCE_STATUSES = ("RECORDED", "LATE_RECORDED")


@bp.post("/team-conferences")
def create_conference():
    authenticate(("NurseCaseManager",))
    body = Body(request.get_json(silent=True))

    admission_id = body.id_field("admission_id")
    therapy_week_id = body.id_field("therapy_week_id")
    led_by = body.id_field("led_by_clinician_id")
    participant_ids = body.id_list_field("participant_clinician_ids", min_len=1, max_len=12)
    held_at = body.dt_field("held_at")

    # ladder rank 10 — body identifier existence
    admission = require(store.admissions, admission_id)
    week = require(store.weeks, therapy_week_id)
    lead = require(store.clinicians, led_by)
    participants = [require(store.clinicians, pid) for pid in participant_ids]

    # ladder rank 12 — the week must belong to this admission
    if week["admission_id"] != admission_id:
        raise ApiError("ERR_WEEK_ADMISSION_MISMATCH")

    # ladder rank 13 — facility boundary for every referenced clinician
    facility_id = admission["facility_id"]
    if lead["facility_id"] != facility_id:
        raise ApiError("ERR_CROSS_FACILITY_MISMATCH")
    for participant in participants:
        if participant["facility_id"] != facility_id:
            raise ApiError("ERR_CROSS_FACILITY_MISMATCH")

    # ladder rank 17 — the stay must be active
    if admission["stay_status"] != "ADMITTED":
        raise ApiError("ERR_ADMISSION_NOT_ACTIVE")

    # ladder rank 29 — the chair must be an active rehabilitation physician
    if lead["credential"] != "REHAB_PHYSICIAN" or lead["status"] != "ACTIVE":
        raise ApiError("ERR_CONFERENCE_LEAD_NOT_PHYSICIAN")

    # ladder rank 30 — attendance must be clinically complete
    credentials = {p["credential"] for p in participants}
    if "NURSE" not in credentials:
        raise ApiError("ERR_CONFERENCE_PARTICIPANTS_INCOMPLETE")
    plan = active_plan(admission_id)
    if plan is not None:
        for discipline in plan["disciplines"]:
            if DISCIPLINE_CREDENTIAL[discipline] not in credentials:
                raise ApiError("ERR_CONFERENCE_PARTICIPANTS_INCOMPLETE")

    # ladder rank 37 — the conference must be held inside its own window
    held_date = held_at.date().isoformat()
    if not (week["week_start_date"] <= held_date <= week["week_end_date"]):
        raise ApiError("ERR_CONFERENCE_OUTSIDE_WEEK")

    # ladder rank 38 — at most one RECORDED conference per week
    for existing in conferences_of_week(therapy_week_id):
        if existing["status"] == "RECORDED":
            raise ApiError("ERR_CONFERENCE_ALREADY_RECORDED")

    # timeliness is decided by the recording instant, not by held_at (PRD §3.7)
    recorded_date = store.clock.date().isoformat()
    status = "RECORDED" if recorded_date <= week["week_end_date"] else "LATE_RECORDED"

    conference = stamp_new({
        "admission_id": admission_id,
        "therapy_week_id": therapy_week_id,
        "led_by_clinician_id": led_by,
        "participant_clinician_ids": list(participant_ids),
        "held_at": iso(held_at),
        "status": status,
    })
    store.conferences[conference["id"]] = conference

    propagate_admission(admission)
    return envelope(serialize(conference), 201)


@bp.get("/team-conferences/<conference_id>")
def get_conference(conference_id):
    authenticate(ALL_ROLES)
    conference = require(store.conferences, conference_id)
    return envelope(serialize(conference), 200)


@bp.get("/team-conferences")
def list_conferences():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    filters = {
        "admission_id": str_arg("admission_id"),
        "therapy_week_id": str_arg("therapy_week_id"),
        "led_by_clinician_id": str_arg("led_by_clinician_id"),
        "status": enum_arg("status", CONFERENCE_STATUSES),
    }
    items = [c for c in by_seq(list(store.conferences.values())) if matches(c, filters)]
    page, pagination = paged(items, limit, offset)
    return envelope([serialize(c) for c in page], 200, pagination)
