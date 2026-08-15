"""CDI program endpoints: CRUD, lifecycle, clock advance, CMI snapshots."""
from flask import Blueprint, request

import db
from calc import (
    agreed_indicators,
    applicable_targets,
    round4_dec,
    run_clock_sweep,
    target_unmet,
)
from errors import raise_error
from helpers import (
    dec4,
    get_or_404,
    list_page,
    make_record,
    require_program_active,
    touch,
    validate_weight,
)
from middleware import (
    ALL_ROLES,
    check_known_fields,
    get_json_body,
    require_fields,
    require_roles,
    validate_integer,
    validate_string,
)
from response import success_list, success_object
from serializers import program_out, snapshot_out

bp = Blueprint("programs", __name__)

READ_ROLES = set(ALL_ROLES)
SNAPSHOT_READ_ROLES = {"CDIManager", "CDISpecialist", "HIMCoder", "ComplianceAuditor"}


@bp.route("/api/cdi-programs", methods=["POST"])
def create_program():
    require_roles({"CDIManager"})
    body = get_json_body()
    check_known_fields(body, {"facility_name", "program_code", "baseline_cmi"})
    require_fields(body, ["facility_name", "program_code", "baseline_cmi"])
    facility_name = validate_string(body["facility_name"], "facility_name")
    program_code = validate_string(body["program_code"], "program_code")
    baseline_cmi = validate_weight(body["baseline_cmi"], "baseline_cmi")
    for p in db.programs.values():
        if p["program_code"] == program_code:
            raise_error(
                "ERR_INVALID_REQUEST",
                f"program_code {program_code!r} is already in use",
            )
    program = make_record(db.programs, {
        "facility_name": facility_name,
        "program_code": program_code,
        "baseline_cmi": baseline_cmi,
        "current_period_index": 0,
        "status": "ACTIVE",
    })
    return success_object(program_out(program), status=201)


@bp.route("/api/cdi-programs", methods=["GET"])
def list_programs():
    require_roles(READ_ROLES)
    status = request.args.get("status")
    items = list(db.programs.values())
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = list_page(items)
    return success_list([program_out(p) for p in page], limit, offset, total)


@bp.route("/api/cdi-programs/<programId>", methods=["GET"])
def get_program(programId):
    require_roles(READ_ROLES)
    program = get_or_404(db.programs, programId, "program")
    return success_object(program_out(program))


@bp.route("/api/cdi-programs/<programId>/suspend", methods=["POST"])
def suspend_program(programId):
    require_roles({"CDIManager"})
    program = get_or_404(db.programs, programId, "program")
    get_json_body()
    if program["status"] != "ACTIVE":
        raise_error("ERR_INVALID_STATE", "Only an ACTIVE program can be suspended")
    program["status"] = "SUSPENDED"
    touch(program)
    return success_object(program_out(program))


@bp.route("/api/cdi-programs/<programId>/resume", methods=["POST"])
def resume_program(programId):
    require_roles({"CDIManager"})
    program = get_or_404(db.programs, programId, "program")
    get_json_body()
    if program["status"] != "SUSPENDED":
        raise_error("ERR_INVALID_STATE", "Only a SUSPENDED program can be resumed")
    program["status"] = "ACTIVE"
    touch(program)
    return success_object(program_out(program))


@bp.route("/api/cdi-programs/<programId>/close", methods=["POST"])
def close_program(programId):
    require_roles({"CDIManager"})
    program = get_or_404(db.programs, programId, "program")
    get_json_body()
    if program["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error("ERR_INVALID_STATE", "Only an ACTIVE or SUSPENDED program can be closed")
    for case in db.cases.values():
        if case["cdi_program_id"] == program["id"] and case["status"] in (
            "OPEN", "UNDER_REVIEW", "RECONCILED",
        ):
            raise_error(
                "ERR_OPEN_CASES_REMAIN",
                "Program close blocked by cases still in OPEN/UNDER_REVIEW/RECONCILED",
            )
    program["status"] = "CLOSED"
    touch(program)
    return success_object(program_out(program))


@bp.route("/api/cdi-programs/<programId>/clock/advance", methods=["POST"])
def advance_clock(programId):
    require_roles({"CDIManager", "SystemAdmin"})
    program = get_or_404(db.programs, programId, "program")
    body = get_json_body()
    check_known_fields(body, {"by_periods"})
    require_fields(body, ["by_periods"])
    by_periods = validate_integer(body["by_periods"], "by_periods")
    if by_periods < 1:
        raise_error("ERR_INVALID_REQUEST", "by_periods must be a positive integer")
    program["current_period_index"] += by_periods
    run_clock_sweep(program)
    touch(program)
    return success_object(program_out(program))


@bp.route("/api/cdi-programs/<programId>/cmi-snapshots", methods=["GET"])
def list_program_snapshots(programId):
    require_roles(SNAPSHOT_READ_ROLES)
    get_or_404(db.programs, programId, "program")
    items = [s for s in db.snapshots.values() if s["cdi_program_id"] == programId]
    page, limit, offset, total = list_page(items)
    return success_list([snapshot_out(s) for s in page], limit, offset, total)


@bp.route("/api/cdi-programs/<programId>/cmi-snapshots", methods=["POST"])
def take_snapshot(programId):
    require_roles({"CDIManager", "ComplianceAuditor"})
    program = get_or_404(db.programs, programId, "program")
    get_json_body()
    require_program_active(program)
    as_of = program["current_period_index"]
    included = [
        c for c in db.cases.values()
        if c["cdi_program_id"] == program["id"]
        and c["status"] in ("RECONCILED", "FINAL_CODED", "CLOSED")
        and c["discharge_period"] <= as_of
    ]
    n = len(included)
    if n == 0:
        unadjusted = adjusted = lift = 0.0
        misses = 0
    else:
        unadjusted_d = round4_dec(
            sum(dec4(c["initial_drg_weight"]) for c in included) / n
        )
        adjusted_d = round4_dec(
            sum(dec4(c["working_drg_weight"]) for c in included) / n
        )
        # Ratios are rounded first; only then is the subtraction performed.
        lift_d = round4_dec(adjusted_d - unadjusted_d)
        unadjusted = float(unadjusted_d)
        adjusted = float(adjusted_d)
        lift = float(lift_d)
        misses = 0
        for case in included:
            finalized = case.get("_finalized_period")
            if finalized is None:
                continue
            agreed = agreed_indicators(case)
            for target in applicable_targets(
                program["id"], case["working_drg_code"], finalized
            ):
                if target_unmet(target, case, agreed):
                    misses += 1
                    break
    snapshot = make_record(db.snapshots, {
        "cdi_program_id": program["id"],
        "as_of_period": as_of,
        "case_count": n,
        "unadjusted_cmi": unadjusted,
        "adjusted_cmi": adjusted,
        "cdi_lift": lift,
        "denial_target_misses": misses,
    })
    return success_object(snapshot_out(snapshot), status=201)
