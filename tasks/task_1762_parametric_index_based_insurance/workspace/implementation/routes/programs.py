"""InsuranceProgram endpoints (PRD §3.1)."""

from flask import Blueprint

import db
from errors import (
    err, ERR_INVALID_REQUEST, ERR_PROGRAM_NOT_ACTIVE, ERR_PROGRAM_NOT_SUSPENDED,
    ERR_PROGRAM_NO_ACTIVE_INDEX, ERR_OPEN_CLAIMS_EXIST, ERR_STALE_VERSION,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from routes.common import (
    body, require_fields, require_enum, pagination_params, paginate,
    sorted_by_created, get_program,
)
from services import domain

bp = Blueprint("programs", __name__)

PERIL_TYPES = {"RAINFALL_DEFICIT", "WINDSPEED", "EARTHQUAKE_MAGNITUDE", "TEMPERATURE_EXCESS"}
REG_CLASSES = {"ADMITTED_INSURANCE", "SURPLUS_LINES", "DERIVATIVE_CONTRACT"}


@bp.post("/programs")
def create_program():
    require_roles("ProgramManager")
    data = body()
    require_fields(data, ["program_code", "peril_type", "regulatory_classification",
                          "contract_wording_version", "exposure_limit_cents"])
    require_enum(data, "peril_type", PERIL_TYPES)
    require_enum(data, "regulatory_classification", REG_CLASSES)
    if not isinstance(data["exposure_limit_cents"], int):
        raise err(ERR_INVALID_REQUEST, 400, "exposure_limit_cents must be an integer")
    prog = domain.stamp_new({
        "program_code": data["program_code"],
        "peril_type": data["peril_type"],
        "regulatory_classification": data["regulatory_classification"],
        "contract_wording_version": data["contract_wording_version"],
        "exposure_limit_cents": data["exposure_limit_cents"],
        "gross_written_premium_cents": 0,
        "incurred_claims_cents": 0,
        "ceded_recovery_cents": 0,
        "net_retained_exposure_cents": 0,
        "fraud_alert_count": 0,
        "reporting_epoch": 0,
        "status": "DRAFT",
    })
    db.programs[prog["id"]] = prog
    return success_object(domain.serialize(prog), 201)


@bp.get("/programs")
def list_programs():
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    limit, offset = pagination_params()
    items = sorted_by_created(db.programs.values())
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/<programId>")
def get_one_program(programId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    return success_object(domain.serialize(prog))


@bp.post("/programs/<programId>/activate")
def activate_program(programId):
    require_roles("ProgramManager")
    prog = get_program(programId)
    if prog["status"] != "DRAFT":
        # PRD §3.1: activation moves DRAFT -> ACTIVE; the precondition error for a
        # non-DRAFT program here is the generic state failure. Use ERR_PROGRAM_NOT_ACTIVE
        # only for operations that require ACTIVE. For activate from non-DRAFT we
        # surface ERR_INVALID_STATE.
        from errors import ERR_INVALID_STATE
        raise err(ERR_INVALID_STATE, 409, "Program activation requires DRAFT status")
    has_active_index = any(
        i["program_id"] == prog["id"] and i["status"] == "ACTIVE"
        for i in db.index_definitions.values()
    )
    if not has_active_index:
        raise err(ERR_PROGRAM_NO_ACTIVE_INDEX, 409,
                  "Program activation requires at least one ACTIVE index definition")
    prog["status"] = "ACTIVE"
    domain.touch(prog)
    return success_object(domain.serialize(prog))


@bp.post("/programs/<programId>/suspend")
def suspend_program(programId):
    require_roles("ProgramManager")
    prog = get_program(programId)
    if prog["status"] != "ACTIVE":
        raise err(ERR_PROGRAM_NOT_ACTIVE, 409, "Operation requires program status ACTIVE")
    prog["status"] = "SUSPENDED"
    domain.touch(prog)
    # Cascade: all ACTIVE indexes -> SUSPENDED (each gets its own touch)
    for idx in db.index_definitions.values():
        if idx["program_id"] == prog["id"] and idx["status"] == "ACTIVE":
            idx["status"] = "SUSPENDED"
            domain.touch(idx)
    return success_object(domain.serialize(prog))


@bp.post("/programs/<programId>/resume")
def resume_program(programId):
    require_roles("ProgramManager")
    prog = get_program(programId)
    if prog["status"] != "SUSPENDED":
        raise err(ERR_PROGRAM_NOT_SUSPENDED, 409, "Resume requires program status SUSPENDED")
    prog["status"] = "ACTIVE"
    domain.touch(prog)
    for idx in db.index_definitions.values():
        if idx["program_id"] == prog["id"] and idx["status"] == "SUSPENDED":
            idx["status"] = "ACTIVE"
            domain.touch(idx)
    return success_object(domain.serialize(prog))


@bp.post("/programs/<programId>/close")
def close_program(programId):
    require_roles("ProgramManager")
    prog = get_program(programId)
    data = body()
    require_fields(data, ["expected_program_version"])
    # State check (priority 5) before OCC comparison? PRD §2.8 lists OCC on close;
    # validation order: state (priority 5) precedes business rules. Close requires
    # ACTIVE (state) — surface the state error first.
    if prog["status"] != "ACTIVE":
        raise err(ERR_PROGRAM_NOT_ACTIVE, 409, "Operation requires program status ACTIVE")
    if int(data["expected_program_version"]) != int(prog["version"]):
        raise err(ERR_STALE_VERSION, 412,
                  "OCC: expected_program_version does not match current program.version")
    # No claims in GENERATED/ADJUSTED/APPROVED/FRAUD_HOLD; no disputes OPEN/AWAITING_CUSTOMER
    for c in db.claims.values():
        pol = db.policies.get(c["policy_id"])
        if pol and pol["program_id"] == prog["id"] and c["status"] in (
            "GENERATED", "ADJUSTED", "APPROVED", "FRAUD_HOLD"
        ):
            raise err(ERR_OPEN_CLAIMS_EXIST, 409,
                      "Program close blocked by open claims or disputes")
    for d in db.disputes.values():
        c = db.claims.get(d["claim_id"])
        if not c:
            continue
        pol = db.policies.get(c["policy_id"])
        if pol and pol["program_id"] == prog["id"] and d["status"] in ("OPEN", "AWAITING_CUSTOMER"):
            raise err(ERR_OPEN_CLAIMS_EXIST, 409,
                      "Program close blocked by open claims or disputes")
    prog["status"] = "CLOSED"
    # version increment happens via touch (close increments version by 1, PRD §3.1)
    domain.touch(prog)
    # Cascade: BOUND policies -> EXPIRED (posture unchanged)
    for p in db.policies.values():
        if p["program_id"] == prog["id"] and p["lifecycle_status"] == "BOUND":
            p["lifecycle_status"] = "EXPIRED"
            domain.touch(p)
    # Cascade: ACTIVE treaties -> COMMUTED
    for t in db.treaties.values():
        if t["program_id"] == prog["id"] and t["status"] == "ACTIVE":
            t["status"] = "COMMUTED"
            domain.touch(t)
    # Retention recompute (all BOUND now gone -> 0)
    from services import calc
    calc.recompute_net_retained_exposure(prog)
    return success_object(domain.serialize(prog))


@bp.post("/programs/<programId>/advance-reporting-epoch")
def advance_epoch(programId):
    require_roles("ProgramManager")
    prog = get_program(programId)
    prog["reporting_epoch"] = int(prog["reporting_epoch"]) + 1
    domain.touch(prog)  # increments version by 1 (PRD §3.1)
    return success_object(domain.serialize(prog))


@bp.get("/programs/<programId>/financial-summary")
def financial_summary(programId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    return success_object(domain.serialize(prog))
