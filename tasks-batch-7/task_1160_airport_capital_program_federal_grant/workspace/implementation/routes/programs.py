"""Capital programs (CIP) and CIP projects."""
from decimal import Decimal

from flask import Blueprint, request

from auth import ALL_ROLES, require
from domain import (PROJECT_TYPES, apply_selection, program_projects,
                    recompute_selected_total, scrub_project_from_applications,
                    ser_program, ser_project)
from errors import ApiError, err_invalid_state, err_validation
from store import DB
from util import (as_bool, as_enum, as_int, as_number, as_str, body,
                  get_or_404, need, new_entity, respond, respond_list, touch)

bp = Blueprint("programs", __name__)

LIVE_PROJECT_STATUSES = ("PROPOSED", "SELECTED", "DEFERRED")


def _get_program(pid):
    return get_or_404(DB.programs, pid, "CapitalProgram")


@bp.route("/aip/capital-programs", methods=["POST"])
@require("SponsorStaff")
def create_program():
    b = body()
    if "sponsor_id" not in b or b["sponsor_id"] is None:
        raise err_validation("Missing required field: sponsor_id")
    sponsor = get_or_404(DB.sponsors, b["sponsor_id"], "Sponsor")
    fy = as_int(need(b, "fiscal_year"), "fiscal_year")
    if not (2026 <= fy <= 2035):
        raise err_validation("fiscal_year must be within 2026..2035")
    if any(p["sponsor_id"] == sponsor["id"] and p["fiscal_year"] == fy
           for p in DB.programs.values()):
        raise err_validation("fiscal_year must be unique per sponsor")
    p = new_entity()
    p.update({"sponsor_id": sponsor["id"], "fiscal_year": fy,
              "selection_budget": Decimal("0"),
              "selected_total_cost": Decimal("0"), "status": "DRAFT"})
    DB.programs[p["id"]] = p
    return respond(ser_program(p), 201)


