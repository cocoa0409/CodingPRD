"""Ballot listing/detail endpoints (community-wide)."""

from flask import Blueprint, request

import db
from auth import require_role
from errors import raise_error
from response import success
from utils import paginate

bp = Blueprint("ballots", __name__)


@bp.route("/ballots", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def list_ballots():
    hid = request.args.get("homeowner_id")
    mid = request.args.get("motion_id")
    items = list(db.ballots.values())
    if hid:
        items = [b for b in items if b["homeowner_id"] == hid]
    if mid:
        items = [b for b in items if b["motion_id"] == mid]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)


@bp.route("/ballots/<bid>", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def get_ballot(bid):
    b = db.ballots.get(bid)
    if not b:
        raise_error("ERR_NOT_FOUND", "ballot not found")
    return success(b)
