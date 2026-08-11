"""OpenTimeSlot read endpoints."""

from flask import Blueprint, request as freq

from db import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_SLOT_NOT_FOUND
from middleware import get_auth
from response import success_object, paginate
from serializers import slot_json

bp = Blueprint("slots", __name__)

SLOT_STATUSES = {"OPEN", "CLAIMED", "EXPIRED"}


@bp.route("/open-time-slots", methods=["GET"])
def list_slots():
    get_auth()
    items = list(db.slots.values())
    block_id = freq.args.get("block_id")
    if block_id is not None:
        items = [s for s in items if s["block_id"] == block_id]
    or_id = freq.args.get("or_id")
    if or_id is not None:
        items = [s for s in items if s["or_id"] == or_id]
    dt = freq.args.get("date")
    if dt is not None:
        items = [s for s in items if s["date"] == dt]
    st = freq.args.get("status")
    if st is not None:
        if st not in SLOT_STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid status filter")
        items = [s for s in items if s["status"] == st]
    out = [slot_json(s) for s in items]
    out.sort(key=lambda r: (r["created_at"],))
    return paginate(out)


@bp.route("/open-time-slots/<slotId>", methods=["GET"])
def get_slot(slotId):
    get_auth()
    rec = db.slots.get(slotId)
    if rec is None:
        raise ApiError(ERR_SLOT_NOT_FOUND, 404, "open-time slot not found")
    return success_object(slot_json(rec))
