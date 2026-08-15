"""ReservingSegment endpoints."""
from flask import Blueprint

from db import db
from middleware import authorized
from response import success_object
from routes.helpers import new_common_record
from services.serializers import segment_view
from validate import (
    get_body,
    reject_server_managed,
    req_str,
    req_enum,
    req_int,
    req_number,
    require_path_resource,
)

bp = Blueprint("segments", __name__)

LOB = ["COMMERCIAL_AUTO", "GENERAL_LIABILITY", "WORKERS_COMP", "PROPERTY"]

# Computed fields that must not appear in request bodies.
COMPUTED = ["last_closed_quarter"]


@bp.post("/actuarial/segments")
def create_segment():
    authorized(["AppointedActuary"])
    body = get_body()
    reject_server_managed(body, COMPUTED)
    name = req_str(body, "name")
    lob = req_enum(body, "line_of_business", LOB)
    threshold = req_int(body, "large_loss_threshold_cents", positive=True)
    mrw = req_number(body, "max_range_width_pct", positive=True)
    bench = req_int(body, "benchmark_open_severity_cents", non_negative=True)

    rec = new_common_record({
        "name": name,
        "line_of_business": lob,
        "large_loss_threshold_cents": threshold,
        "max_range_width_pct": mrw,
        "benchmark_open_severity_cents": bench,
        "last_closed_quarter": None,
    })
    db["segments"][rec["id"]] = rec
    return success_object(segment_view(rec), status=201)


@bp.get("/actuarial/segments/<sid>")
def get_segment(sid):
    authorized(["ClaimsExaminer", "ActuarialAnalyst", "PeerReviewer", "AppointedActuary"])
    rec = require_path_resource("segments", sid)
    return success_object(segment_view(rec))
