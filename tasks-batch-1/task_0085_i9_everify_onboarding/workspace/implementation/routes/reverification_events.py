"""Reverification (Section 3) event read endpoints (list, get)."""

from flask import Blueprint, request

from errors import err
from db import db
from middleware import require_read_role, parse_pagination
from response import object_response
from listing import sorted_collection, paginate_and_respond
import serializers

bp = Blueprint("reverification_events", __name__)


@bp.route("/reverification-events", methods=["GET"])
def list_events():
    require_read_role()
    limit, offset = parse_pagination()
    records = sorted_collection(db.reverification_events)
    i9_form_id = request.args.get("i9_form_id")
    work_authorization_id = request.args.get("work_authorization_id")
    if i9_form_id is not None:
        records = [r for r in records if r.get("i9_form_id") == i9_form_id]
    if work_authorization_id is not None:
        records = [r for r in records
                   if r.get("work_authorization_id") == work_authorization_id]
    return paginate_and_respond(records, limit, offset,
                                serializers.reverification_event)


@bp.route("/reverification-events/<event_id>", methods=["GET"])
def get_event(event_id):
    require_read_role()
    ev = db.reverification_events.get(event_id)
    if ev is None:
        raise err("ERR_NOT_FOUND", "ReverificationEvent not found")
    return object_response(serializers.reverification_event(ev))
