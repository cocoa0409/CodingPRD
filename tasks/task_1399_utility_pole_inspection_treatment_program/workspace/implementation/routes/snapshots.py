from flask import Blueprint, request

import db
from errors import ApiError
from middleware import authenticate
from response import ok, ok_list
from serializers import ser_snapshot
from validators import pagination, apply_filters

bp = Blueprint("snapshots", __name__)


@bp.get("/pole-program/backlog-snapshots")
def list_snapshots():
    authenticate()
    limit, offset = pagination()
    items = apply_filters(db.snapshots.values(), [
        ("cycle_id", request.args.get("cycle_id")),
        ("budget_id", request.args.get("budget_id")),
    ])
    page = items[offset:offset + limit]
    return ok_list([ser_snapshot(s) for s in page], len(items), limit, offset)


@bp.get("/pole-program/backlog-snapshots/<sid>")
def get_snapshot(sid):
    authenticate()
    rec = db.snapshots.get(sid)
    if rec is None:
        raise ApiError("ERR_SNAPSHOT_NOT_FOUND", 404,
                       "backlog snapshot id does not resolve")
    return ok(ser_snapshot(rec), 200)
