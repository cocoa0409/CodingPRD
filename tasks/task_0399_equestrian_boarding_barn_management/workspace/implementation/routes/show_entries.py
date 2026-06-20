"""Show entry routes & state machine (PRD §3.7 Show entries)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_caller, require_role
from response import success
from clock import parse_iso, format_iso
from services.common import new_common, touch, require_str, require_int
from services.serialize import view
from services.lookups import get_horse, get_entry, require_owner_owns, owner_has_active_waiver

bp = Blueprint("show_entries", __name__)


@bp.route("/show-entries", methods=["POST"])
def create_entry():
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    body = request.get_json(silent=True) or {}
    horse_id = require_str(body, "horse_id")
    event_name = require_str(body, "event_name")
    event_date = require_str(body, "event_date")
    entry_fee = require_int(body, "entry_fee_cents")
    horse = get_horse(horse_id)
    require_owner_owns(caller, horse["owner_id"])
    try:
        ed = parse_iso(event_date)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "event_date must be ISO-8601 UTC")
    entry = new_common()
    entry.update({
        "horse_id": horse["id"],
        "event_name": event_name,
        "event_date": format_iso(ed),
        "entry_fee_cents": entry_fee,
        "invoiced": False,
        "status": "SUBMITTED",
    })
    db.entries[entry["id"]] = entry
    return success(view(entry), 201)


_ENTRY_TARGET_ROLES = {
    "CONFIRMED": {"BarnManager"},
    "SCRATCHED": {"BarnManager"},
    "WITHDRAWN": {"Owner"},
}


@bp.route("/show-entries/<entry_id>/transition", methods=["POST"])
def transition_entry(entry_id):
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    entry = get_entry(entry_id)
    body = request.get_json(silent=True) or {}
    target = body.get("target_status")
    if target not in _ENTRY_TARGET_ROLES:
        raise err("ERR_INVALID_STATE", "Unknown or illegal target_status")
    if caller.role not in _ENTRY_TARGET_ROLES[target]:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s not permitted for target %s" % (caller.role, target))
    horse = db.horses.get(entry["horse_id"])
    require_owner_owns(caller, horse["owner_id"] if horse else None)

    if target == "CONFIRMED":
        return _confirm(entry, horse)
    if target == "SCRATCHED":
        return _scratch(entry)
    return _withdraw(entry)


def _confirm(entry, horse):
    if entry["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Entry is not SUBMITTED")
    owner_id = horse["owner_id"] if horse else None
    if not owner_has_active_waiver(owner_id):
        raise err("ERR_WAIVER_NOT_ACTIVE", "Owner has no SIGNED non-expired waiver")
    entry["status"] = "CONFIRMED"
    touch(entry)
    return success(view(entry), 200)


def _scratch(entry):
    if entry["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Entry is not CONFIRMED")
    entry["status"] = "SCRATCHED"
    touch(entry)
    return success(view(entry), 200)


def _withdraw(entry):
    if entry["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Entry is not SUBMITTED")
    entry["status"] = "WITHDRAWN"
    touch(entry)
    return success(view(entry), 200)
