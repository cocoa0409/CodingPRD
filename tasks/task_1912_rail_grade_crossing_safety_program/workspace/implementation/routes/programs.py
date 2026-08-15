"""Funding program endpoints (PRD §3.4)."""
import uuid

from flask import Blueprint

from db import now_iso, store
from errors import (
    ApiError,
    ERR_DUPLICATE_FISCAL_YEAR,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PROGRAM_HAS_OPEN_PROJECTS,
    ERR_PROGRAM_NOT_FOUND,
)
from helpers import (
    body_or_empty,
    get_or_404,
    reject_unknown,
    req_enum,
    req_int,
)
from middleware import auth
from response import ok
from services import domain

bp = Blueprint("funding_programs", __name__)

ALL_ROLES = ("ProgramAdministrator", "RailSafetyOfficer", "LocalAuthority", "RailroadMaintainer")

ALLOCATION_METHODS = ("WATERFALL_BY_RANK", "PROPORTIONAL_SHARE")
PROGRAM_STATUSES = ("OPEN", "ALLOCATION_LOCKED", "CLOSED")

OPEN_PROJECT_STATUSES = ("SELECTED", "AWARDED", "IN_PROGRESS")


def serialize_program(p):
    return {
        "id": p["id"],
        "fiscal_year": p["fiscal_year"],
        "apportionment_cents": p["apportionment_cents"],
        "allocation_method": p["allocation_method"],
        "status": p["status"],
        "available_cents": p["available_cents"],
        "encumbered_cents": p["encumbered_cents"],
        "eligible_demand_cents": p["eligible_demand_cents"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/funding-programs")
def create_program():
    auth(["ProgramAdministrator"])
    body = body_or_empty()
    reject_unknown(body, ("fiscal_year", "apportionment_cents", "allocation_method"))
    fiscal_year = req_int(body, "fiscal_year")
    apportionment_cents = req_int(body, "apportionment_cents")
    if apportionment_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'apportionment_cents' must be greater than zero")
    allocation_method = req_enum(body, "allocation_method", ALLOCATION_METHODS)

    if any(p["fiscal_year"] == fiscal_year for p in store.programs.values()):
        raise ApiError(ERR_DUPLICATE_FISCAL_YEAR, 409,
                       f"A funding program for fiscal_year {fiscal_year} already exists")

    ts = now_iso()
    rec = {
        "id": str(uuid.uuid4()),
        "fiscal_year": fiscal_year,
        "apportionment_cents": apportionment_cents,
        "allocation_method": allocation_method,
        "status": "OPEN",
        "available_cents": apportionment_cents,
        "encumbered_cents": 0,
        "eligible_demand_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.programs[rec["id"]] = rec
    return ok(serialize_program(rec), 201)


@bp.get("/funding-programs/<program_id>")
def get_program(program_id):
    auth(ALL_ROLES)
    rec = get_or_404(store.programs, program_id, ERR_PROGRAM_NOT_FOUND,
                     f"Funding program {program_id} does not exist")
    return ok(serialize_program(rec))


def _run_allocation_sweep(program):
    """calculations.funding_allocation over the program's ELIGIBLE projects."""
    candidates = [
        p for p in store.projects.values()
        if p["program_id"] == program["id"] and p["status"] == "ELIGIBLE"
    ]

    def rank_key(p):
        crossing = store.crossings.get(p["crossing_id"])
        incidents = domain.live_incident_count_5yr(p["crossing_id"]) if crossing else 0
        # priority_score DESC, incident_count_5yr DESC, created_at ASC
        return (-p["priority_score"], -incidents, p["created_at"])

    ranked = sorted(candidates, key=rank_key)

    if program["allocation_method"] == "WATERFALL_BY_RANK":
        remaining = program["available_cents"]
        for project in ranked:
            if remaining >= project["estimated_cost_cents"]:
                project["status"] = "SELECTED"
                project["tentative_award_cents"] = project["estimated_cost_cents"]
                project["updated_at"] = now_iso()
                remaining -= project["estimated_cost_cents"]
            else:
                break  # first non-fitting project stops the sweep immediately
    else:  # PROPORTIONAL_SHARE
        total_requested = sum(p["estimated_cost_cents"] for p in ranked)
        for project in ranked:
            share = (program["available_cents"] * project["estimated_cost_cents"]) // total_requested
            project["status"] = "SELECTED"
            project["tentative_award_cents"] = min(project["estimated_cost_cents"], share)
            project["updated_at"] = now_iso()


@bp.post("/funding-programs/<program_id>/transition")
def transition_program(program_id):
    auth(["ProgramAdministrator"])
    rec = get_or_404(store.programs, program_id, ERR_PROGRAM_NOT_FOUND,
                     f"Funding program {program_id} does not exist")
    body = body_or_empty()
    reject_unknown(body, ("to_status",))
    to_status = body.get("to_status")
    if not isinstance(to_status, str) or to_status not in PROGRAM_STATUSES:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"to_status must be one of: {', '.join(PROGRAM_STATUSES)}")

    if to_status == "ALLOCATION_LOCKED":
        if rec["status"] != "OPEN":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot lock allocation from {rec['status']}")
        _run_allocation_sweep(rec)
        rec["status"] = "ALLOCATION_LOCKED"
        domain.recompute_eligible_demand(rec)
    elif to_status == "CLOSED":
        if rec["status"] != "ALLOCATION_LOCKED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot close from {rec['status']}")
        open_projects = [
            p for p in store.projects.values()
            if p["program_id"] == rec["id"] and p["status"] in OPEN_PROJECT_STATUSES
        ]
        if open_projects:
            raise ApiError(ERR_PROGRAM_HAS_OPEN_PROJECTS, 409,
                           "Program has projects in SELECTED, AWARDED, or IN_PROGRESS")
        rec["status"] = "CLOSED"
    else:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"Cannot move to {to_status} from {rec['status']}")

    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return ok(serialize_program(rec))
