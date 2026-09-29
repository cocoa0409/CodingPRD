"""Road segments and the emergency-vehicle access inspection (PRD 3.1, 2.7)."""

from flask import Blueprint

import response as R
import validation as V
from db import by_seq, db, iso, new_row, touch
from middleware import READ_ALL, auth
from services import calc
from services import constants as C
from services import state as S

bp = Blueprint("road_segments", __name__)


@bp.post("/road-segments")
@auth("RoadCommissioner")
def create_segment():
    body = V.get_body()
    association_id = V.req_str(body, "association_id")
    name = V.req_str(body, "name")
    length_feet = V.req_num(body, "length_feet", exclusive_minimum=0)
    width_feet = V.req_num(body, "width_feet", exclusive_minimum=0)
    max_grade_pct = V.req_num(body, "max_grade_pct", minimum=0)
    surface_type = V.req_enum(body, "surface_type", C.SURFACE_TYPES)
    turnout_count = V.req_int(body, "turnout_count", minimum=0)
    turnaround_present = V.req_bool(body, "turnaround_present")
    bridge_present = V.req_bool(body, "bridge_present")
    bridge_rating = V.opt_num(body, "bridge_load_rating_tons", None, minimum=0)
    culvert_count = V.req_int(body, "culvert_count", minimum=0)

    S.require("association", association_id)

    row = new_row({
        "association_id": association_id,
        "name": name,
        "length_feet": length_feet,
        "width_feet": width_feet,
        "max_grade_pct": max_grade_pct,
        "surface_type": surface_type,
        "turnout_count": turnout_count,
        "turnaround_present": turnaround_present,
        "bridge_present": bridge_present,
        "bridge_load_rating_tons": bridge_rating,
        "culvert_count": culvert_count,
        "required_turnouts": calc.required_turnouts(length_feet),
        "emergency_access_grade": "UNKNOWN",
        "last_inspection_at": None,
    })
    db.road_segments[row["id"]] = row
    return R.ok(row, 201)


@bp.get("/road-segments/<segment_id>")
@auth(*READ_ALL)
def read_segment(segment_id):
    return R.ok(S.require("segment", segment_id))


@bp.get("/road-segments")
@auth(*READ_ALL)
def list_segments():
    limit, offset = V.pagination()
    association_id = V.query_str("association_id")
    grade = V.query_enum("emergency_access_grade", C.ACCESS_GRADES)

    rows = by_seq(list(db.road_segments.values()))
    if association_id is not None:
        rows = [r for r in rows if r["association_id"] == association_id]
    if grade is not None:
        rows = [r for r in rows if r["emergency_access_grade"] == grade]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)


@bp.post("/road-segments/<segment_id>/access-inspections")
@auth("RoadCommissioner")
def record_inspection(segment_id):
    body = V.get_body()
    V.req_dt(body, "inspected_at")  # shape-validate only; stored verbatim below
    width = V.req_num(body, "measured_width_feet", minimum=0)
    grade_pct = V.req_num(body, "measured_max_grade_pct", minimum=0)
    turnouts = V.req_int(body, "measured_turnout_count", minimum=0)
    turnaround = V.req_bool(body, "turnaround_present")
    bridge_supplied = "measured_bridge_load_rating_tons" in body
    bridge_rating = V.opt_num(body, "measured_bridge_load_rating_tons", None, minimum=0)

    segment = S.require("segment", segment_id)

    segment["width_feet"] = width
    segment["max_grade_pct"] = grade_pct
    segment["turnout_count"] = turnouts
    segment["turnaround_present"] = turnaround
    if bridge_supplied:
        segment["bridge_load_rating_tons"] = bridge_rating
    # PRD 3.1: "`last_inspection_at` is set to the supplied `inspected_at`" —
    # the supplied instant is recorded as given, not re-rendered.
    segment["last_inspection_at"] = body["inspected_at"]
    segment["emergency_access_grade"] = calc.evaluate_access_grade(segment)

    if segment["emergency_access_grade"] == "DEFICIENT":
        cancelled = False
        for project in by_seq(list(db.projects.values())):
            if project["road_segment_id"] != segment["id"]:
                continue
            if project["category"] != "PAVING":
                continue
            if project["status"] not in ("BID_SOLICITATION", "AWARDED"):
                continue
            S.cancel_project(project)
            cancelled = True
        if cancelled:
            S.recompute_reserve(S.association_of_segment(segment))

    touch(segment)
    return R.ok(segment)
