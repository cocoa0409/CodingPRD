"""ItemStatistic read endpoints (STATS_READ gated per PRD §2.11)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_NO_ACTIVE_GRANT
from middleware import authorized
from routes.helpers import public, list_response, get_one
from services.grants import caller_may, check_grant
from validate import require_path_resource

bp = Blueprint("statistics", __name__)

READ_ROLES = ["ProgramDirector", "Psychometrician"]


def _program_id_of(stat):
    item = db["items"].get(stat["item_id"])
    return item["program_id"] if item else None


@bp.get("/api/item-statistics")
def list_statistics():
    caller = authorized(READ_ROLES)
    filters = {
        "item_id": request.args.get("item_id"),
        "window_id": request.args.get("window_id"),
        "stats_kind": request.args.get("stats_kind"),
    }

    def visible(rec):
        pid = _program_id_of(rec)
        if pid is None:
            return True
        return caller_may(caller, pid, "STATS_READ")

    return list_response("item_statistics", filters, exclude=visible)


@bp.get("/api/item-statistics/<sid>")
def get_statistic(sid):
    caller = authorized(READ_ROLES)
    rec = require_path_resource("item_statistics", sid)
    pid = _program_id_of(rec)
    if pid is not None:
        check_grant(caller, pid, "STATS_READ")
    return get_one(rec)
