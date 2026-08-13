"""Option endpoints (PRD 3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ARTIST_ARCHIVED,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_OPTION_WINDOW_VIOLATION,
    ERR_ENGAGEMENT_WINDOW_PAST,
)
from response import success_object
from routes.helpers import get_one, list_response, public, scoped_mutation_auth
from services.core import new_record, touch, confirm_cascade
from util import CLOCK, parse_datetime
from validate import (
    get_body, opt_str, req_datetime, req_enum, req_int, req_str,
    require_path_resource, require_ref,
)

bp = Blueprint("options", __name__)

OPTION_TYPES = {"RECORDING_CYCLE", "ENDORSEMENT_RENEWAL", "TOUR_LEG", "MERCHANDISE"}
INCOME_TYPES = {"TOURING", "RECORDING", "PUBLISHING", "ENDORSEMENT"}


@bp.post("/options")
def create_option():
    body = get_body()
    artist_id = req_str(body, "artist_id")
    caller = scoped_mutation_auth(["Agent", "FirmAdmin"], body_artist_id=artist_id)
    agreement_id = req_str(body, "agreement_id")
    option_type = req_enum(body, "option_type", OPTION_TYPES)
    income_type = req_enum(body, "income_type", INCOME_TYPES)
    ex_start = req_datetime(body, "exercise_window_start")
    ex_end = req_datetime(body, "exercise_window_end")
    if parse_datetime(ex_end) <= parse_datetime(ex_start):
        raise_error(ERR_INVALID_REQUEST, "exercise_window_end must be later than exercise_window_start")
    eng_start = req_datetime(body, "engagement_start_datetime")
    eng_end = req_datetime(body, "engagement_end_datetime")
    if parse_datetime(eng_end) <= parse_datetime(eng_start):
        raise_error(ERR_INVALID_REQUEST, "engagement_end_datetime must be later than engagement_start_datetime")
    exercise_value = req_int(body, "exercise_value_cents", positive=True)
    source_opportunity_id = opt_str(body, "source_opportunity_id")

    artist = require_ref("artists", artist_id, "artist_id")
    agreement = require_ref("agreements", agreement_id, "agreement_id")
    if source_opportunity_id is not None:
        require_ref("opportunities", source_opportunity_id, "source_opportunity_id")

    if artist["status"] == "ARCHIVED":
        raise_error(ERR_ARTIST_ARCHIVED, "artist is ARCHIVED")
    if agreement["status"] != "ACTIVE":
        raise_error(ERR_AGREEMENT_NOT_ACTIVE, "option must be created on an ACTIVE agreement")

    rec = new_record("options", {
        "artist_id": artist_id,
        "agreement_id": agreement_id,
        "source_opportunity_id": source_opportunity_id,
        "option_type": option_type,
        "income_type": income_type,
        "exercise_window_start": ex_start,
        "exercise_window_end": ex_end,
        "engagement_start_datetime": eng_start,
        "engagement_end_datetime": eng_end,
        "exercise_value_cents": exercise_value,
        "status": "OPEN",
        "exercised_engagement_id": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/options/<rid>")
def get_option(rid):
    return get_one("options", rid)


@bp.get("/options")
def list_options():
    filters = {
        "artist_id": request.args.get("artist_id"),
        "agreement_id": request.args.get("agreement_id"),
        "source_opportunity_id": request.args.get("source_opportunity_id"),
        "exercised_engagement_id": request.args.get("exercised_engagement_id"),
        "status": request.args.get("status"),
    }
    return list_response("options", filters)


@bp.post("/options/<rid>/exercise")
def exercise_option(rid):
    caller = scoped_mutation_auth(["Agent"], "options", rid)
    opt = require_path_resource("options", rid)
    if opt["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "exercise requires OPEN")
    now = CLOCK.now()
    if not (parse_datetime(opt["exercise_window_start"]) <= now <= parse_datetime(opt["exercise_window_end"])):
        raise_error(ERR_OPTION_WINDOW_VIOLATION,
                    "exercise attempted outside the inclusive exercise window")
    agreement = db["agreements"].get(opt["agreement_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise_error(ERR_AGREEMENT_NOT_ACTIVE, "the referenced agreement is not ACTIVE")
    if parse_datetime(opt["engagement_end_datetime"]) <= now:
        raise_error(ERR_ENGAGEMENT_WINDOW_PAST,
                    "the engagement would be born CONFIRMED with its window already past")

    eng = new_record("engagements", {
        "artist_id": opt["artist_id"],
        "opportunity_id": opt.get("source_opportunity_id"),
        "income_type": opt["income_type"],
        "counterparty_name": "",
        "start_datetime": opt["engagement_start_datetime"],
        "end_datetime": opt["engagement_end_datetime"],
        "travel_buffer_hours": 24,
        "guarantee_cents": opt["exercise_value_cents"],
        "status": "CONFIRMED",
        "confirmed_at": CLOCK.now_iso(),
    })
    confirm_cascade(opt["artist_id"], eng, exclude_id=eng["id"])

    opt["status"] = "EXERCISED"
    opt["exercised_engagement_id"] = eng["id"]
    touch(opt)
    return success_object(public(eng), status=201)


@bp.post("/options/<rid>/waive")
def waive_option(rid):
    caller = scoped_mutation_auth(["Artist", "FirmAdmin"], "options", rid)
    opt = require_path_resource("options", rid)
    if opt["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "waive requires OPEN")
    opt["status"] = "WAIVED"
    touch(opt)
    return success_object(public(opt))
