"""Recommended walking routes and per-segment hazard mapping (PRD 3.7)."""
from flask import Blueprint

import calc
import domain
import validate as v
from auth import require
from db import base_entity, db, now, touch
from errors import bad_request, fail
from response import object_response
from timeutil import fmt_dt

bp = Blueprint("walking_routes", __name__)

READ_ROLES = ("ProgramAdmin", "TrafficEngineer", "CrossingSupervisor",
              "SchoolLiaison", "PublicReporter")


@bp.post("/srts/walking-routes")
def draft_route():
    require("SchoolLiaison", "ProgramAdmin")
    body = v.body()
    school_id = v.req_str(body, "school_id")
    route_code = v.req_str(body, "route_code")
    route_name = v.req_str(body, "route_name")
    segments = _read_segments(body)

    school = domain.get_school(school_id)
    for segment in segments:
        if segment["intersection_id"] is not None:
            domain.get_intersection(segment["intersection_id"])

    route = base_entity()
    route.update({
        "school_id": school["id"],
        "route_code": route_code,
        "route_name": route_name,
        "segments": segments,
        "segment_count": len(segments),
        "hazard_score": float(calc.route_hazard_score(segments)),
        "status": "DRAFT",
        "published_at": None,
        "hold_reason": None,
    })
    db.walking_routes[route["id"]] = route
    touch(school)
    return object_response(route, 201)


def _read_segments(body):
    raw = body.get("segments")
    if raw is None:
        bad_request("Field 'segments' is required.")
    if not isinstance(raw, list) or not raw:
        bad_request("Field 'segments' must be a non-empty array.")
    segments = []
    for item in raw:
        if not isinstance(item, dict):
            bad_request("Every entry of 'segments' must be an object.")
        order = v.req_int(item, "segment_order", minimum=1)
        hazard_type = v.req_enum(item, "hazard_type", calc.HAZARD_TYPES)
        length_ft = v.req_int(item, "length_ft", minimum=1)
        mitigated = v.req_bool(item, "mitigated")
        intersection_id = v.opt_str(item, "intersection_id")
        segments.append({
            "segment_order": order,
            "hazard_type": hazard_type,
            "length_ft": length_ft,
            "mitigated": mitigated,
            "intersection_id": intersection_id,
        })
    orders = sorted(s["segment_order"] for s in segments)
    if orders != list(range(1, len(segments) + 1)):
        bad_request("segment_order values must form exactly 1..N "
                    "with no gaps and no duplicates.")
    segments.sort(key=lambda s: s["segment_order"])
    return segments


@bp.get("/srts/walking-routes/<route_id>")
def read_route(route_id):
    require(*READ_ROLES)
    route = domain.get_route(route_id)
    return object_response(route)


@bp.post("/srts/walking-routes/<route_id>/publish")
def publish_route(route_id):
    require("SchoolLiaison", "ProgramAdmin")
    route = domain.get_route(route_id)

    if route["status"] != "DRAFT":
        fail("ERR_ROUTE_NOT_DRAFT", "Only a DRAFT route can be published.")

    for segment in route["segments"]:
        if segment["hazard_type"] != "UNCONTROLLED_CROSSING" or segment["mitigated"]:
            continue
        intersection = (db.intersections.get(segment["intersection_id"])
                        if segment["intersection_id"] else None)
        if (intersection is None
                or intersection["warrant_status"] not in domain.WARRANT_PERMITTING):
            fail("ERR_ROUTE_CROSSING_NOT_WARRANTED",
                 "Segment %s crosses an untreated, unwarranted intersection."
                 % segment["segment_order"])

    if calc.dec(route["hazard_score"]) > calc.HAZARD_SCORE_CEILING:
        fail("ERR_ROUTE_HAZARD_SCORE_EXCEEDED",
             "hazard_score must be at most 25.00 to publish.")

    for segment in route["segments"]:
        if segment["intersection_id"] is None:
            continue
        intersection = db.intersections.get(segment["intersection_id"])
        if intersection is None or intersection["school_id"] != route["school_id"]:
            fail("ERR_ROUTE_SEGMENT_SCHOOL_MISMATCH",
                 "Segment %s cites an intersection of another school."
                 % segment["segment_order"])

    route["status"] = "PUBLISHED"
    route["published_at"] = fmt_dt(now())
    route["hold_reason"] = None
    touch(route)

    school = domain.get_school(route["school_id"])
    for other in domain.routes_of_school(school):
        if other["id"] == route["id"]:
            continue
        if other["route_code"] != route["route_code"]:
            continue
        if other["status"] not in ("PUBLISHED", "ADVISORY_HOLD"):
            continue
        other["status"] = "RETIRED"
        other["hold_reason"] = None
        touch(other)

    if school["coverage_posture"] == "SUSPENDED":
        route["status"] = "ADVISORY_HOLD"
        route["hold_reason"] = "SCHOOL_COVERAGE_SUSPENDED"
        touch(route)
    return object_response(route)
