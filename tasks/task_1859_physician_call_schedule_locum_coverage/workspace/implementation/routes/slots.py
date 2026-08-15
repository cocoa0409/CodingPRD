"""Call slots — read-only; created by generation. Pinned sort: date ASC, then
call_type ASC (BACKUP before PRIMARY), then position_index ASC (PRD §3.3)."""
from flask import Blueprint

from db import store
from errors import ApiError
from middleware import require_roles
from response import ok, paginate

bp = Blueprint("slots", __name__)

ALL = ["SchedulerAdmin", "ChiefOfStaff", "Physician", "CredentialingOfficer"]


def get_slot_or_404(slot_id):
    slot = store.slots.get(slot_id)
    if slot is None:
        raise ApiError("ERR_SLOT_NOT_FOUND", 404, "CallSlot id does not exist")
    return slot


def slot_sort_key(s):
    return (s.get("date", ""), s.get("call_type", ""), s.get("position_index", 0))


@bp.route("/api/call-slots", methods=["GET"])
def list_slots():
    require_roles(ALL)
    rows = list(store.slots.values())
    rows = paginate.filter(rows, "program_id")
    rows = paginate.filter(rows, "date")
    rows = paginate.filter(rows, "call_type")
    rows = paginate.filter(rows, "date_type")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows, sort_key=slot_sort_key), rtype="array", pagination=paginate)


@bp.route("/api/call-slots/<slot_id>", methods=["GET"])
def get_slot(slot_id):
    require_roles(ALL)
    return ok(get_slot_or_404(slot_id))
