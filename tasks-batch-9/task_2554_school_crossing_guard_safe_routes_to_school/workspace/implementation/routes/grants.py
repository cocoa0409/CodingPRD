"""Grant programs and the competitive award of infrastructure projects
(PRD 3.8, 2.11)."""
from flask import Blueprint

import calc
import domain
import validate as v
from auth import require
from db import base_entity, db, now, touch
from errors import fail
from response import list_response, object_response
from timeutil import fmt_date, fmt_dt

bp = Blueprint("grants", __name__)

PROJECT_TYPES = ("RRFB", "CURB_EXTENSION", "SIDEWALK_INFILL",
                 "SIGNAL_RETIMING", "RAISED_CROSSWALK")
PROGRAM_READ_ROLES = ("ProgramAdmin", "TrafficEngineer")
REFERRED_COMPLAINT_STATUSES = ("TRIAGED", "REFERRED", "RESOLVED")


@bp.post("/srts/grant-programs")
def open_program():
    require("ProgramAdmin")
    body = v.body()
    program_name = v.req_str(body, "program_name")
    fiscal_year = v.req_int(body, "fiscal_year")
    total_cents = v.req_int(body, "total_cents", minimum=1)
    application_deadline = v.req_date(body, "application_deadline")

    program = base_entity()
    program.update({
        "program_name": program_name,
        "fiscal_year": fiscal_year,
        "total_cents": total_cents,
        "application_deadline": fmt_date(application_deadline),
        "committed_cents": 0,
        "remaining_cents": total_cents,
        "funded_project_count": 0,
        "deferred_project_count": 0,
        "next_cycle_carryover_cents": 0,
    })
    db.grant_programs[program["id"]] = program
    return object_response(program, 201)


@bp.get("/srts/grant-programs/<program_id>")
def read_program(program_id):
    require(*PROGRAM_READ_ROLES)
    program = domain.get_program(program_id)
    return object_response(program)


@bp.post("/srts/infrastructure-projects")
def propose_project():
    require("TrafficEngineer")
    body = v.body()
    program_id = v.req_str(body, "grant_program_id")
    intersection_id = v.req_str(body, "intersection_id")
    project_type = v.req_enum(body, "project_type", PROJECT_TYPES)
    scope_summary = v.req_str(body, "scope_summary")
    requested_cost_cents = v.req_int(body, "requested_cost_cents", minimum=1)
    students_benefited = v.req_int(body, "students_benefited", minimum=0)
    complaint_id = v.opt_str(body, "source_complaint_id")

    program = domain.get_program(program_id)
    intersection = domain.get_intersection(intersection_id)
    complaint = None
    if complaint_id is not None:
        complaint = domain.get_complaint(complaint_id)
        if (complaint["status"] != "TRIAGED"
                or complaint["disposition"] != "REFER_TO_ENGINEERING"
                or complaint["intersection_id"] != intersection["id"]):
            fail("ERR_COMPLAINT_NOT_REFERABLE",
                 "The cited complaint is not a referred complaint on this intersection.")

    project = base_entity()
    project.update({
        "grant_program_id": program["id"],
        "intersection_id": intersection["id"],
        "source_complaint_id": complaint["id"] if complaint else None,
        "project_type": project_type,
        "scope_summary": scope_summary,
        "requested_cost_cents": requested_cost_cents,
        "students_benefited": students_benefited,
        "status": "PROPOSED",
        "benefit_points": None,
        "cost_factor": None,
        "benefit_cost_score": None,
        "referred_complaint_count_at_scoring": None,
        "awarded_cents": 0,
        "funded_at": None,
        "withdrawal_reason": None,
    })
    db.projects[project["id"]] = project

    if complaint is not None:
        complaint["status"] = "REFERRED"
        complaint["referred_project_id"] = project["id"]
        touch(complaint)
    touch(program)
    return object_response(project, 201)


@bp.get("/srts/infrastructure-projects/<project_id>")
def read_project(project_id):
    require(*PROGRAM_READ_ROLES)
    project = domain.get_project(project_id)
    return object_response(project)


@bp.get("/srts/infrastructure-projects")
def list_projects():
    require(*PROGRAM_READ_ROLES)
    limit, offset = v.pagination()
    program_id = v.query_filter("grant_program_id")
    intersection_id = v.query_filter("intersection_id")
    complaint_id = v.query_filter("source_complaint_id")
    status = v.query_filter("status")
    records = list(db.projects.values())
    if program_id is not None:
        records = [p for p in records if p["grant_program_id"] == program_id]
    if intersection_id is not None:
        records = [p for p in records if p["intersection_id"] == intersection_id]
    if complaint_id is not None:
        records = [p for p in records if p["source_complaint_id"] == complaint_id]
    if status is not None:
        records = [p for p in records if p["status"] == status]
    return list_response(records, limit, offset)


