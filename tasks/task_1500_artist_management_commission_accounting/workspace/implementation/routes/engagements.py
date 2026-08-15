"""Engagement endpoints (PRD 3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ARTIST_ARCHIVED,
    ERR_ENGAGEMENT_WINDOW_PAST,
    ERR_ENGAGEMENT_NOT_ENDED,
    ERR_ENGAGEMENT_HAS_INCOME,
    ERR_OPPORTUNITY_NOT_ACCEPTED,
)
from response import success_object
from routes.helpers import get_one, list_response, public, scoped_mutation_auth
from services.core import new_record, touch, confirm_cascade
from util import CLOCK, parse_datetime
from validate import (
    get_body, opt_int, opt_str, req_datetime, req_enum, req_int, req_str,
    require_path_resource, require_ref,
)

bp = Blueprint("engagements", __name__)

INCOME_TYPES = {"TOURING", "RECORDING", "PUBLISHING", "ENDORSEMENT"}


@bp.post("/engagements")
def create_engagement():
    body = get_body()
    artist_id = req_str(body, "artist_id")
    caller = scoped_mutation_auth(["Agent"], body_artist_id=artist_id)
    income_type = req_enum(body, "income_type", INCOME_TYPES)
    counterparty_name = req_str(body, "counterparty_name")
    start_dt = req_datetime(body, "start_datetime")
    end_dt = req_datetime(body, "end_datetime")
    if parse_datetime(end_dt) <= parse_datetime(start_dt):
        raise_error(ERR_INVALID_REQUEST, "end_datetime must be later than start_datetime")
    guarantee = req_int(body, "guarantee_cents", non_negative=True)
    buffer_hours = opt_int(body, "travel_buffer_hours", default=24, non_negative=True)
    opportunity_id = opt_str(body, "opportunity_id")

    artist = require_ref("artists", artist_id, "artist_id")
    if opportunity_id is not None:
        require_ref("opportunities", opportunity_id, "opportunity_id")
    if artist["status"] == "ARCHIVED":
        raise_error(ERR_ARTIST_ARCHIVED, "artist is ARCHIVED")

    rec = new_record("engagements", {
        "artist_id": artist_id,
        "opportunity_id": opportunity_id,
        "income_type": income_type,
        "counterparty_name": counterparty_name,
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "travel_buffer_hours": buffer_hours,
        "guarantee_cents": guarantee,
        "status": "HOLD",
        "confirmed_at": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/engagements/<rid>")
def get_engagement(rid):
    return get_one("engagements", rid)


@bp.get("/engagements")
def list_engagements():
    filters = {
        "artist_id": request.args.get("artist_id"),
        "opportunity_id": request.args.get("opportunity_id"),
        "status": request.args.get("status"),
    }
    return list_response("engagements", filters)


@bp.post("/engagements/<rid>/confirm")
def confirm_engagement(rid):
    caller = scoped_mutation_auth(["Agent"], "engagements", rid)
    eng = require_path_resource("engagements", rid)
    if eng["status"] != "HOLD":
        raise_error(ERR_INVALID_STATE, "confirm requires HOLD")
    if parse_datetime(eng["end_datetime"]) <= CLOCK.now():
        raise_error(ERR_ENGAGEMENT_WINDOW_PAST, "engagement window is already past")
    if eng.get("opportunity_id"):
        opp = db["opportunities"].get(eng["opportunity_id"])
        if opp is None or opp["status"] not in ("ACCEPTED", "CONVERTED"):
            raise_error(ERR_OPPORTUNITY_NOT_ACCEPTED,
                        "linked opportunity is not ACCEPTED or CONVERTED")
    # Overlap check first (conflict fails the confirm), then cascade releases
    confirm_cascade(eng["artist_id"], eng, exclude_id=eng["id"])
    eng["status"] = "CONFIRMED"
    eng["confirmed_at"] = CLOCK.now_iso()
    touch(eng)
    return success_object(public(eng))


@bp.post("/engagements/<rid>/complete")
def complete_engagement(rid):
    caller = scoped_mutation_auth(["Agent", "BusinessManager"], "engagements", rid)
    eng = require_path_resource("engagements", rid)
    if eng["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE, "complete requires CONFIRMED")
    if CLOCK.now() < parse_datetime(eng["end_datetime"]):
        raise_error(ERR_ENGAGEMENT_NOT_ENDED, "engagement has not ended yet")
    eng["status"] = "COMPLETED"
    touch(eng)
    return success_object(public(eng))


@bp.post("/engagements/<rid>/cancel")
def cancel_engagement(rid):
    caller = scoped_mutation_auth(["Agent"], "engagements", rid)
    eng = require_path_resource("engagements", rid)
    if eng["status"] not in ("HOLD", "CONFIRMED"):
        raise_error(ERR_INVALID_STATE, f"cannot cancel from {eng['status']}")
    for ev in db["income_events"].values():
        if ev.get("linked_engagement_id") == eng["id"] and ev["status"] in ("VERIFIED", "SETTLED", "POSTED"):
            raise_error(ERR_ENGAGEMENT_HAS_INCOME,
                        "a linked income event has reached VERIFIED/SETTLED/POSTED")
    eng["status"] = "CANCELLED"
    touch(eng)
    return success_object(public(eng))
