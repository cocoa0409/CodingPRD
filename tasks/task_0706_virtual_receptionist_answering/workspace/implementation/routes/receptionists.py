"""Receptionist routes (PRD §3.3)."""
from flask import Blueprint, request

import errors
import serializers
from db import db
from response import success_object, success_array
from middleware import (get_auth, require_role, ROLE_ADMIN, ROLE_OWNER,
                        ROLE_RECEPTIONIST)
from common import (get_body, make_record, paginate, public, touch,
                    as_str, as_int, as_array)
from services.lookups import find_or_404

bp = Blueprint("receptionists", __name__)

LANGUAGES = {"EN", "ES"}


@bp.route("/va/receptionists", methods=["POST"])
def create_receptionist():
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN})
    body = get_body()

    display_name = as_str(body, "display_name", required=True)
    languages = as_array(body, "languages", required=True)
    if not languages:
        raise errors.err(errors.ERR_INVALID_REQUEST, "languages must be non-empty")
    for lang in languages:
        if lang not in LANGUAGES:
            raise errors.err(errors.ERR_INVALID_REQUEST, "languages values must be in {EN, ES}")
    max_concurrent_calls = as_int(body, "max_concurrent_calls", default=1, minimum=1)

    rec = make_record({
        "display_name": display_name,
        "languages": list(languages),
        "max_concurrent_calls": max_concurrent_calls,
        "status": "OFFLINE",
        "active_call_count": 0,
    })
    db.receptionists[rec["id"]] = rec
    return success_object(serializers.receptionist(public(rec)), 201)


@bp.route("/va/receptionists/<receptionist_id>", methods=["GET"])
def get_receptionist(receptionist_id):
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_RECEPTIONIST, ROLE_OWNER})
    rec = find_or_404(db.receptionists, receptionist_id)
    return success_object(serializers.receptionist(public(rec)), 200)


@bp.route("/va/receptionists", methods=["GET"])
def list_receptionists():
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_RECEPTIONIST})
    records = list(db.receptionists.values())
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, meta = paginate(records)
    return success_array([serializers.receptionist(public(r)) for r in page], meta, 200)


@bp.route("/va/receptionists/<receptionist_id>/go-online", methods=["POST"])
def go_online(receptionist_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_RECEPTIONIST})
    rec = find_or_404(db.receptionists, receptionist_id)
    # Receptionist may only act on itself.
    if rec["id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "A receptionist may only manage itself")

    # Transition OFFLINE -> AVAILABLE (PRD §2.7 priority 6).
    if rec["status"] != "OFFLINE":
        raise errors.err(errors.ERR_INVALID_STATE, "Receptionist is not OFFLINE")
    # Requires >= 1 ACTIVE AvailabilityWindow (PRD §3.3).
    has_window = any(
        w["receptionist_id"] == rec["id"] and w["status"] == "ACTIVE"
        for w in db.availability_windows.values()
    )
    if not has_window:
        raise errors.err(errors.ERR_NO_AVAILABILITY_WINDOW,
                         "Receptionist has no ACTIVE availability window")
    rec["status"] = "AVAILABLE"
    touch(rec)
    return success_object(serializers.receptionist(public(rec)), 200)


@bp.route("/va/receptionists/<receptionist_id>/go-offline", methods=["POST"])
def go_offline(receptionist_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_RECEPTIONIST})
    rec = find_or_404(db.receptionists, receptionist_id)
    if rec["id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "A receptionist may only manage itself")

    if rec["status"] != "AVAILABLE":
        raise errors.err(errors.ERR_INVALID_STATE, "Receptionist is not AVAILABLE")
    if rec["active_call_count"] != 0:
        raise errors.err(errors.ERR_RECEPTIONIST_BUSY,
                         "Receptionist has calls in progress")
    rec["status"] = "OFFLINE"
    touch(rec)
    return success_object(serializers.receptionist(public(rec)), 200)