@bp.post("/srts/infrastructure-projects/<project_id>/score")
def score_project(project_id):
    require("TrafficEngineer")
    project = domain.get_project(project_id)

    if project["status"] != "PROPOSED":
        fail("ERR_PROJECT_NOT_SCORED", "Only a PROPOSED project can be scored.")

    intersection = domain.get_intersection(project["intersection_id"])
    if intersection["latest_warrant_score"] is None:
        fail("ERR_INTERSECTION_NOT_STUDIED",
             "The project's intersection carries no finalized warrant score.")

    crashes = domain.pedestrian_crashes_in_window(intersection, now().date())
    crash_points = calc.severity_points(crashes)
    referred = sum(1 for c in domain.complaints_of_intersection(intersection["id"])
                   if c["status"] in REFERRED_COMPLAINT_STATUSES)

    points = calc.benefit_points(intersection["latest_warrant_score"], crash_points,
                                 project["students_benefited"], referred)
    factor = calc.cost_factor(project["requested_cost_cents"])

    project["referred_complaint_count_at_scoring"] = referred
    project["benefit_points"] = float(points)
    project["cost_factor"] = float(factor)
    project["benefit_cost_score"] = float(calc.benefit_cost_score(points, factor))
    project["status"] = "SCORED"
    touch(project)
    return object_response(project)


def _ranking_key(project):
    return (-calc.dec(project["benefit_cost_score"]),
            project["requested_cost_cents"],
            project["created_at"],
            project["_seq"])


@bp.post("/srts/infrastructure-projects/<project_id>/fund")
def fund_project(project_id):
    require("ProgramAdmin")
    body = v.body()
    expected_version = v.req_int(body, "expected_grant_program_version")
    v.opt_str(body, "award_note")
    project = domain.get_project(project_id)

    if project["status"] != "SCORED":
        fail("ERR_PROJECT_NOT_SCORED", "Only a SCORED project can be funded.")

    program = domain.get_program(project["grant_program_id"])
    if expected_version != program["version"]:
        fail("ERR_STALE_GRANT_PROGRAM_VERSION",
             "expected_grant_program_version does not match the stored version.")

    pool = [p for p in domain.projects_of_program(program["id"])
            if p["status"] == "SCORED"]
    pool.sort(key=_ranking_key)
    if pool[0]["id"] != project["id"]:
        fail("ERR_PROJECT_NOT_TOP_RANKED",
             "This project is not the top-ranked scored candidate of its program.")

    if project["requested_cost_cents"] > program["remaining_cents"]:
        fail("ERR_GRANT_FUNDS_EXHAUSTED",
             "The program's remaining balance cannot cover this award.")

    project["status"] = "FUNDED"
    project["awarded_cents"] = project["requested_cost_cents"]
    project["funded_at"] = fmt_dt(now())
    touch(project)

    domain.recompute_program_balance(program)
    if program["remaining_cents"] == 0:
        for other in domain.projects_of_program(program["id"]):
            if other["id"] != project["id"] and other["status"] == "SCORED":
                other["status"] = "DEFERRED"
                touch(other)
        domain.recompute_program_balance(program)

    _move_cited_complaint(project, "REFERRED", "RESOLVED", -1)
    return object_response(project)


@bp.post("/srts/infrastructure-projects/<project_id>/withdraw-funding")
def withdraw_funding(project_id):
    require("ProgramAdmin")
    body = v.body()
    withdrawal_reason = v.req_str(body, "withdrawal_reason")
    expected_version = v.req_int(body, "expected_grant_program_version")
    project = domain.get_project(project_id)

    if project["status"] != "FUNDED":
        fail("ERR_PROJECT_NOT_FUNDED", "Only a FUNDED project can be withdrawn.")

    program = domain.get_program(project["grant_program_id"])
    if expected_version != program["version"]:
        fail("ERR_STALE_GRANT_PROGRAM_VERSION",
             "expected_grant_program_version does not match the stored version.")

    project["status"] = "SCORED"
    project["awarded_cents"] = 0
    project["withdrawal_reason"] = withdrawal_reason
    touch(project)

    domain.recompute_program_balance(program)
    if program["remaining_cents"] > 0:
        for other in domain.projects_of_program(program["id"]):
            if other["status"] == "DEFERRED":
                other["status"] = "SCORED"
                touch(other)
        domain.recompute_program_balance(program)

    _move_cited_complaint(project, "RESOLVED", "REFERRED", 1)
    return object_response(project)


def _move_cited_complaint(project, from_status, to_status, delta):
    complaint_id = project["source_complaint_id"]
    if not complaint_id:
        return
    complaint = db.complaints.get(complaint_id)
    if complaint is None or complaint["status"] != from_status:
        return
    complaint["status"] = to_status
    touch(complaint)
    intersection = db.intersections.get(complaint["intersection_id"])
    if intersection is not None:
        intersection["open_complaint_count"] += delta
        touch(intersection)
