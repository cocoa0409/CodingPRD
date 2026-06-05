"""ActionItem create/read + lifecycle (start/complete/cancel) with bubble-up."""
from flask import Blueprint, request

import response
from db import db
from errors import ApiError
from middleware import require_user_context, require_role, get_json_body, get_pagination
from services.common import require_str, stamp_create, touch
from services.lookups import get_postmortem, get_responder, get_action_item
from services.serializers import action_item_out

bp = Blueprint("action_items", __name__)

ALL_ROLES = {"PlatformAdmin", "IncidentCommander", "ResponderUser"}


@bp.route("/action-items", methods=["POST"])
def create_action_item():
    _, role = require_user_context()
    require_role(role, {"IncidentCommander"})
    body = get_json_body()
    postmortem_id = require_str(body, "postmortem_id")
    owner_responder_id = require_str(body, "owner_responder_id")
    with db.lock:
        pm = get_postmortem(postmortem_id)   # FK existence (priority 3)
        get_responder(owner_responder_id)
        description = require_str(body, "description")
        rec = stamp_create({
            "postmortem_id": postmortem_id,
            "owner_responder_id": owner_responder_id,
            "description": description,
            "status": "OPEN",
        })
        db.action_items[rec["id"]] = rec
        # bubble-up: parent open_action_item_count incremented by 1
        touch(pm)
    return response.success(action_item_out(rec), 201)


@bp.route("/action-items/<aid>", methods=["GET"])
def get_one_action_item(aid):
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        ai = get_action_item(aid)
        return response.success(action_item_out(ai), 200)


@bp.route("/postmortems/<pid>/action-items", methods=["GET"])
def list_postmortem_action_items(pid):
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    limit, offset = get_pagination()
    with db.lock:
        get_postmortem(pid)
        rows = [ai for ai in db.action_items.values() if ai["postmortem_id"] == pid]
        return response.list_response(rows, limit, offset, action_item_out)


@bp.route("/action-items", methods=["GET"])
def list_action_items():
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    limit, offset = get_pagination()
    owner_responder_id = request.args.get("owner_responder_id")
    postmortem_id = request.args.get("postmortem_id")
    with db.lock:
        rows = list(db.action_items.values())
        if owner_responder_id is not None:
            rows = [r for r in rows if r["owner_responder_id"] == owner_responder_id]
        if postmortem_id is not None:
            rows = [r for r in rows if r["postmortem_id"] == postmortem_id]
        return response.list_response(rows, limit, offset, action_item_out)


@bp.route("/action-items/<aid>/start", methods=["POST"])
def start_action_item(aid):
    user_id, role = require_user_context()
    require_role(role, {"ResponderUser"})
    with db.lock:
        ai = get_action_item(aid)
        # state (priority 6): must be OPEN
        if ai["status"] != "OPEN":
            raise ApiError("ERR_ACTION_ITEM_NOT_OPEN", "Action item is not OPEN.")
        # ownership (priority 8)
        if ai["owner_responder_id"] != user_id:
            raise ApiError("ERR_NOT_ACTION_ITEM_OWNER", "Acting responder is not the owner.")
        ai["status"] = "IN_PROGRESS"
        touch(ai)
        # bubble-up: OPEN+IN_PROGRESS both counted, so count unchanged; still
        # an independent recompute -> parent updated_at/version refreshed.
        _touch_parent(ai)
        return response.success(action_item_out(ai), 200)


@bp.route("/action-items/<aid>/complete", methods=["POST"])
def complete_action_item(aid):
    user_id, role = require_user_context()
    require_role(role, {"ResponderUser"})
    with db.lock:
        ai = get_action_item(aid)
        if ai["status"] != "IN_PROGRESS":
            raise ApiError("ERR_ACTION_ITEM_NOT_IN_PROGRESS", "Action item is not IN_PROGRESS.")
        if ai["owner_responder_id"] != user_id:
            raise ApiError("ERR_NOT_ACTION_ITEM_OWNER", "Acting responder is not the owner.")
        ai["status"] = "DONE"
        touch(ai)
        # bubble-up: parent open_action_item_count decremented by 1
        _touch_parent(ai)
        return response.success(action_item_out(ai), 200)


@bp.route("/action-items/<aid>/cancel", methods=["POST"])
def cancel_action_item(aid):
    _, role = require_user_context()
    require_role(role, {"IncidentCommander"})
    with db.lock:
        ai = get_action_item(aid)
        if ai["status"] not in ("OPEN", "IN_PROGRESS"):
            raise ApiError("ERR_ACTION_ITEM_TERMINAL", "Action item is already terminal.")
        ai["status"] = "CANCELLED"
        touch(ai)
        # compensation: parent open_action_item_count decremented by 1
        _touch_parent(ai)
        return response.success(action_item_out(ai), 200)


def _touch_parent(ai):
    pm = db.postmortems.get(ai["postmortem_id"])
    if pm is not None:
        touch(pm)
