"""Availability slot endpoints."""
from datetime import timedelta

from flask import Blueprint, g, request

import db
from clock import now, iso, parse_iso
from errors import err
from middleware import require_auth, get_pagination, get_user
from response import success, success_list, no_content
from services.validation import (
    get_body, require_str, CHANNELS,
)
from services.scheduling import check_invariants


bp = Blueprint("availability", __name__)


def _public(s: dict) -> dict:
    return db.public(s)


@bp.route("/counseling/availability-slots", methods=["POST"])
@require_auth(roles={"Counselor"})
def create_slot():
    body = get_body()
    counselor_id = require_str(body, "counselor_id")
    start_at_s = require_str(body, "start_at")
    end_at_s = require_str(body, "end_at")
    channel = require_str(body, "channel")

    if g.user_id != counselor_id:
        raise err("ERR_FORBIDDEN", "Counselor may only create own slots")

    counselor = db.counselors.get(counselor_id)
    if counselor is None:
        raise err("ERR_REF_NOT_FOUND", f"counselor_id {counselor_id} not found")

    if counselor["status"] != "ACTIVE":
        raise err("ERR_COUNSELOR_NOT_ACTIVE",
                  f"Counselor not ACTIVE ({counselor['status']})")

    if channel not in CHANNELS:
        raise err("ERR_VALIDATION", f"invalid channel: {channel}")
    if channel not in counselor["supported_channels"]:
        raise err("ERR_CHANNEL_NOT_SUPPORTED",
                  f"channel {channel} not in counselor.supported_channels")

    try:
        start_at = parse_iso(start_at_s)
        end_at = parse_iso(end_at_s)
    except ValueError:
        raise err("ERR_VALIDATION", "start_at/end_at must be ISO 8601")

    duration_min = int((end_at - start_at).total_seconds() / 60)
    if duration_min != 60 or (end_at - start_at) != timedelta(minutes=60):
        raise err("ERR_INVALID_SLOT_DURATION",
                  "Slot duration must be exactly 60 minutes")

    check_invariants(counselor=counselor, start_at=start_at, end_at=end_at)

    slot = {
        "counselor_id": counselor_id,
        "start_at": iso(start_at),
        "end_at": iso(end_at),
        "channel": channel,
        "status": "OPEN",
        "held_until": None,
        "held_appointment_id": None,
    }
    db.stamp_create(slot, common_fields=True)
    db.availability_slots[slot["id"]] = slot
    return success(_public(slot), 201)


@bp.route("/counseling/availability-slots", methods=["GET"])
def list_slots():
    user_id, role = get_user(allow_public=True)
    if role not in {"Public", "Client", "Counselor", "PlatformAdmin"}:
        raise err("ERR_FORBIDDEN", "Role not authorized")

    limit, offset = get_pagination()
    counselor_id = request.args.get("counselor_id")
    status = request.args.get("status")
    channel = request.args.get("channel")
    from_s = request.args.get("from")
    to_s = request.args.get("to")

    items = list(db.availability_slots.values())
    if counselor_id:
        items = [s for s in items if s["counselor_id"] == counselor_id]
    if status:
        items = [s for s in items if s["status"] == status]
    if channel:
        items = [s for s in items if s["channel"] == channel]
    if from_s:
        try:
            from_dt = parse_iso(from_s)
        except ValueError:
            raise err("ERR_VALIDATION", "from must be ISO 8601")
        items = [s for s in items if parse_iso(s["start_at"]) >= from_dt]
    if to_s:
        try:
            to_dt = parse_iso(to_s)
        except ValueError:
            raise err("ERR_VALIDATION", "to must be ISO 8601")
        items = [s for s in items if parse_iso(s["start_at"]) < to_dt]

    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([_public(s) for s in page], limit, offset, total)


@bp.route("/counseling/availability-slots/<id>", methods=["DELETE"])
@require_auth(roles={"Counselor"})
def delete_slot(id):
    slot = db.availability_slots.get(id)
    if slot is None:
        raise err("ERR_NOT_FOUND", f"AvailabilitySlot {id} not found")
    if g.user_id != slot["counselor_id"]:
        raise err("ERR_FORBIDDEN", "Counselor may only delete own slots")
    if slot["status"] != "OPEN":
        raise err("ERR_INVALID_STATE",
                  f"Slot status {slot['status']} cannot be deleted")
    slot["status"] = "RELEASED"
    db.stamp_update(slot)
    return no_content()
