"""Affiliate programs, the subsidy pool, and the waitlist selector."""
from decimal import Decimal

from flask import Blueprint

import calc
import derive
from common import API, get_program, listing, created, okay, match
from envelope import array_response
from errors import fail
from payload import body, qenum, qstring, vint, vdecimal, venum, vstring
from rbac import auth
from store import bump, db, stamp

bp = Blueprint("programs", __name__)

READ_ROLES = ("ProgramAdmin", "FamilyServicesCoordinator", "MortgageOfficer",
              "ConstructionManager", "SelectionCommitteeMember")


@bp.post(API + "/programs")
def create_program():
    auth("ProgramAdmin")
    data = body()
    name = vstring(data, "affiliate_name", 1, 120, required=True)
    area = vstring(data, "service_area_code", 2, 10, required=True)
    if area != area.upper():
        fail("ERR_VALIDATION", "service_area_code must be uppercase.")
    median = vint(data, "ami_median_income_cents", minimum=1000000, required=True)
    base_hours = vdecimal(data, "sweat_equity_base_hours_required",
                          minimum=0, maximum=500, default=None)
    quorum = vint(data, "committee_quorum", minimum=2, maximum=9, default=None)
    pool = vint(data, "subsidy_pool_cents", minimum=0, required=True)

    for existing in db.programs.values():
        if existing["affiliate_name"] == name:
            fail("ERR_VALIDATION", "affiliate_name must be unique across programs.")

    row = {
        "affiliate_name": name,
        "service_area_code": area,
        "ami_median_income_cents": median,
        "sweat_equity_base_hours_required": base_hours if base_hours is not None
        else Decimal("300.00"),
        "committee_quorum": quorum if quorum is not None else 3,
        "subsidy_pool_cents": pool,
        "subsidy_committed_cents": 0,
        "subsidy_disbursed_cents": 0,
        "subsidy_available_cents": pool,
        "donated_material_fmv_cents": 0,
        "households_served_count": 0,
        "program_posture": "OPEN",
        "status": "ACTIVE",
    }
    stamp(row)
    db.programs[row["id"]] = row
    return created(derive.public_program(row))


@bp.get(API + "/programs")
def list_programs():
    auth(*READ_ROLES)
    area = qstring("service_area_code")
    status = qenum("status", ("ACTIVE", "SUSPENDED"))
    rows = [r for r in db.programs.values()
            if match(r, "service_area_code", area) and match(r, "status", status)]
    return listing(rows, derive.public_program)


@bp.get(API + "/programs/<pid>")
def read_program(pid):
    auth(*READ_ROLES)
    program = get_program(pid)
    return okay(derive.public_program(program))


@bp.post(API + "/programs/<pid>/subsidy-pool-adjustments")
def adjust_pool(pid):
    auth("ProgramAdmin")
    program = get_program(pid)
    data = body()
    action = venum(data, "action",
                   ("TOP_UP", "REDUCE", "SUSPEND_PROGRAM", "RESUME_PROGRAM"),
                   required=True)
    delta = vint(data, "delta_cents", minimum=0, default=None)
    expected = vint(data, "expected_program_version", required=True)
    vstring(data, "memo", 1, None, default=None, nullable=True)

    if expected != program.get("version"):
        fail("ERR_STALE_PROGRAM_VERSION")

    if action == "SUSPEND_PROGRAM":
        if program.get("status") != "ACTIVE":
            fail("ERR_TRANSITION_NOT_ALLOWED")
        program["status"] = "SUSPENDED"
    elif action == "RESUME_PROGRAM":
        if program.get("status") != "SUSPENDED":
            fail("ERR_TRANSITION_NOT_ALLOWED")
        program["status"] = "ACTIVE"
    elif action == "TOP_UP":
        program["subsidy_pool_cents"] = program["subsidy_pool_cents"] + (delta or 0)
    else:
        ledger = derive.program_ledger(program)
        target = program["subsidy_pool_cents"] - (delta or 0)
        obligations = ledger["subsidy_committed_cents"] + ledger["subsidy_disbursed_cents"]
        if target < obligations:
            fail("ERR_POOL_BELOW_OBLIGATIONS")
        program["subsidy_pool_cents"] = target

    derive.refresh_program(program)
    bump(program)
    return okay(derive.public_program(program))


@bp.post(API + "/programs/<pid>/waitlist-promotions")
def promote_waitlist(pid):
    auth("ProgramAdmin")
    program = get_program(pid)
    data = body()
    promote_count = vint(data, "promote_count", minimum=1, maximum=10, required=True)

    pool = calc.waitlist_pool(program)
    if not pool:
        fail("ERR_NO_ELIGIBLE_WAITLIST_HOUSEHOLD")
    capacity = calc.ready_site_capacity(program)
    if capacity == 0:
        fail("ERR_NO_READY_SITE_CAPACITY")

    count = min(promote_count, capacity, len(pool))
    promoted = []
    for household in pool[:count]:
        household["selection_status"] = "SELECTED"
        bump(household)
        promoted.append(derive.public_household(household))
    return array_response(promoted)
