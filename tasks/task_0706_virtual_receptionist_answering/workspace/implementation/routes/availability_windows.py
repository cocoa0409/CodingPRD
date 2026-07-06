"""AvailabilityWindow routes (PRD §3.3)."""
from flask import Blueprint, request

import errors
import serializers
from db import db
from response import success_object, success_array
from middleware import (get_auth, require_role, ROLE_ADMIN, ROLE_RECEPTIONIST)
from common import (get_body, make_record, paginate, public,
                    as_int)
from services.lookups import find_or_404

bp = Blueprint("availability_windows", __name__)


def _overlaps(a_start, a_end, b_start, b_end):
    """Closed intervals [a_start,a_end] and [b_start,b_end] overlap unless they
    merely touch at an endpoint (adjacency end==start allowed) (PRD §3.3)."""
    return a_start < b_end and b_start < a_end


@bp.route("/va/receptionists/<receptionist_id>/availability-windows", methods=["POST"])
def add_window(receptionist_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_RECEPTIONIST, ROLE_ADMIN})
    receptionist = find_or_404(db.receptionists, receptionist_id)
    if role == ROLE_RECEPTIONIST and receptionist["id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "A receptionist may only manage itself")

    body = get_body()
    start_minute = as_int(body, "start_minute", required=True, minimum=0, maximum=1439)
    end_minute = as_int(body, "end_minute", required=True, minimum=1, maximum=1440)
    if end_minute <= start_minute:
        raise errors.err(errors.ERR_INVALID_REQUEST, "end_minute must be greater than start_minute")

    # ERR_WINDOW_OVERLAP against existing ACTIVE windows (PRD §3.3).
    for w in db.availability_windows.values():
        if w["receptionist_id"] != receptionist["id"] or w["status"] != "ACTIVE":
            continue
        if _overlaps(start_minute, end_minute, w["start_minute"], w["end_minute"]):
            raise errors.err(errors.ERR_WINDOW_OVERLAP,
                             "Window overlaps an existing ACTIVE window")

    rec = make_record({
        "receptionist_id": receptionist["id"],
        "start_minute": start_minute,
        "end_minute": end_minute,
        "status": "ACTIVE",
    })
    db.availability_windows[rec["id"]] = rec
    return success_object(serializers.availability_window(public(rec)), 201)


@bp.route("/va/availability-windows/<window_id>", methods=["GET"])
def get_window(window_id):
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_RECEPTIONIST})
    rec = find_or_404(db.availability_windows, window_id)
    return success_object(serializers.availability_window(public(rec)), 200)


@bp.route("/va/availability-windows", methods=["GET"])
def list_windows():
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_RECEPTIONIST})
    records = list(db.availability_windows.values())
    receptionist_id = request.args.get("receptionist_id")
    if receptionist_id is not None:
        records = [r for r in records if r["receptionist_id"] == receptionist_id]
    page, meta = paginate(records)
    return success_array([serializers.availability_window(public(r)) for r in page], meta, 200)
