from decimal import Decimal

from flask import Blueprint

import db
from errors import ApiError
from middleware import authenticate, require_role, locked
from response import ok
from serializers import ser_crew
from validators import body, req_field, as_str

bp = Blueprint("crews", __name__)


@bp.post("/pole-program/contractor-crews")
@locked
def create_crew():
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    d = body()
    crew_code = as_str(req_field(d, "crew_code"), "crew_code", non_empty=True)
    region = as_str(req_field(d, "region"), "region")
    if any(c["crew_code"] == crew_code for c in db.crews.values()):
        raise ApiError("ERR_DUPLICATE_CREW_CODE", 409,
                       "crew_code already registered")
    rec = db.new_record()
    rec.update(crew_code=crew_code, region=region, status="ACTIVE",
               qa_pass_count=0, qa_fail_count=0,
               quality_score_lifetime=Decimal("100.00"),
               quality_score_rolling=Decimal("100.00"),
               qa_event_log=[], current_cycle_billing_cents=0)
    db.crews[rec["id"]] = rec
    return ok(ser_crew(rec), 201)


@bp.get("/pole-program/contractor-crews/<cid>")
def get_crew(cid):
    authenticate()
    rec = db.crews.get(cid)
    if rec is None:
        raise ApiError("ERR_CREW_NOT_FOUND", 404, "crew_id does not resolve")
    return ok(ser_crew(rec), 200)