@bp.route("/aip/capital-programs", methods=["GET"])
@require(*ALL_ROLES)
def list_programs():
    items = list(DB.programs.values())
    sponsor_id = request.args.get("sponsor_id")
    status = request.args.get("status")
    if sponsor_id is not None:
        items = [p for p in items if p["sponsor_id"] == sponsor_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return respond_list(items, ser_program)


@bp.route("/aip/capital-programs/<programId>", methods=["GET"])
@require(*ALL_ROLES)
def get_program(programId):
    return respond(ser_program(_get_program(programId)))


@bp.route("/aip/capital-programs/<programId>/submit", methods=["POST"])
@require("SponsorStaff")
def submit_program(programId):
    p = _get_program(programId)
    if p["status"] not in ("DRAFT", "AMENDMENT_DRAFT"):
        raise err_invalid_state(
            f"CapitalProgram in status {p['status']} cannot be submitted")
    if not any(c["status"] in LIVE_PROJECT_STATUSES
               for c in program_projects(p["id"])):
        raise ApiError("ERR_PROGRAM_EMPTY", 422,
                       "Program has no child projects in a live status")
    p["status"] = "SUBMITTED"
    touch(p)
    return respond(ser_program(p))


@bp.route("/aip/capital-programs/<programId>/accept", methods=["POST"])
@require("FAAManager")
def accept_program(programId):
    p = _get_program(programId)
    if p["status"] != "SUBMITTED":
        raise err_invalid_state(
            f"CapitalProgram in status {p['status']} cannot be accepted")
    p["status"] = "ACCEPTED"
    touch(p)
    return respond(ser_program(p))


@bp.route("/aip/capital-programs/<programId>/begin-amendment",
          methods=["POST"])
@require("SponsorStaff")
def begin_amendment(programId):
    p = _get_program(programId)
    if p["status"] != "ACCEPTED":
        raise err_invalid_state(
            f"CapitalProgram in status {p['status']} cannot begin amendment")
    p["status"] = "AMENDMENT_DRAFT"
    touch(p)
    return respond(ser_program(p))


@bp.route("/aip/capital-programs/<programId>/apply-selection",
          methods=["POST"])
@require("SponsorStaff")
def apply_selection_endpoint(programId):
    p = _get_program(programId)
    if p["status"] != "ACCEPTED":
        raise err_invalid_state(
            "Selection sweep requires an ACCEPTED CapitalProgram")
    b = body()
    budget = as_number(need(b, "selection_budget"), "selection_budget")
    expected = as_int(need(b, "expected_program_version"),
                      "expected_program_version")
    # OCC is evaluated last (priority 29).
    if expected != p["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_program_version does not match the program's "
                       "current version")
    apply_selection(p, budget)
    return respond(ser_program(p))


# ---------------------------------------------------------------------------
# CIP projects
# ---------------------------------------------------------------------------

SCORE_FIELDS = ("safety_score", "capacity_score", "preservation_score",
                "security_score", "environmental_score")


@bp.route("/aip/cip-projects", methods=["POST"])
@require("SponsorStaff")
def create_project():
    b = body()
    if "program_id" not in b or b["program_id"] is None:
        raise err_validation("Missing required field: program_id")
    program = get_or_404(DB.programs, b["program_id"], "CapitalProgram")
    if program["status"] not in ("DRAFT", "AMENDMENT_DRAFT"):
        raise err_invalid_state(
            "Projects may only be added while the program is DRAFT or "
            "AMENDMENT_DRAFT")
    title = as_str(need(b, "title"), "title")
    ptype = as_enum(need(b, "project_type"), "project_type", PROJECT_TYPES)
    cost = as_number(need(b, "estimated_cost"), "estimated_cost")
    if cost <= 0:
        raise err_validation("estimated_cost must be > 0")
    scores = {}
    for f in SCORE_FIELDS:
        v = as_int(need(b, f), f)
        if not (0 <= v <= 20):
            raise err_validation(f"{f} must be within 0..20")
        scores[f] = v
    rsa = b.get("runway_safety_noncompliant", False)
    mas = b.get("multi_airport_system", False)
    if not isinstance(rsa, bool):
        raise err_validation("runway_safety_noncompliant must be a boolean")
    if not isinstance(mas, bool):
        raise err_validation("multi_airport_system must be a boolean")
    p = new_entity()
    p.update({"program_id": program["id"], "title": title,
              "project_type": ptype, "estimated_cost": cost,
              "runway_safety_noncompliant": rsa, "multi_airport_system": mas,
              "priority_score_sponsor": None, "priority_score_federal": None,
              "selection_rank": None, "status": "PROPOSED", **scores})
    DB.projects[p["id"]] = p
    return respond(ser_project(p), 201)


@bp.route("/aip/cip-projects", methods=["GET"])
@require(*ALL_ROLES)
def list_projects():
    items = list(DB.projects.values())
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [p for p in items if p["program_id"] == program_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return respond_list(items, ser_project)


@bp.route("/aip/cip-projects/<projectId>", methods=["GET"])
@require(*ALL_ROLES)
def get_project(projectId):
    return respond(ser_project(
        get_or_404(DB.projects, projectId, "CIPProject")))


@bp.route("/aip/cip-projects/<projectId>/drop", methods=["POST"])
@require("SponsorStaff")
def drop_project(projectId):
    p = get_or_404(DB.projects, projectId, "CIPProject")
    if p["status"] == "DROPPED":
        raise err_invalid_state("CIPProject is already DROPPED")
    prior_status = p["status"]
    program = DB.programs.get(p["program_id"])
    if prior_status == "SELECTED":
        if any(c["cip_project_id"] == p["id"] for c in DB.contracts.values()):
            raise ApiError("ERR_PROJECT_UNDER_CONTRACT", 422,
                           "A Contract references this project")
        if any(p["id"] in a["project_ids"] for a in DB.applications.values()
               if a["status"] in ("UNDER_REVIEW", "OFFERED")):
            raise ApiError("ERR_PROJECT_IN_ACTIVE_APPLICATION", 422,
                           "An UNDER_REVIEW or OFFERED application references "
                           "this project")
        scrub_project_from_applications(p, ("DRAFT", "RETURNED"))
    p["status"] = "DROPPED"
    touch(p)
    # Program recompute applies to DEFERRED/SELECTED drops (side-effect table).
    if program is not None and prior_status in ("SELECTED", "DEFERRED"):
        recompute_selected_total(program)
        touch(program)
    return respond(ser_project(p))
