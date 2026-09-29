"""Unit designation and redesignation (PRD 3.2)."""

from flask import Blueprint

import calc
import domain
import serialize
import validation as v
from auth import guard, own_project
from envelope import object_response
from errors import fail
from store import db, new_row, touch

bp = Blueprint("units", __name__)

DESIGNATIONS = ("RESTRICTED", "MARKET", "EMPLOYEE_UNIT")


def _check_ami(project, designation, ami_percent):
    """Ladder rule 33 -- ERR_AMI_PERCENT_NOT_ALLOWED in all three directions."""
    if designation != "RESTRICTED":
        if ami_percent is not None:
            fail("ERR_AMI_PERCENT_NOT_ALLOWED",
                 "ami_percent must be omitted for a %s unit." % designation)
        return
    if ami_percent is None:
        fail("ERR_AMI_PERCENT_NOT_ALLOWED",
             "ami_percent is required for a RESTRICTED unit.")
    if ami_percent not in calc.ALLOWED_AMI_PERCENTS:
        fail("ERR_AMI_PERCENT_NOT_ALLOWED",
             "ami_percent %s is not an allowed band." % ami_percent)
    if ami_percent > 60 and project.get("set_aside_election") != "AVG_INCOME":
        fail("ERR_AMI_PERCENT_NOT_ALLOWED",
             "A band above 60 requires an AVG_INCOME election.")


@bp.post("/unit-restrictions")
def create_unit():
    caller = guard("POST /unit-restrictions")
    body = v.body()
    own_project(caller, domain.soft_get(db.projects, body.get("project_id")))

    project_id = v.req_id(body, "project_id")
    unit_number = v.req_str(body, "unit_number", allow_empty=False)
    bedroom_count = v.req_int(body, "bedroom_count", minimum=0)
    floor_space_sqft = v.req_int(body, "floor_space_sqft", minimum=1)
    designation = v.req_enum(body, "designation", DESIGNATIONS)
    ami_percent = v.opt_int(body, "ami_percent")
    utility_allowance_cents = v.req_int(body, "utility_allowance_cents", minimum=0)
    market_rent_cents = v.req_int(body, "market_rent_cents", minimum=1)

    project = domain.get_or_404(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    own_project(caller, project)

    existing = calc.project_units(project_id)
    if any(u.get("unit_number") == unit_number for u in existing):
        fail("ERR_DUPLICATE_UNIT_NUMBER",
             "unit_number '%s' already exists in this development." % unit_number)
    if len(existing) + 1 > (project.get("total_units") or 0):
        fail("ERR_UNIT_COUNT_EXCEEDS_TOTAL",
             "The development already carries its full complement of designated units.")

    _check_ami(project, designation, ami_percent)

    row = new_row(db.units, {
        "project_id": project_id,
        "unit_number": unit_number,
        "bedroom_count": bedroom_count,
        "floor_space_sqft": floor_space_sqft,
        "designation": designation,
        "ami_percent": ami_percent if designation == "RESTRICTED" else None,
        "utility_allowance_cents": utility_allowance_cents,
        "market_rent_cents": market_rent_cents,
        "restricted_rent_cents": None,
        "status": "PROPOSED",
    })
    domain.refresh_unit_rent(row, project)
    domain.rederive_project_from_units(project)
    return object_response(serialize.unit(row), 201)


@bp.patch("/unit-restrictions/<row_id>")
def patch_unit(row_id):
    caller = guard("PATCH /unit-restrictions/{id}")
    unit = domain.soft_get(db.units, row_id)
    own_project(caller, domain.project_of_row(unit))

    body = v.body()
    designation = v.req_enum(body, "designation", DESIGNATIONS)
    ami_supplied = body.get("ami_percent") is not None
    ami_percent = v.opt_int(body, "ami_percent")
    utility_allowance_cents = v.opt_int(body, "utility_allowance_cents", minimum=0)
    market_rent_cents = v.opt_int(body, "market_rent_cents", minimum=1)

    unit = domain.get_or_404(db.units, row_id, "ERR_UNIT_RESTRICTION_NOT_FOUND")
    project = domain.project_of_row(unit)
    own_project(caller, project)

    if unit.get("status") not in ("PROPOSED", "ACTIVE"):
        fail("ERR_UNIT_RESTRICTION_STATE_INVALID",
             "A unit in %s can no longer be redesignated." % unit.get("status"))

    if designation == "RESTRICTED":
        effective_ami = ami_percent if ami_supplied else unit.get("ami_percent")
    else:
        effective_ami = ami_percent if ami_supplied else None
    _check_ami(project, designation, effective_ami)

    unit["designation"] = designation
    unit["ami_percent"] = effective_ami if designation == "RESTRICTED" else None
    if utility_allowance_cents is not None:
        unit["utility_allowance_cents"] = utility_allowance_cents
    if market_rent_cents is not None:
        unit["market_rent_cents"] = market_rent_cents
    domain.refresh_unit_rent(unit, project)
    touch(unit)
    domain.rederive_project_from_units(project)
    return object_response(serialize.unit(unit))
