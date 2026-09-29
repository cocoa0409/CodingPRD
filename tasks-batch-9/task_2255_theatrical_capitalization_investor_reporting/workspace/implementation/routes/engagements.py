"""Theatre engagements and the buffered occupancy rule (PRD 3.1)."""

from flask import Blueprint

import db
import errors
import response
import validation as v
from errors import fail
from middleware import (GENERAL_MANAGER, OPERATOR_ROLES, endpoint, find_production,
                        find_theatre, lookup)
from services import queries as q

bp = Blueprint("engagements", __name__)

ENGAGEMENT_TYPES = ("REHEARSAL", "TECH", "PERFORMANCE_RUN")


@bp.post("/theatre-engagements")
@endpoint((GENERAL_MANAGER,))
def create_engagement():
    data = v.body()
    production_id = v.req_id(data, "production_id")
    theatre_id = v.req_id(data, "theatre_id")
    engagement_type = v.req_enum(data, "engagement_type", ENGAGEMENT_TYPES)
    start_text, start = v.req_date(data, "start_date")
    end_text, end = v.req_date(data, "end_date")
    if end < start:
        fail(errors.ERR_INVALID_REQUEST,
             "end_date must be on or after start_date.")

    find_production(production_id)
    theatre = find_theatre(theatre_id)

    buffer_days = theatre["changeover_buffer_days"]
    for other in q.engagements_of_theatre(theatre_id):
        low = db.add_days(db.parse_iso_date(other["start_date"]), -buffer_days)
        high = db.add_days(db.parse_iso_date(other["end_date"]), buffer_days)
        if start <= high and end >= low:
            fail(errors.ERR_THEATRE_ENGAGEMENT_OVERLAP,
                 "The occupation collides with an existing engagement of this house.")

    row = db.insert("theatre_engagements", {
        "production_id": production_id,
        "theatre_id": theatre_id,
        "engagement_type": engagement_type,
        "start_date": start_text,
        "end_date": end_text,
    }, versioned=False)
    return response.obj(row, 201)


@bp.get("/theatre-engagements/<engagement_id>")
@endpoint(OPERATOR_ROLES)
def read_engagement(engagement_id):
    return response.obj(lookup("theatre_engagements", engagement_id,
                               errors.ERR_THEATRE_ENGAGEMENT_NOT_FOUND))


@bp.get("/theatre-engagements")
@endpoint(OPERATOR_ROLES)
def list_engagements():
    production_id = v.q_str("production_id")
    theatre_id = v.q_str("theatre_id")
    engagement_type = v.q_enum("engagement_type", ENGAGEMENT_TYPES)
    limit, offset = v.pagination()
    rows = [r for r in db.all_rows("theatre_engagements")
            if (production_id is None or r["production_id"] == production_id)
            and (theatre_id is None or r["theatre_id"] == theatre_id)
            and (engagement_type is None
                 or r["engagement_type"] == engagement_type)]
    return response.listing(rows, limit, offset)
