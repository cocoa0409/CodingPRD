"""Lead capture, booth interactions and the two lead-scoring variants."""

from flask import Blueprint

import calc
import db
from auth import authorize, own_entity, own_event
from db import S
from errors import ApiError
from response import ok, ok_list
from validate import (
    body, get_booth, get_event, get_lead, get_registration, pagination,
    paginate, qs, req_bool, req_enum, req_str,
)
from routes.registrations import fk

bp = Blueprint("leads", __name__)

INTERACTION_TYPES = ("VISIT", "DOWNLOAD")


@bp.route("/api/booths/<booth_id>/leads", methods=["POST"])
def capture_lead(booth_id):
    authorize("Attendee")
    booth = get_booth(booth_id)
    b = body()

    registration = fk(b, "registration_id", get_registration)
    if registration is not None:
        own_entity(registration["id"])

    req_str(b, "registration_id")
    marketing_consent = req_bool(b, "marketing_consent")

    if booth.get("state") == "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "The booth no longer accepts lead capture.")

    # 12. safety rules outrank referential rules
    if marketing_consent is not True:
        raise ApiError("ERR_CONSENT_REQUIRED")

    # 13. referential consistency
    if registration.get("event_id") != booth.get("event_id"):
        raise ApiError("ERR_REGISTRATION_EVENT_MISMATCH")

    for existing in S.leads.values():
        if (
            existing.get("booth_id") == booth["id"]
            and existing.get("registration_id") == registration["id"]
        ):
            raise ApiError("ERR_DUPLICATE_LEAD")

    row = db.new_row({
        "booth_id": booth["id"],
        "registration_id": registration["id"],
        "event_id": booth.get("event_id"),
        "marketing_consent": marketing_consent,
        "booth_visits": 1,
        "doc_downloads": 0,
        "score": 0,
        "score_variant": "BOOTH_WEIGHTED",
        "is_hot": False,
    })
    calc.score_lead(row, "BOOTH_WEIGHTED")
    S.leads[row["id"]] = row

    booth["captured_lead_count"] = int(booth.get("captured_lead_count", 0)) + 1
    db.touch(booth)
    return ok(db.serialize(row), 201)


@bp.route("/api/leads", methods=["GET"])
def list_leads():
    authorize("Organizer", "PlatformAdmin", "SponsorUser", "FinanceAdmin")
    limit, offset = pagination()
    booth_id = qs("booth_id")
    registration_id = qs("registration_id")
    event_id = qs("event_id")
    rows = [
        r for r in S.leads.values()
        if (booth_id is None or r.get("booth_id") == booth_id)
        and (registration_id is None or r.get("registration_id") == registration_id)
        and (event_id is None or r.get("event_id") == event_id)
    ]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/leads/<lead_id>", methods=["GET"])
def read_lead(lead_id):
    authorize("Organizer", "PlatformAdmin", "SponsorUser", "FinanceAdmin")
    return ok(db.serialize(get_lead(lead_id)))


@bp.route("/api/leads/<lead_id>/interactions", methods=["POST"])
def log_interaction(lead_id):
    authorize("SponsorUser")
    lead = get_lead(lead_id)
    booth = S.booths.get(lead.get("booth_id"))
    if booth is not None:
        own_entity(booth.get("sponsor_id"))
    b = body()
    interaction_type = req_enum(b, "interaction_type", INTERACTION_TYPES)

    if interaction_type == "VISIT":
        lead["booth_visits"] = int(lead.get("booth_visits", 0)) + 1
    else:
        lead["doc_downloads"] = int(lead.get("doc_downloads", 0)) + 1

    calc.score_lead(lead, "BOOTH_WEIGHTED")
    db.touch(lead)
    return ok(db.serialize(lead))


@bp.route("/api/events/<event_id>/leads/rescore", methods=["POST"])
def rescore_event_leads(event_id):
    authorize("Organizer")
    event = get_event(event_id)
    own_event(event)

    rescored_count = 0
    hot_lead_count = 0
    for lead in db.sort_rows(list(S.leads.values())):
        if lead.get("event_id") != event["id"]:
            continue
        calc.score_lead(lead, "ENGAGEMENT_WEIGHTED")
        db.touch(lead)
        rescored_count += 1
        if lead.get("is_hot"):
            hot_lead_count += 1

    return ok({"rescored_count": rescored_count, "hot_lead_count": hot_lead_count})
