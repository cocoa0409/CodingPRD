"""VolunteerShift routes: create (posture-gated), get, list, and the lifecycle
book (overlap-guarded) / release / cancel.
"""

from datetime import timedelta

from flask import Blueprint, request

import errors
import serializers
from db import db, lock, new_id, now_ts
from clock import parse_iso8601
from middleware import require_roles
from response import success
from helpers import (get_body, require_str, require_int, opt_int,
                     paginate_and_respond)
from lookups import get_shift, get_campaign, get_volunteer
from services import validation
from services.mutations import touch

bp = Blueprint("shifts", __name__)


def _validate_window(starts_at, ends_at):
    try:
        s = parse_iso8601(starts_at)
        e = parse_iso8601(ends_at)
    except (ValueError, TypeError):
        raise errors.invalid_request("starts_at / ends_at must be valid ISO 8601")
    if not (e > s):
        raise errors.invalid_request("ends_at must be strictly after starts_at")
    return s, e


@bp.route("/fundraising/shifts", methods=["POST"])
@require_roles("CampaignAdmin")
def create_shift():
    body = get_body()
    # priority 4: reference existence of campaign_id.
    campaign_id = require_str(body, "campaign_id")
    campaign = validation.resolve_campaign_ref(campaign_id)
    # priority 5: body shape.
    role_label = require_str(body, "role_label")
    starts_at = require_str(body, "starts_at")
    ends_at = require_str(body, "ends_at")
    _validate_window(starts_at, ends_at)
    setup_buffer_minutes = opt_int(body, "setup_buffer_minutes", 0)
    if setup_buffer_minutes < 0:
        raise errors.invalid_request("setup_buffer_minutes must be at least 0")
    with lock:
        # priority 8: posture gate — shift create requires ACTIVE.
        validation.require_campaign_active_for_create(campaign)
        sid = new_id()
        ts = now_ts()
        shift = {
            "id": sid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "campaign_id": campaign_id,
            "volunteer_id": None,
            "role_label": role_label,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "setup_buffer_minutes": setup_buffer_minutes,
            "status": "OPEN",
        }
        db.shifts[sid] = shift
    return success(serializers.shift(shift), status=201)


@bp.route("/fundraising/shifts", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def list_shifts():
    items = list(db.shifts.values())
    campaign_id = request.args.get("campaign_id")
    status = request.args.get("status")
    volunteer_id = request.args.get("volunteer_id")
    if campaign_id is not None:
        items = [s for s in items if s["campaign_id"] == campaign_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if volunteer_id is not None:
        items = [s for s in items if s.get("volunteer_id") == volunteer_id]
    return paginate_and_respond(items, serializers.shift)


@bp.route("/fundraising/shifts/<shift_id>", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def get_shift_route(shift_id):
    s = get_shift(shift_id)
    return success(serializers.shift(s), status=200)


@bp.route("/fundraising/shifts/<shift_id>/book", methods=["POST"])
@require_roles("CampaignAdmin")
def book(shift_id):
    shift = get_shift(shift_id)
    campaign = get_campaign(shift["campaign_id"])
    body = get_body()
    # priority 4: reference existence — volunteer in the same campaign.
    volunteer_id = require_str(body, "volunteer_id")
    validation.resolve_volunteer_ref(volunteer_id, shift["campaign_id"])
    with lock:
        # priority 7: state legality (OPEN -> BOOKED).
        if shift["status"] != "OPEN":
            raise errors.invalid_state("Shift must be OPEN to book")
        # priority 8: posture gate.
        validation.require_campaign_active(campaign)
        # priority 11: shift_overlap_guard. The requested shift's buffer-extended
        # interval [starts_at - buffer, ends_at) must not overlap any OTHER BOOKED
        # shift of the same volunteer (compared on their plain intervals).
        req_start = parse_iso8601(shift["starts_at"]) - timedelta(
            minutes=shift["setup_buffer_minutes"])
        req_end = parse_iso8601(shift["ends_at"])
        for other in db.shifts.values():
            if other["id"] == shift_id:
                continue
            if other.get("volunteer_id") != volunteer_id:
                continue
            if other["status"] != "BOOKED":
                continue
            o_start = parse_iso8601(other["starts_at"])
            o_end = parse_iso8601(other["ends_at"])
            if req_start < o_end and o_start < req_end:
                raise errors.shift_overlap()
        shift["volunteer_id"] = volunteer_id
        shift["status"] = "BOOKED"
        touch(shift)
    return success(serializers.shift(shift), status=200)


@bp.route("/fundraising/shifts/<shift_id>/release", methods=["POST"])
@require_roles("CampaignAdmin")
def release(shift_id):
    shift = get_shift(shift_id)
    with lock:
        # priority 7: state legality (BOOKED -> RELEASED).
        if shift["status"] != "BOOKED":
            raise errors.invalid_state("Shift must be BOOKED to release")
        shift["status"] = "RELEASED"
        touch(shift)
    return success(serializers.shift(shift), status=200)


@bp.route("/fundraising/shifts/<shift_id>/cancel", methods=["POST"])
@require_roles("CampaignAdmin")
def cancel(shift_id):
    shift = get_shift(shift_id)
    with lock:
        # priority 7: state legality (cancel legal from OPEN or BOOKED).
        if shift["status"] not in ("OPEN", "BOOKED"):
            raise errors.invalid_state("Shift must be OPEN or BOOKED to cancel")
        shift["status"] = "CANCELLED"
        touch(shift)
    return success(serializers.shift(shift), status=200)
