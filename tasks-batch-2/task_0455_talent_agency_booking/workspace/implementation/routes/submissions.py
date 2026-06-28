"""Submission endpoints and lifecycle (PRD §3.2)."""
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
    lookup,
    paginate,
)

bp = Blueprint("submissions", __name__)

ALL_ROLES = {"Agent", "CastingDirector", "Talent"}


@bp.route("/submissions", methods=["POST"])
def create_submission():
    _, role = get_identity()
    require_role(role, {"Agent", "Talent"})
    body = get_json_body()
    casting_call_id = require_str(body, "casting_call_id")
    talent_id = require_str(body, "talent_id")
    comp_card_id = require_str(body, "comp_card_id")
    with lock:
        # Left-to-right existence in declaration order.
        lookup("CastingCall", casting_call_id)
        lookup("Talent", talent_id)
        lookup("CompCard", comp_card_id)
        record = mint_common({
            "casting_call_id": casting_call_id,
            "talent_id": talent_id,
            "comp_card_id": comp_card_id,
            "status": "SUBMITTED",
        })
        db.submissions[record["id"]] = record
        return object_response(public(record), status=201)


@bp.route("/submissions", methods=["GET"])
def list_submissions():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        items = list(db.submissions.values())
        for field in ("casting_call_id", "talent_id", "comp_card_id", "status"):
            val = request.args.get(field)
            if val is not None:
                items = [s for s in items if s[field] == val]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/submissions/<sub_id>", methods=["GET"])
def get_submission(sub_id):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        record = lookup("Submission", sub_id)
        return object_response(public(record), status=200)


def _release_scheduled_slots(sub_id):
    for slot in db.audition_slots.values():
        if slot["submission_id"] == sub_id and slot["status"] == "SCHEDULED":
            slot["status"] = "RELEASED"
            touch(slot)


@bp.route("/submissions/<sub_id>/decline", methods=["POST"])
def decline_submission(sub_id):
    _, role = get_identity()
    require_role(role, {"CastingDirector"})
    with lock:
        sub = lookup("Submission", sub_id)
        if sub["status"] not in ("SUBMITTED", "AUDITION_SCHEDULED", "CALLBACK_SCHEDULED"):
            raise ApiError("ERR_INVALID_STATE")
        sub["status"] = "DECLINED"
        touch(sub)
        _release_scheduled_slots(sub_id)
        return object_response(public(sub), status=200)


@bp.route("/submissions/<sub_id>/withdraw", methods=["POST"])
def withdraw_submission(sub_id):
    _, role = get_identity()
    require_role(role, {"Talent"})
    with lock:
        sub = lookup("Submission", sub_id)
        if sub["status"] not in ("SUBMITTED", "AUDITION_SCHEDULED", "CALLBACK_SCHEDULED"):
            raise ApiError("ERR_INVALID_STATE")
        sub["status"] = "WITHDRAWN"
        touch(sub)
        _release_scheduled_slots(sub_id)
        return object_response(public(sub), status=200)
