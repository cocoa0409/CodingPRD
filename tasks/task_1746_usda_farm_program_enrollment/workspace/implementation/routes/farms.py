"""Farm endpoints (PRD §3.1, §3.6)."""

from flask import Blueprint, request

import db
from errors import invalid_state, invalid_request, not_found
from middleware import require_roles, ALL_ROLES
from response import success_object, paginate
from services.helpers import (
    get_farm_or_404, recompute_farm_base_acres, has_open_appeal_or_disaster,
)
from validation import (
    body, require_string, require_int, optional_enum,
)

bp = Blueprint("farms", __name__)

FARM_CREATE_ROLES = ["CountySpecialist"]


@bp.post("/fsa/farms")
def create_farm():
    require_roles(FARM_CREATE_ROLES)
    data = body()
    farm_number = require_string(data, "farm_number")
    county_code = require_string(data, "county_code")
    program_year = require_int(data, "program_year")
    indicator = optional_enum(data, "arc_co_ic_indicator", ("COUNTY", "INDIVIDUAL"), "COUNTY")

    farm = db.common_fields()
    farm.update({
        "farm_number": farm_number,
        "county_code": county_code,
        "program_year": program_year,
        "farm_status": "ACTIVE",
        "total_base_acres": 0.0,
        "arc_co_ic_indicator": indicator,
    })
    db.farms[farm["id"]] = farm
    return success_object(farm, 201)


@bp.get("/fsa/farms/<farm_id>")
def get_farm(farm_id):
    require_roles(ALL_ROLES)
    farm = get_farm_or_404(farm_id)
    return success_object(farm)


@bp.get("/fsa/farms")
def list_farms():
    require_roles(ALL_ROLES)
    county_code = request.args.get("county_code")
    program_year = request.args.get("program_year")
    items = list(db.farms.values())
    if county_code is not None:
        items = [f for f in items if f["county_code"] == county_code]
    if program_year is not None:
        try:
            py = int(program_year)
        except ValueError:
            raise invalid_request("program_year must be an integer")
        items = [f for f in items if f["program_year"] == py]
    items.sort(key=lambda f: f["created_at"])
    return paginate(items, request.args)


@bp.post("/fsa/farms/<farm_id>/retire")
def retire_farm(farm_id):
    require_roles(["CountyExecutiveDirector"])
    farm = get_farm_or_404(farm_id)
    if farm["farm_status"] != "ACTIVE":
        raise invalid_state("Farm is not ACTIVE")
    # All enrollments in DRAFT, VOID, or PAYMENT_ISSUED.
    for e in db.enrollments.values():
        if e["farm_id"] == farm_id and e["enrollment_status"] not in (
                "DRAFT", "VOID", "PAYMENT_ISSUED"):
            raise invalid_state(
                "All enrollments on the farm must be in DRAFT, VOID, or PAYMENT_ISSUED")
    if has_open_appeal_or_disaster(farm_id):
        raise invalid_state("Farm has an open appeal or disaster application")
    farm["farm_status"] = "RETIRED"
    db.touch(farm)
    # Side effect: all ACTIVE memberships -> REMOVED.
    for m in db.memberships.values():
        if m["farm_id"] == farm_id and m["membership_status"] == "ACTIVE":
            m["membership_status"] = "REMOVED"
            db.touch(m)
    return success_object(farm)
