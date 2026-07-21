"""Registration endpoints (PRD 3.3)."""
from flask import Blueprint

import config
import db
import response
import validators as v
from auth import authorize
from db import store
from errors import raise_error
from services import calc, domain

bp = Blueprint("registrations", __name__)

PUBLIC = config.PUBLIC_READ_ROLES
REGISTRATION_STATUSES = ["RESERVED", "CONFIRMED", "CHECKED_IN", "CANCELLED", "NO_SHOW"]
BUFFER = db.minutes(config.REGISTRATION_BUFFER_MINUTES)


def _authorize_registration_action(user_id, role, registration):
    if role == config.ROLE_PARTICIPANT:
        if registration["participant_id"] != user_id:
            raise_error("ERR_UNAUTHORIZED")
    elif role == config.ROLE_CAMPAIGN_MANAGER:
        campaign = domain.campaign_of_registration(registration)
        if campaign is not None:
            domain.require_manager_owns_campaign(user_id, campaign)


def _reopen_event(event):
    """Re-derive registered_count and the OPEN/FULL flip after a status change."""
    domain.refresh_event(event)
    db.touch(event)


@bp.post("/api/registrations")
def create_registration():
    user_id, role = authorize([config.ROLE_PARTICIPANT, config.ROLE_CAMPAIGN_MANAGER])
    body = v.get_body()
    participant_id = v.req_str(body, "participant_id")
    event_id = v.req_str(body, "event_id")
    minimum_waived = v.opt_bool(body, "minimum_waived", default=False)
    # PRD 3.3: only a campaign manager may waive the fundraising minimum.
    if minimum_waived and role != config.ROLE_CAMPAIGN_MANAGER:
        raise_error("ERR_UNAUTHORIZED")

    participant = domain.get_participant(participant_id)
    event = domain.get_event(event_id)

    if role == config.ROLE_PARTICIPANT:
        domain.require_participant_is(user_id, participant)
    elif role == config.ROLE_CAMPAIGN_MANAGER:
        campaign = domain.campaign_of_participant(participant)
        if campaign is not None:
            domain.require_manager_owns_campaign(user_id, campaign)

    # PRD 2.7 step 7: the event must belong to the fundraiser's campaign.
    if event["campaign_id"] != participant["campaign_id"]:
        raise_error("ERR_EVENT_CAMPAIGN_MISMATCH")

    # PRD 2.8 step 9: buffered window conflict against the fundraiser's other events.
    new_start = db.dt_of(event["starts_at"]) - BUFFER
    new_end = db.dt_of(event["ends_at"]) + BUFFER
    for other in domain.participant_registrations(participant_id):
        if other["status"] not in domain.OPEN_REGISTRATION_STATUSES:
            continue
        if other["event_id"] == event_id:
            # Same-event repeats are governed by ERR_DUPLICATE_REGISTRATION below.
            continue
        other_event = store.events.get(other["event_id"])
        if other_event is None:
            continue
        other_start = db.dt_of(other_event["starts_at"]) - BUFFER
        other_end = db.dt_of(other_event["ends_at"]) + BUFFER
        # Closed endpoints: windows that merely touch are a conflict.
        if new_start <= other_end and other_start <= new_end:
            raise_error("ERR_REGISTRATION_TIME_CONFLICT")

    domain.refresh_event(event)
    if event["status"] == "CLOSED":
        raise_error("ERR_INVALID_STATE")

    campaign = domain.campaign_of_participant(participant)
    if campaign is None or campaign["status"] != "PUBLISHED":
        raise_error("ERR_CAMPAIGN_NOT_PUBLISHED")

    # PRD 2.8 step 11: at most one open registration per fundraiser per event.
    for other in domain.participant_registrations(participant_id):
        if (
            other["event_id"] == event_id
            and other["status"] in domain.OPEN_REGISTRATION_STATUSES
        ):
            raise_error("ERR_DUPLICATE_REGISTRATION")

    # PRD 2.8 step 12: capacity strictly below at the moment of persistence.
    if event["registered_count"] >= event["capacity"]:
        raise_error("ERR_EVENT_AT_CAPACITY")

    fee_charged_cents = calc.registration_fee_charged(
        event["registration_fee_cents"],
        db.now(),
        db.dt_of(event["early_bird_ends_at"]),
    )
    rec = db.new_record(
        participant_id=participant_id,
        event_id=event_id,
        minimum_waived=minimum_waived,
        fee_charged_cents=fee_charged_cents,
        status="RESERVED",
        confirmed_at=None,
    )
    store.registrations[rec["id"]] = rec
    _reopen_event(event)
    return response.object_response(domain.ser_registration(rec), 201)


