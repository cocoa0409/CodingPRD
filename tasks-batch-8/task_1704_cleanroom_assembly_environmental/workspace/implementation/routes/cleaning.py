"""Cleaning validation programs and cycles (PRD 3.7)."""

from flask import Blueprint, request

from db import store, new_record, mutate, pub
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_PROGRAM_ALREADY_ACTIVE,
    ERR_CYCLE_NOT_RECORDED,
    ERR_CYCLE_RESULT_FAIL,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_role, body, QA, ET
from response import ok, paginate
from services.core import req_string, opt_int, req_enum, touch_room

bp = Blueprint("cleaning", __name__)
READERS = [QA, ET]
CYCLE_RESULTS = {"PASS", "FAIL"}


def load_program(program_id):
    program = store.cleaning_programs.get(program_id)
    if program is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "cleaning program %s not found" % program_id)
    return program


def load_cycle(cycle_id):
    cycle = store.cleaning_cycles.get(cycle_id)
    if cycle is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "cleaning cycle %s not found" % cycle_id)
    return cycle


def apply_cycle_failure(program):
    """FAIL-recorded or REJECTED cycle: reset counter, force re-validation."""
    program["consecutive_pass_count"] = 0
    if program["status"] == "VALIDATED":
        program["status"] = "RE_VALIDATION_REQUIRED"
    mutate(program)


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------


@bp.post("/cleanroom/cleaning-programs")
def create_program():
    require_role([QA])
    payload = body()
    cleanroom_id = payload.get("cleanroom_id")
    if not isinstance(cleanroom_id, str) \
            or store.rooms.get(cleanroom_id) is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "cleanroom %s not found" % cleanroom_id)
    touch_room(store.rooms[cleanroom_id])
    method_code = req_string(payload, "method_code")
    required = opt_int(payload, "required_consecutive_passes", minimum=1)
    program = new_record({
        "cleanroom_id": cleanroom_id,
        "method_code": method_code,
        "required_consecutive_passes": required if required is not None else 3,
        "consecutive_pass_count": 0,
        "status": "DRAFT",
    })
    store.cleaning_programs[program["id"]] = program
    return ok(pub(program), 201)


@bp.get("/cleanroom/cleaning-programs")
def list_programs():
    require_role(READERS)
    records = list(store.cleaning_programs.values())
    cleanroom_id = request.args.get("cleanroom_id")
    status = request.args.get("status")
    if cleanroom_id is not None:
        records = [p for p in records if p["cleanroom_id"] == cleanroom_id]
    if status is not None:
        records = [p for p in records if p["status"] == status]
    return paginate(records, request.args)


@bp.get("/cleanroom/cleaning-programs/<programId>")
def get_program(programId):
    require_role(READERS)
    return ok(pub(load_program(programId)))


@bp.post("/cleanroom/cleaning-programs/<programId>/activate")
def activate_program(programId):
    require_role([QA])
    program = load_program(programId)
    if program["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "program is not DRAFT")
    conflict = any(
        p["cleanroom_id"] == program["cleanroom_id"]
        and p["id"] != program["id"]
        and p["status"] in ("ACTIVE", "VALIDATED")
        for p in store.cleaning_programs.values()
    )
    if conflict:
        raise ApiError(ERR_PROGRAM_ALREADY_ACTIVE, 409,
                       "another program for this room is ACTIVE or VALIDATED")
    program["status"] = "ACTIVE"
    mutate(program)
    return ok(pub(program))


# ---------------------------------------------------------------------------
# Cycles
# ---------------------------------------------------------------------------


@bp.post("/cleanroom/cleaning-programs/<programId>/cycles")
def create_cycle(programId):
    uid = require_role([ET])
    program = load_program(programId)
    payload = body()
    result = req_enum(payload, "result", CYCLE_RESULTS)

    if result == "FAIL":
        # FAIL cycles never wait for review: recorded directly as REJECTED,
        # program counter resets, VALIDATED drops to RE_VALIDATION_REQUIRED.
        cycle = new_record({
            "program_id": program["id"],
            "performed_by_user_id": uid,
            "result": "FAIL",
            "verified_by_user_id": None,
            "status": "REJECTED",
        })
        store.cleaning_cycles[cycle["id"]] = cycle
        apply_cycle_failure(program)
        return ok(pub(cycle), 201)

    cycle = new_record({
        "program_id": program["id"],
        "performed_by_user_id": uid,
        "result": "PASS",
        "verified_by_user_id": None,
        "status": "RECORDED",
    })
    store.cleaning_cycles[cycle["id"]] = cycle
    return ok(pub(cycle), 201)


@bp.get("/cleanroom/cleaning-programs/<programId>/cycles")
def list_cycles(programId):
    require_role(READERS)
    program = load_program(programId)
    records = [c for c in store.cleaning_cycles.values()
               if c["program_id"] == program["id"]]
    return paginate(records, request.args)


@bp.get("/cleanroom/cleaning-cycles/<cycleId>")
def get_cycle(cycleId):
    require_role(READERS)
    return ok(pub(load_cycle(cycleId)))


@bp.post("/cleanroom/cleaning-cycles/<cycleId>/verify")
def verify_cycle(cycleId):
    uid = require_role([QA])
    cycle = load_cycle(cycleId)
    if cycle["status"] != "RECORDED":
        raise ApiError(ERR_CYCLE_NOT_RECORDED, 409, "cycle is not RECORDED")
    if cycle["result"] != "PASS":
        raise ApiError(ERR_CYCLE_RESULT_FAIL, 409, "cycle result is FAIL")
    if uid == cycle["performed_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "verifier must differ from the cycle performer")
    cycle["verified_by_user_id"] = uid
    cycle["status"] = "VERIFIED"
    mutate(cycle)

    program = store.cleaning_programs[cycle["program_id"]]
    program["consecutive_pass_count"] += 1
    if program["consecutive_pass_count"] >= program["required_consecutive_passes"] \
            and program["status"] in ("ACTIVE", "RE_VALIDATION_REQUIRED"):
        program["status"] = "VALIDATED"
    mutate(program)
    return ok(pub(cycle))


@bp.post("/cleanroom/cleaning-cycles/<cycleId>/reject")
def reject_cycle(cycleId):
    require_role([QA])
    cycle = load_cycle(cycleId)
    if cycle["status"] != "RECORDED":
        raise ApiError(ERR_CYCLE_NOT_RECORDED, 409, "cycle is not RECORDED")
    cycle["status"] = "REJECTED"
    mutate(cycle)
    program = store.cleaning_programs[cycle["program_id"]]
    apply_cycle_failure(program)
    return ok(pub(cycle))
