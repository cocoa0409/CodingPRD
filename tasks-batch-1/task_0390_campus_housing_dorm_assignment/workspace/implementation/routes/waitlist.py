"""Waitlist entry routes: get, list (read-only artifacts)."""

from flask import Blueprint, request

import db
import response
import common
from middleware import authenticate, require_role
from services import core

bp = Blueprint("waitlist", __name__)

ALL_ROLES = ("HousingOfficer", "Student", "ResidentAdvisor")


@bp.route("/waitlist-entries/<entry_id>", methods=["GET"])
def get_entry(entry_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        rec = core.get_or_404(db.waitlist_entries, entry_id)
        return response.object_response(core.serialize(rec))


@bp.route("/waitlist-entries", methods=["GET"])
def list_entries():
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        limit, offset = common.parse_pagination()
        items = list(db.waitlist_entries.values())
        for key in ("cycle_id", "application_id"):
            val = request.args.get(key)
            if val is not None:
                items = [e for e in items if e.get(key) == val]
        items = common.sort_by_created(items)
        page, total = common.paginate(items, limit, offset)
        return response.array_response(
            [core.serialize(e) for e in page], limit, offset, total
        )
