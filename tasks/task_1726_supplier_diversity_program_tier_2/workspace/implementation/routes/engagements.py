"""Development engagements (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_ENGAGEMENT_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import TRACKS, make_record, touch, pub_engagement, supplier_engagements
from validate import get_body, req_str, req_int, req_enum, req_date, get_resource

bp = Blueprint("engagements", __name__)

WRITERS = ["DiversityAdmin", "DiversityAnalyst"]
READERS = ["DiversityAdmin", "DiversityAnalyst", "Auditor"]

BUFFER_DAYS = 30


@bp.route("/api/v1/suppliers/<rid>/development-engagements", methods=["POST"])
def create_engagement(rid):
    authorized(WRITERS)
    supplier = get_resource("suppliers", rid)
    body = get_body()
    track = req_enum(body, "track", TRACKS)
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")
    mentor_name = req_str(body, "mentor_name")
    capacity_score_before = req_int(body, "capacity_score_before", minimum=0, maximum=100)
    # Non-overlap + 30-day buffer against the supplier's other ENROLLED/ACTIVE
    # engagements (PRD 3.8). Windows are half-open [start_date, end_date).
    for other in supplier_engagements(supplier["id"]):
        if other["status"] not in ("ENROLLED", "ACTIVE"):
            continue
        o_start, o_end = other["start_date"], other["end_date"]
        overlaps = start_date < o_end and o_start < end_date
        inside_buffer = o_end <= start_date < o_end + timedelta(days=BUFFER_DAYS)
        if overlaps or inside_buffer:
            raise_error(
                ERR_ENGAGEMENT_OVERLAP,
                "engagement window overlaps or starts within 30 days of an "
                "existing ENROLLED/ACTIVE engagement",
            )
    if end_date <= start_date:
        raise_error(ERR_INVALID_REQUEST, "end_date must be strictly after start_date")
    rec = make_record({
        "supplier_id": supplier["id"],
        "track": track,
        "start_date": start_date,
        "end_date": end_date,
        "mentor_name": mentor_name,
        "capacity_score_before": capacity_score_before,
        "capacity_score_after": None,
        "improvement": None,
        "status": "ENROLLED",
    })
    db["engagements"][rec["id"]] = rec
    return success_object(pub_engagement(rec), status=201)


@bp.route("/api/v1/suppliers/<rid>/development-engagements", methods=["GET"])
def list_engagements(rid):
    authorized(READERS)
    supplier = get_resource("suppliers", rid)
    filters = {"status": request.args.get("status")}
    records = [e for e in db["engagements"].values() if e["supplier_id"] == supplier["id"]]
    return list_response(records, filters, pub_engagement)


@bp.route("/api/v1/development-engagements/<rid>/complete", methods=["POST"])
def complete_engagement(rid):
    authorized(WRITERS)
    rec = get_resource("engagements", rid)
    if rec["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "complete requires status ACTIVE")
    body = get_body()
    after = req_int(body, "capacity_score_after", minimum=0, maximum=100)
    rec["capacity_score_after"] = after
    rec["improvement"] = after - rec["capacity_score_before"]
    rec["status"] = "COMPLETED"
    touch(rec)
    return success_object(pub_engagement(rec))


@bp.route("/api/v1/development-engagements/<rid>/withdraw", methods=["POST"])
def withdraw_engagement(rid):
    authorized(WRITERS)
    rec = get_resource("engagements", rid)
    if rec["status"] not in ("ENROLLED", "ACTIVE"):
        raise_error(ERR_INVALID_STATE, "withdraw requires status ENROLLED or ACTIVE")
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return success_object(pub_engagement(rec))
