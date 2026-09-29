"""Crop-year programs: opening, harvest reporting (cascade A) and settlement."""

from flask import Blueprint, request

from calc import contracts_of_program
from cascades import run_reallocation
from db import db, new_entity, now, set_dt, touch
from errors import ApiError, bad_request
from middleware import ALL_ROLES, require
from response import array_response, object_response
from serialize import program_out
from util import D
from validation import (
    body,
    f_dec,
    f_dt,
    f_int,
    f_str,
    must_exist,
    paginate,
    pagination,
)

bp = Blueprint("programs", __name__)


@bp.post("/crop-year-programs")
def create_program():
    require(("AllocationManager", "PlatformAdmin"))
    payload = body()
    crop_year = f_int(payload, "crop_year", required=True, minimum=2020, maximum=2100)
    open_date, open_raw = f_dt(payload, "contract_open_date", required=True)
    due_date, due_raw = f_dt(payload, "harvest_report_due_date", required=True)

    for existing in db.programs.values():
        if existing["crop_year"] == crop_year:
            raise ApiError(
                "ERR_DUPLICATE_CROP_YEAR", "A program for that crop year already exists"
            )

    program = new_entity()
    program.update(
        {
            "crop_year": crop_year,
            "status": "OPEN",
            "harvest_yield_pct": None,
            "total_contracted_lbs": D(0),
            "allocatable_pool_lbs": D(0),
            "unallocated_pool_lbs": D(0),
            "harvest_reported_at": None,
        }
    )
    set_dt(program, "contract_open_date", open_date, open_raw)
    set_dt(program, "harvest_report_due_date", due_date, due_raw)
    db.programs[program["id"]] = program
    return object_response(program_out(program), 201)


@bp.get("/crop-year-programs/<program_id>")
def get_program(program_id):
    require(ALL_ROLES)
    program = must_exist("programs", program_id)
    return object_response(program_out(program))


@bp.get("/crop-year-programs")
def list_programs():
    require(ALL_ROLES)
    limit, offset = pagination()
    status = request.args.get("status")
    crop_year = request.args.get("crop_year")
    if crop_year is not None:
        try:
            crop_year = int(str(crop_year).strip())
        except (TypeError, ValueError):
            raise bad_request("crop_year must be an integer")
    items = list(db.programs.values())
    if status:
        items = [p for p in items if p["status"] == status]
    if crop_year is not None:
        items = [p for p in items if p["crop_year"] == crop_year]
    items.sort(key=lambda p: p["crop_year"], reverse=True)
    page = paginate(items, limit, offset)
    return array_response(
        [program_out(p) for p in page], len(items), limit, offset
    )


@bp.post("/crop-year-programs/<program_id>/report-harvest")
def report_harvest(program_id):
    require(("AllocationManager",))
    payload = body()
    yield_pct = f_dec(
        payload, "harvest_yield_pct", required=True, scale=2, minimum=0, maximum=200
    )
    f_str(payload, "reported_note", required=False, max_len=1000)

    program = must_exist("programs", program_id)
    if program["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_PROGRAM_STATE",
            "Harvest may only be reported from an OPEN program",
        )
    program["harvest_yield_pct"] = yield_pct
    set_dt(program, "harvest_reported_at", now())
    program["status"] = "HARVEST_REPORTED"
    run_reallocation(program, yield_pct)
    touch(program)
    return object_response(program_out(program))


@bp.post("/crop-year-programs/<program_id>/settle")
def settle_program(program_id):
    require(("AllocationManager",))
    payload = body()
    f_str(payload, "settlement_note", required=False, max_len=1000)

    program = must_exist("programs", program_id)
    if program["status"] != "HARVEST_REPORTED":
        raise ApiError(
            "ERR_INVALID_PROGRAM_STATE",
            "Only a HARVEST_REPORTED program may be settled",
        )
    for contract in contracts_of_program(program["id"]):
        if contract["status"] == "CARRY_FORWARD_PENDING":
            raise ApiError(
                "ERR_INVALID_PROGRAM_STATE",
                "An undecided carry-forward request blocks settlement",
            )
    program["status"] = "SETTLED"
    touch(program)
    return object_response(program_out(program))
