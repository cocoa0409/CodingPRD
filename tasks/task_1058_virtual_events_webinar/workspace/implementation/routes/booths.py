"""Virtual booths: a branching review workflow with a revision loop (PRD 3.8)."""

from flask import Blueprint

import db
from auth import authorize, own_entity, own_event
from db import S
from errors import ApiError
from response import ok, ok_list
from validate import (
    body, get_booth, get_sponsor, guard_state, pagination, paginate, qs,
    req_int, req_str,
)
from routes.registrations import fk

bp = Blueprint("booths", __name__)

BOOTH_TERMINAL = ("SUSPENDED",)


def _event_of(booth):
    return S.events.get(booth.get("event_id"))


@bp.route("/api/booths", methods=["POST"])
def create_booth():
    authorize("SponsorUser")
    b = body()

    sponsor = fk(b, "sponsor_id", get_sponsor)
    if sponsor is not None:
        own_entity(sponsor["id"])

    req_str(b, "sponsor_id")
    headline = req_str(b, "headline")
    lead_quota = req_int(b, "lead_quota", minimum=0)

    row = db.new_row({
        "sponsor_id": sponsor["id"],
        "event_id": sponsor.get("event_id"),
        "headline": headline,
        "lead_quota": lead_quota,
        "state": "DRAFT",
        "captured_lead_count": 0,
        "stream_minutes_total": 0,
        "revision_round": 0,
    })
    S.booths[row["id"]] = row
    return ok(db.serialize(row), 201)


@bp.route("/api/booths", methods=["GET"])
def list_booths():
    authorize("Organizer", "PlatformAdmin", "SponsorUser", "Attendee", "FinanceAdmin")
    limit, offset = pagination()
    sponsor_id = qs("sponsor_id")
    event_id = qs("event_id")
    state = qs("state")
    rows = [
        r for r in S.booths.values()
        if (sponsor_id is None or r.get("sponsor_id") == sponsor_id)
        and (event_id is None or r.get("event_id") == event_id)
        and (state is None or r.get("state") == state)
    ]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/booths/<booth_id>", methods=["GET"])
def read_booth(booth_id):
    authorize("Organizer", "PlatformAdmin", "SponsorUser", "Attendee", "FinanceAdmin")
    return ok(db.serialize(get_booth(booth_id)))


@bp.route("/api/booths/<booth_id>/submit", methods=["POST"])
def submit_booth(booth_id):
    authorize("SponsorUser")
    booth = get_booth(booth_id)
    own_entity(booth.get("sponsor_id"))
    guard_state(booth, ("DRAFT", "CHANGES_REQUESTED"), BOOTH_TERMINAL)
    booth["state"] = "SUBMITTED"
    booth["revision_round"] = int(booth.get("revision_round", 0)) + 1
    db.touch(booth)
    return ok(db.serialize(booth))


@bp.route("/api/booths/<booth_id>/approve", methods=["POST"])
def approve_booth(booth_id):
    authorize("Organizer")
    booth = get_booth(booth_id)
    event = _event_of(booth)
    if event is not None:
        own_event(event)
    guard_state(booth, ("SUBMITTED",), BOOTH_TERMINAL)

    sponsor = S.sponsors.get(booth.get("sponsor_id"))
    if sponsor is None or sponsor.get("contract_status") != "SIGNED":
        raise ApiError("ERR_CONTRACT_NOT_SIGNED")

    booth["state"] = "APPROVED"
    db.touch(booth)
    return ok(db.serialize(booth))


@bp.route("/api/booths/<booth_id>/request-changes", methods=["POST"])
def request_changes_booth(booth_id):
    authorize("Organizer")
    booth = get_booth(booth_id)
    event = _event_of(booth)
    if event is not None:
        own_event(event)
    b = body()
    req_str(b, "reason")
    guard_state(booth, ("SUBMITTED",), BOOTH_TERMINAL)
    booth["state"] = "CHANGES_REQUESTED"
    db.touch(booth)
    return ok(db.serialize(booth))


@bp.route("/api/booths/<booth_id>/suspend", methods=["POST"])
def suspend_booth(booth_id):
    authorize("Organizer")
    booth = get_booth(booth_id)
    event = _event_of(booth)
    if event is not None:
        own_event(event)
    b = body()
    req_str(b, "reason")
    guard_state(booth, ("APPROVED", "LIVE"), BOOTH_TERMINAL)
    booth["state"] = "SUSPENDED"
    db.touch(booth)
    return ok(db.serialize(booth))


@bp.route("/api/booths/<booth_id>/stream-usage", methods=["POST"])
def booth_stream_usage(booth_id):
    authorize("SponsorUser")
    booth = get_booth(booth_id)
    own_entity(booth.get("sponsor_id"))
    b = body()
    reported = req_int(b, "minutes", minimum=0)
    booth["stream_minutes_total"] = int(booth.get("stream_minutes_total", 0)) + reported
    db.touch(booth)
    return ok(db.serialize(booth))
