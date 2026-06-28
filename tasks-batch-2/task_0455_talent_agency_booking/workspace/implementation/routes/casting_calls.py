"""CastingCall endpoints and lifecycle (PRD §3.2)."""
from flask import Blueprint, request

from db import db, lock
from errors import ApiError
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import (
    mint_common,
    touch,
    public,
    get_json_body,
    require_str,
    require_enum,
    require_int,
    lookup,
    paginate,
)
from timeutil import require_dt, to_date

bp = Blueprint("casting_calls", __name__)

ALL_ROLES = {"Agent", "CastingDirector", "Talent"}
MEDIA_TYPES = {"BROADCAST_TV", "CABLE", "STREAMING", "PRINT", "DIGITAL"}


@bp.route("/casting-calls", methods=["POST"])
def create_casting_call():
    _, role = get_identity()
    require_role(role, {"CastingDirector"})
    body = get_json_body()
    casting_director_id = require_str(body, "casting_director_id")
    title = require_str(body, "title")
    media_type = require_enum(body, "media_type", MEDIA_TYPES)
    usage_term_months = require_int(body, "usage_term_months", minimum=1)
    require_str(body, "shoot_start_date")
    require_str(body, "shoot_end_date")
    offered_day_rate_cents = require_int(body, "offered_day_rate_cents", minimum=0)
    shoot_start = require_dt(body["shoot_start_date"])
    shoot_end = require_dt(body["shoot_end_date"])
    with lock:
        lookup("CastingDirector", casting_director_id)
        if to_date(shoot_end) < to_date(shoot_start):
            raise ApiError("ERR_INVALID_DATE_RANGE")
        record = mint_common({
            "casting_director_id": casting_director_id,
            "title": title,
            "media_type": media_type,
            "usage_term_months": usage_term_months,
            "shoot_start_date": body["shoot_start_date"],
            "shoot_end_date": body["shoot_end_date"],
            "offered_day_rate_cents": offered_day_rate_cents,
            "status": "OPEN",
        })
        db.casting_calls[record["id"]] = record
        return object_response(public(record), status=201)


@bp.route("/casting-calls", methods=["GET"])
def list_casting_calls():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        items = list(db.casting_calls.values())
        cd_id = request.args.get("casting_director_id")
        if cd_id is not None:
            items = [c for c in items if c["casting_director_id"] == cd_id]
        status = request.args.get("status")
        if status is not None:
            items = [c for c in items if c["status"] == status]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/casting-calls/<call_id>", methods=["GET"])
def get_casting_call(call_id):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        record = lookup("CastingCall", call_id)
        return object_response(public(record), status=200)


@bp.route("/casting-calls/<call_id>/close", methods=["POST"])
def close_casting_call(call_id):
    _, role = get_identity()
    require_role(role, {"CastingDirector"})
    with lock:
        call = lookup("CastingCall", call_id)
        if call["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE")
        call["status"] = "CLOSED"
        touch(call)
        # Cascade link 1: open submissions -> WITHDRAWN.
        for sub in db.submissions.values():
            if sub["casting_call_id"] != call_id:
                continue
            if sub["status"] in ("SUBMITTED", "AUDITION_SCHEDULED", "CALLBACK_SCHEDULED"):
                sub["status"] = "WITHDRAWN"
                touch(sub)
                # Cascade link 2: their SCHEDULED audition slots -> RELEASED.
                for slot in db.audition_slots.values():
                    if slot["submission_id"] == sub["id"] and slot["status"] == "SCHEDULED":
                        slot["status"] = "RELEASED"
                        touch(slot)
        return object_response(public(call), status=200)


@bp.route("/casting-calls/<call_id>/reopen", methods=["POST"])
def reopen_casting_call(call_id):
    _, role = get_identity()
    require_role(role, {"CastingDirector"})
    with lock:
        call = lookup("CastingCall", call_id)
        if call["status"] != "CLOSED":
            raise ApiError("ERR_INVALID_STATE")
        call["status"] = "OPEN"
        touch(call)
        return object_response(public(call), status=200)
