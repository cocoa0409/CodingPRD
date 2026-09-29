"""Sponsors, sanctions, investors, cap pools and development filing (PRD 3.1-3.2)."""

from flask import Blueprint

import calc
import domain
import serialize
import validation as v
from auth import guard, own_project
from envelope import object_response
from errors import fail
from store import db, new_row, touch

bp = Blueprint("onboarding", __name__)


@bp.post("/developers")
def create_developer():
    guard("POST /developers")
    body = v.body()
    name = v.req_str(body, "name", allow_empty=False)
    tax_id = v.req_str(body, "tax_id", allow_empty=False)
    contact_email = v.req_str(body, "contact_email", allow_empty=False)
    row = new_row(db.developers, {
        "name": name,
        "tax_id": tax_id,
        "contact_email": contact_email,
        "status": "ACTIVE",
        "sanction_reason": None,
    })
    return object_response(serialize.developer(row), 201)


@bp.post("/developers/<row_id>/sanctions")
def sanction_developer(row_id):
    guard("POST /developers/{id}/sanctions")
    body = v.body()
    action = v.req_enum(body, "action", ("SUSPEND", "REINSTATE", "DEBAR"))
    reason = v.req_str(body, "reason", allow_empty=False)

    developer = domain.get_or_404(db.developers, row_id, "ERR_DEVELOPER_NOT_FOUND")
    status = developer.get("status")

    if action == "SUSPEND":
        if status != "ACTIVE":
            fail("ERR_DEVELOPER_NOT_ACTIVE",
                 "A sponsor in %s cannot be suspended." % status)
        developer["status"] = "SUSPENDED"
        developer["sanction_reason"] = reason
    elif action == "REINSTATE":
        if status != "SUSPENDED":
            fail("ERR_DEVELOPER_NOT_ACTIVE",
                 "A sponsor in %s cannot be reinstated." % status)
        developer["status"] = "ACTIVE"
        developer["sanction_reason"] = None
    else:
        if status not in ("ACTIVE", "SUSPENDED"):
            fail("ERR_DEVELOPER_NOT_ACTIVE",
                 "A sponsor in %s cannot be debarred." % status)
        developer["status"] = "DEBARRED"
        developer["sanction_reason"] = reason
        for project in calc.developer_projects(developer["id"]):
            if project.get("development_status") in ("PLANNING", "FINANCED",
                                                     "UNDER_CONSTRUCTION"):
                project["financing_stalled"] = True
                touch(project)

    touch(developer)
    return object_response(serialize.developer(developer))


@bp.post("/investors")
def create_investor():
    guard("POST /investors")
    body = v.body()
    name = v.req_str(body, "name", allow_empty=False)
    tax_id = v.req_str(body, "tax_id", allow_empty=False)
    investor_type = v.req_enum(body, "investor_type",
                               ("SYNDICATOR", "DIRECT_CORPORATE", "FUND"))
    row = new_row(db.investors, {
        "name": name,
        "tax_id": tax_id,
        "investor_type": investor_type,
        "total_credit_accepted_cents": 0,
    })
    return object_response(serialize.investor(row), 201)


@bp.post("/cap-pools")
def create_cap_pool():
    guard("POST /cap-pools")
    body = v.body()
    program_year = v.req_int(body, "program_year", minimum=1)
    base_cap_cents = v.req_int(body, "base_cap_cents", minimum=1)
    carryforward_cents = v.opt_int(body, "carryforward_cents", minimum=0, default=0)
    row = new_row(db.cap_pools, {
        "program_year": program_year,
        "base_cap_cents": base_cap_cents,
        "carryforward_cents": carryforward_cents,
    })
    return object_response(serialize.cap_pool(row), 201)


@bp.post("/projects")
def create_project():
    caller = guard("POST /projects")
    body = v.body()

    # Ownership (ladder rule 3) outranks payload well-formedness (rule 4).
    raw_developer = body.get("developer_id")
    if isinstance(raw_developer, str) and raw_developer != caller.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "developer_id must equal X-User-ID.")

    developer_id = v.req_id(body, "developer_id")
    name = v.req_str(body, "name", allow_empty=False)
    total_units = v.req_int(body, "total_units", minimum=1)
    total_floor_space_sqft = v.req_int(body, "total_floor_space_sqft", minimum=1)
    land_cost_cents = v.req_int(body, "land_cost_cents", minimum=0)
    depreciable_basis_cents = v.req_int(body, "depreciable_basis_cents", minimum=1)
    set_aside_election = v.req_enum(body, "set_aside_election", calc.SET_ASIDE_ELECTIONS)

    developer = domain.get_or_404(db.developers, developer_id, "ERR_DEVELOPER_NOT_FOUND")
    if developer.get("id") != caller.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "developer_id must equal X-User-ID.")
    if developer.get("status") != "ACTIVE":
        fail("ERR_DEVELOPER_NOT_ACTIVE",
             "Sponsor standing is %s; no development may be filed."
             % developer.get("status"))

    row = new_row(db.projects, {
        "developer_id": developer_id,
        "name": name,
        "total_units": total_units,
        "total_floor_space_sqft": total_floor_space_sqft,
        "land_cost_cents": land_cost_cents,
        "depreciable_basis_cents": depreciable_basis_cents,
        "set_aside_election": set_aside_election,
        "aggregate_basis_cents": land_cost_cents + depreciable_basis_cents,
        "development_status": "PLANNING",
        "compliance_status": "UNRESTRICTED",
        "provisional_fifty_percent_ratio_bps": None,
        "final_fifty_percent_ratio_bps": None,
        "automatic_credit_triggered": False,
        "placed_in_service_date": None,
        "compliance_start_date": None,
        "compliance_end_date": None,
        "extended_use_end_date": None,
        "volume_cap_deferral_count": 0,
        "financing_stalled": False,
    })
    own_project(caller, row)
    touch(developer)
    return object_response(serialize.project(row), 201)
