"""Crossing locations, crash history and public complaints (PRD 3.2, 3.8)."""
from flask import Blueprint

import domain
import validate as v
from auth import require
from db import base_entity, db, now, touch
from response import list_response, object_response
from timeutil import fmt_date, fmt_dt

bp = Blueprint("intersections", __name__)

READ_ROLES = ("ProgramAdmin", "TrafficEngineer", "CrossingSupervisor", "SchoolLiaison")
STUDY_LIST_ROLES = ("ProgramAdmin", "TrafficEngineer", "CrossingSupervisor")

CONTROL_TYPES = ("UNCONTROLLED", "STOP_SIGN", "SIGNALIZED")
SEVERITIES = ("PROPERTY_DAMAGE_ONLY", "INJURY", "SEVERE_INJURY", "FATAL")
COMPLAINT_TYPES = ("SPEEDING", "NEAR_MISS", "FAILURE_TO_YIELD",
                   "SIGHT_OBSTRUCTION", "SIGNAL_TIMING")
SEVERITY_CLAIMS = ("LOW", "MEDIUM", "HIGH")


@bp.post("/srts/intersections")
def register_intersection():
    require("ProgramAdmin")
    body = v.body()
    school_id = v.req_str(body, "school_id")
    cross_streets = v.req_str(body, "cross_streets")
    control_type = v.req_enum(body, "control_type", CONTROL_TYPES)
    speed_limit_mph = v.req_int(body, "speed_limit_mph", minimum=5, maximum=65)
    lanes_crossed = v.req_int(body, "lanes_crossed", minimum=1)
    posted_school_zone = v.opt_bool(body, "posted_school_zone", default=False)
    school = domain.get_school(school_id)

    intersection = base_entity()
    intersection.update({
        "school_id": school["id"],
        "cross_streets": cross_streets,
        "control_type": control_type,
        "speed_limit_mph": speed_limit_mph,
        "lanes_crossed": lanes_crossed,
        "posted_school_zone": posted_school_zone,
        "warrant_status": "NOT_STUDIED",
        "latest_warrant_score": None,
        "crash_history": [],
        "pedestrian_crash_count_window": 0,
        "crash_severity_points": 0,
        "open_complaint_count": 0,
    })
    db.intersections[intersection["id"]] = intersection
    touch(school)
    return object_response(intersection, 201)


@bp.get("/srts/intersections/<intersection_id>")
def read_intersection(intersection_id):
    require(*READ_ROLES)
    intersection = domain.get_intersection(intersection_id)
    return object_response(intersection)


@bp.post("/srts/intersections/<intersection_id>/crash-records")
def append_crash_record(intersection_id):
    require("TrafficEngineer", "ProgramAdmin")
    body = v.body()
    crash_date = v.req_date(body, "crash_date")
    severity = v.req_enum(body, "severity", SEVERITIES)
    involved_pedestrian = v.req_bool(body, "involved_pedestrian")
    involved_school_age = v.req_bool(body, "involved_school_age")
    intersection = domain.get_intersection(intersection_id)

    intersection["crash_history"].append({
        "crash_date": fmt_date(crash_date),
        "severity": severity,
        "involved_pedestrian": involved_pedestrian,
        "involved_school_age": involved_school_age,
        "recorded_at": fmt_dt(now()),
    })
    domain.refresh_crash_aggregates(intersection)
    touch(intersection)
    return object_response(intersection)


@bp.get("/srts/intersections/<intersection_id>/warrant-studies")
def list_intersection_studies(intersection_id):
    require(*STUDY_LIST_ROLES)
    limit, offset = v.pagination()
    status = v.query_filter("status")
    intersection = domain.get_intersection(intersection_id)
    records = [s for s in db.studies.values()
               if s["intersection_id"] == intersection["id"]]
    if status is not None:
        records = [s for s in records if s["status"] == status]
    return list_response(records, limit, offset)


@bp.get("/srts/intersections/<intersection_id>/guard-posts")
def list_intersection_posts(intersection_id):
    require(*STUDY_LIST_ROLES)
    limit, offset = v.pagination()
    status = v.query_filter("status")
    intersection = domain.get_intersection(intersection_id)
    records = domain.posts_of_intersection(intersection)
    if status is not None:
        records = [p for p in records if p["status"] == status]
    return list_response(records, limit, offset)


@bp.get("/srts/intersections/<intersection_id>/complaints")
def list_intersection_complaints(intersection_id):
    require(*READ_ROLES)
    limit, offset = v.pagination()
    status = v.query_filter("status")
    intersection = domain.get_intersection(intersection_id)
    records = domain.complaints_of_intersection(intersection["id"])
    if status is not None:
        records = [c for c in records if c["status"] == status]
    return list_response(records, limit, offset)


@bp.post("/srts/intersections/<intersection_id>/complaints")
def file_complaint(intersection_id):
    require("PublicReporter", "SchoolLiaison", "ProgramAdmin")
    body = v.body()
    complaint_type = v.req_enum(body, "complaint_type", COMPLAINT_TYPES)
    reporter_name = v.req_str(body, "reporter_name")
    occurred_at = v.req_str(body, "occurred_at")
    v.req_datetime(body, "occurred_at")
    narrative = v.req_str(body, "narrative")
    severity_claim = v.req_enum(body, "severity_claim", SEVERITY_CLAIMS)
    reporter_contact = v.opt_str(body, "reporter_contact")
    intersection = domain.get_intersection(intersection_id)

    complaint = base_entity()
    complaint.update({
        "intersection_id": intersection["id"],
        "complaint_type": complaint_type,
        "reporter_name": reporter_name,
        "reporter_contact": reporter_contact,
        "occurred_at": occurred_at,
        "narrative": narrative,
        "severity_claim": severity_claim,
        "status": "RECEIVED",
        "disposition": None,
        "triaged_by_user_id": None,
        "triage_note": None,
        "referred_project_id": None,
    })
    db.complaints[complaint["id"]] = complaint
    intersection["open_complaint_count"] += 1
    touch(intersection)
    return object_response(complaint, 201)
