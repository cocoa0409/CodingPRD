"""CatastropheEvent endpoints."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_CAT_EVENT_DATE_OVERLAP, ERR_INVALID_REQUEST
from middleware import authorized
from response import success_object, success_list
from routes.helpers import new_common_record, sorted_by_creation
from services.serializers import catastrophe_event_view
from util import parse_date
from validate import (
    get_body,
    parse_pagination,
    reject_server_managed,
    req_str,
    req_date,
    require_body_fk,
    require_path_resource,
)

bp = Blueprint("catastrophe_events", __name__)


@bp.post("/actuarial/catastrophe-events")
def create_catastrophe_event():
    authorized(["AppointedActuary"])
    body = get_body()
    reject_server_managed(body)
    segment_id = req_str(body, "segment_id")
    name = req_str(body, "name")
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")

    # end_date >= start_date is a shape-level requirement
    if parse_date(end_date) < parse_date(start_date):
        raise_error(ERR_INVALID_REQUEST, "end_date must be >= start_date")

    require_body_fk("segments", segment_id, "segment_id")

    # Closed-interval overlap: [s1,e1] vs [s2,e2] overlap iff s1 <= e2 AND s2 <= e1
    # (touching counts as overlap per PRD §3.1).
    new_s = parse_date(start_date)
    new_e = parse_date(end_date)
    for ev in db["catastrophe_events"].values():
        if ev["segment_id"] != segment_id:
            continue
        ex_s = parse_date(ev["start_date"])
        ex_e = parse_date(ev["end_date"])
        if new_s <= ex_e and ex_s <= new_e:
            raise_error(ERR_CAT_EVENT_DATE_OVERLAP,
                        "catastrophe event window overlaps an existing event of the segment")

    rec = new_common_record({
        "segment_id": segment_id,
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
    })
    db["catastrophe_events"][rec["id"]] = rec
    return success_object(catastrophe_event_view(rec), status=201)


@bp.get("/actuarial/segments/<sid>/catastrophe-events")
def list_catastrophe_events(sid):
    authorized(["ClaimsExaminer", "ActuarialAnalyst", "PeerReviewer", "AppointedActuary"])
    require_path_resource("segments", sid)
    limit, offset = parse_pagination()
    all_items = sorted_by_creation([
        e for e in db["catastrophe_events"].values() if e["segment_id"] == sid
    ])
    total = len(all_items)
    page = all_items[offset:offset + limit]
    return success_list([catastrophe_event_view(e) for e in page], total, limit, offset)