@bp.get("/api/registrations/<registration_id>")
def read_registration(registration_id):
    authorize(PUBLIC)
    rec = domain.get_registration(registration_id)
    return response.object_response(domain.ser_registration(rec))


@bp.get("/api/registrations")
def list_registrations():
    authorize(PUBLIC)
    limit, offset = v.pagination()
    participant_id = v.q("participant_id")
    event_id = v.q("event_id")
    status = v.q_enum("status", REGISTRATION_STATUSES)
    rows = list(store.registrations.values())
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    if event_id is not None:
        rows = [r for r in rows if r["event_id"] == event_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paged(rows, domain.ser_registration, limit, offset)


@bp.post("/api/registrations/<registration_id>/confirm")
def confirm_registration(registration_id):
    user_id, role = authorize([config.ROLE_PARTICIPANT, config.ROLE_CAMPAIGN_MANAGER])
    rec = domain.get_registration(registration_id)
    _authorize_registration_action(user_id, role, rec)
    if rec["status"] != "RESERVED":
        raise_error("ERR_INVALID_STATE")
    event = store.events.get(rec["event_id"])
    domain.refresh_event(event)
    if event["status"] not in ("OPEN", "FULL"):
        raise_error("ERR_INVALID_STATE")
    participant = store.participants.get(rec["participant_id"])
    if participant["status"] != "ACTIVE":
        raise_error("ERR_PARTICIPANT_NOT_ACTIVE")
    # PRD 2.8 step 13: the fundraising gate.
    if not rec["minimum_waived"]:
        domain.refresh_participant(participant)
        campaign = domain.campaign_of_participant(participant)
        minimum = campaign["fundraising_minimum_cents"] if campaign else 0
        if participant["credited_cents"] < minimum:
            raise_error("ERR_FUNDRAISING_MINIMUM_NOT_MET")
    rec["status"] = "CONFIRMED"
    rec["confirmed_at"] = db.now_iso()
    db.touch(rec)
    return response.object_response(domain.ser_registration(rec))


@bp.post("/api/registrations/<registration_id>/cancel")
def cancel_registration(registration_id):
    user_id, role = authorize([config.ROLE_PARTICIPANT, config.ROLE_CAMPAIGN_MANAGER])
    rec = domain.get_registration(registration_id)
    _authorize_registration_action(user_id, role, rec)
    if rec["status"] not in ("RESERVED", "CONFIRMED"):
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    event = store.events.get(rec["event_id"])
    if event is not None:
        _reopen_event(event)
    return response.object_response(domain.ser_registration(rec))


@bp.post("/api/registrations/<registration_id>/check-in")
def check_in_registration(registration_id):
    user_id, role = authorize([config.ROLE_CAMPAIGN_MANAGER])
    rec = domain.get_registration(registration_id)
    _authorize_registration_action(user_id, role, rec)
    if rec["status"] != "CONFIRMED":
        raise_error("ERR_INVALID_STATE")
    participant = store.participants.get(rec["participant_id"])
    if participant["status"] != "ACTIVE":
        raise_error("ERR_PARTICIPANT_NOT_ACTIVE")
    event = store.events.get(rec["event_id"])
    if db.now() < db.dt_of(event["starts_at"]):
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "CHECKED_IN"
    db.touch(rec)
    domain.refresh_event(event)
    return response.object_response(domain.ser_registration(rec))


@bp.post("/api/registrations/<registration_id>/no-show")
def no_show_registration(registration_id):
    user_id, role = authorize([config.ROLE_CAMPAIGN_MANAGER])
    rec = domain.get_registration(registration_id)
    _authorize_registration_action(user_id, role, rec)
    if rec["status"] != "CONFIRMED":
        raise_error("ERR_INVALID_STATE")
    event = store.events.get(rec["event_id"])
    if db.now() < db.dt_of(event["ends_at"]):
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "NO_SHOW"
    db.touch(rec)
    _reopen_event(event)
    return response.object_response(domain.ser_registration(rec))
