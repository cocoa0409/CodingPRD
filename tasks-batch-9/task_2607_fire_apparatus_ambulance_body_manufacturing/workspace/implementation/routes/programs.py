"""The logical clock and the apparatus program lifecycle (PRD §2.4, §3.1)."""

from flask import Blueprint

import calc
import find
import services
import validate
from db import db, new_row, touch
from errors import ApiError
from middleware import ALL_ROLES, PROGRAM_ADMIN, authorize
from response import created, listing, ok

bp = Blueprint("programs", __name__)

PROGRAM_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED", "CLOSED")
TERMINAL_UNIT_BUILD_STATUSES = ("WARRANTY_ACTIVE", "CANCELLED")


# ==========================================================================
# The logical plant clock
# ==========================================================================


@bp.post("/_clock/set_current_utc")
@authorize(*ALL_ROLES)
def set_clock():
    data = validate.body()
    current_utc = validate.req_dt(data, "current_utc")
    db.set_clock(current_utc)
    return ok({"current_utc": db.clock_raw})


# ==========================================================================
# Apparatus programs
# ==========================================================================


@bp.post("/programs")
@authorize(PROGRAM_ADMIN)
def open_program():
    data = validate.body()
    name = validate.req_str(data, "name", 1, 120)
    agency_name = validate.req_str(data, "agency_name", 1, 120)
    base_year = validate.req_int(data, "base_year", 2020, 2030)
    base_unit_price_cents = validate.req_int(data, "base_unit_price_cents", 1000000)
    escalation = validate.req_num(data, "escalation_index_pct_per_year", 0.0, 15.0)
    max_option_units = validate.req_int(data, "max_option_units", 0, 20)
    contract_ceiling_cents = validate.req_int(data, "contract_ceiling_cents", 0)
    if contract_ceiling_cents < base_unit_price_cents:
        validate.bad(
            "'contract_ceiling_cents' may not be less than 'base_unit_price_cents'."
        )

    row = new_row(
        {
            "name": name,
            "agency_name": agency_name,
            "base_year": base_year,
            "base_unit_price_cents": base_unit_price_cents,
            "escalation_index_pct_per_year": escalation,
            "max_option_units": max_option_units,
            "options_exercised_count": 0,
            "contract_ceiling_cents": contract_ceiling_cents,
            "committed_cents": 0,
            "status": "DRAFT",
            "suspension_reason": None,
        }
    )
    db.programs[row["id"]] = row
    return created(row)


@bp.get("/programs")
@authorize(*ALL_ROLES)
def list_programs():
    limit, offset = validate.pagination()
    status = validate.query_filter("status")
    rows = list(db.programs.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows, limit, offset)


@bp.get("/programs/<program_id>")
@authorize(*ALL_ROLES)
def read_program(program_id):
    return ok(find.program(program_id))


@bp.post("/programs/<program_id>/activate")
@authorize(PROGRAM_ADMIN)
def activate_program(program_id):
    program = find.program(program_id)
    if program["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_PROGRAM_STATE")
    program["status"] = "ACTIVE"
    program["suspension_reason"] = None
    touch(program)
    return ok(program)


@bp.post("/programs/<program_id>/suspend")
@authorize(PROGRAM_ADMIN)
def suspend_program(program_id):
    program = find.program(program_id)
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_PROGRAM_STATE")
    program["status"] = "SUSPENDED"
    program["suspension_reason"] = "MANUAL"
    touch(program)
    return ok(program)


@bp.post("/programs/<program_id>/reactivate")
@authorize(PROGRAM_ADMIN)
def reactivate_program(program_id):
    program = find.program(program_id)
    if program["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_PROGRAM_STATE")
    # Rung 51 — recovery is never automatic, and the original suspension reason
    # is irrelevant: committed money must be back at or under the soft ceiling.
    if int(program["committed_cents"]) > calc.soft_ceiling_cents(program):
        raise ApiError("ERR_SOFT_CEILING_STILL_BREACHED")
    program["status"] = "ACTIVE"
    program["suspension_reason"] = None
    touch(program)
    return ok(program)


@bp.post("/programs/<program_id>/close")
@authorize(PROGRAM_ADMIN)
def close_program(program_id):
    program = find.program(program_id)
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_PROGRAM_STATE")
    # Rung 50 — a genuinely aggregate guard: one unit still in flight blocks it.
    for unit in services.program_units(program["id"]):
        if unit["build_status"] not in TERMINAL_UNIT_BUILD_STATUSES:
            raise ApiError("ERR_UNITS_NOT_TERMINAL")
    program["status"] = "CLOSED"
    touch(program)
    return ok(program)


@bp.post("/programs/<program_id>/ops-run")
@authorize(PROGRAM_ADMIN)
def run_program_sweep(program_id):
    program = find.program(program_id)
    if program["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_PROGRAM_STATE")
    return ok(services.ops_run(program))
