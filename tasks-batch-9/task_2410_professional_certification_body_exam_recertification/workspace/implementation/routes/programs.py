"""CertificationProgram endpoints (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import serialize
from db import DB, mark_created, new_record, ordered, touch
from dispatch import api
from errors import ApiError
from middleware import (
    ROLE_ELIGIBILITY_REVIEWER,
    ROLE_ETHICS_OFFICER,
    ROLE_EXAM_OPERATIONS,
    ROLE_ITEM_SPECIALIST,
    ROLE_PANELIST,
    ROLE_PROGRAM_ADMIN,
    ROLE_PSYCHOMETRICIAN,
    authenticate,
    ensure_body,
    opt_enum,
    opt_int,
    opt_num,
    opt_str,
    peek_body,
    present,
    req_int,
    req_str,
    req_str_list,
)
from response import apply_filters, created_response, object_response, paginate, read_pagination
from services import derive, lookup

bp = Blueprint("programs", __name__)

EDUCATION_CREDENTIALS = ("DIPLOMA", "ASSOCIATE", "BACHELOR", "MASTER", "DOCTORATE")
STAT_BASES = ("POOLED", "OPERATIONAL_ONLY")
ACCRUAL_BASES = ("STRICT_CYCLE", "CARRYOVER_ALLOWED")

# name -> (reader, default)
INT_KNOBS = {
    "min_responses_for_stats": 30,
    "form_retirement_tolerance_pct": 10,
    "min_panelists": 5,
    "panel_trim_count": 1,
    "education_recency_years": 10,
    "min_experience_months": 24,
    "eligibility_valid_days": 365,
    "exam_fee_cents": 45000,
    "max_attempts_per_cycle": 3,
    "retake_wait_days": 45,
    "cycle_length_months": 36,
    "recert_grace_days": 90,
}
NUM_KNOBS = {
    "min_discrimination": Decimal("0.15"),
    "min_p_value": Decimal("0.20"),
    "max_p_value": Decimal("0.95"),
    "cut_score_sem_multiplier": Decimal("0.5"),
    "required_ceu_credits": Decimal("60"),
    "ceu_carryover_max_credits": Decimal("10"),
}


def _read_domain_specs(body):
    """Layer 7: structural shape of the blueprint rows."""
    if not present(body, "domain_specs"):
        raise ApiError("ERR_INVALID_REQUEST")
    rows = body["domain_specs"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise ApiError("ERR_INVALID_REQUEST")
    specs = []
    for row in rows:
        if not isinstance(row, dict):
            raise ApiError("ERR_INVALID_REQUEST")
        code = req_str(row, "domain_code")
        weight = req_int(row, "weight_pct", minimum=0)
        minimum = req_int(row, "min_operational_items", minimum=0)
        specs.append({
            "domain_code": code,
            "weight_pct": weight,
            "min_operational_items": minimum,
        })
    return specs


def _check_blueprint_weights(specs):
    """Layer 8: weights sum to exactly 100 over unique domain codes."""
    codes = [spec["domain_code"] for spec in specs]
    if len(set(codes)) != len(codes):
        raise ApiError("ERR_BLUEPRINT_WEIGHTS_INVALID")
    if sum(spec["weight_pct"] for spec in specs) != 100:
        raise ApiError("ERR_BLUEPRINT_WEIGHTS_INVALID")


def _read_credential_code(body):
    code = req_str(body, "credential_code")
    if not 2 <= len(code) <= 12:
        raise ApiError("ERR_INVALID_REQUEST")
    if not code.isalnum() or code != code.upper():
        raise ApiError("ERR_INVALID_REQUEST")
    return code


def _read_accepted_credentials(body):
    values = req_str_list(body, "accepted_education_credentials", minimum_length=1)
    for value in values:
        if value not in EDUCATION_CREDENTIALS:
            raise ApiError("ERR_INVALID_REQUEST")
    return values


@bp.post("/programs")
@api
def create_program():
    authenticate([ROLE_PROGRAM_ADMIN])
    body = ensure_body(peek_body())

    name = req_str(body, "name")
    credential_code = _read_credential_code(body)
    jta_version = req_str(body, "jta_version")
    domain_specs = _read_domain_specs(body)
    form_length = req_int(body, "form_length", minimum=1)
    accepted = _read_accepted_credentials(body)

    knobs = {
        "psychometric_stat_basis": opt_enum(
            body, "psychometric_stat_basis", STAT_BASES, "OPERATIONAL_ONLY"),
        "ceu_credit_accrual_basis": opt_enum(
            body, "ceu_credit_accrual_basis", ACCRUAL_BASES, "STRICT_CYCLE"),
        "audit_every_nth": opt_int(body, "audit_every_nth", 3, minimum=1),
    }
    for knob, default in INT_KNOBS.items():
        knobs[knob] = opt_int(body, knob, default, minimum=0)
    for knob, default in NUM_KNOBS.items():
        knobs[knob] = opt_num(body, knob, default, minimum=0)

    _check_blueprint_weights(domain_specs)

    # Layer 10: credential_code is unique among DRAFT and ACTIVE programs.
    for existing in DB.programs.values():
        if (existing["credential_code"] == credential_code
                and existing["status"] in ("DRAFT", "ACTIVE")):
            raise ApiError("ERR_CREDENTIAL_CODE_TAKEN")

    program = new_record(
        name=name,
        credential_code=credential_code,
        jta_version=jta_version,
        domain_specs=domain_specs,
        form_length=form_length,
        accepted_education_credentials=accepted,
        status="DRAFT",
        operational_item_count=0,
        deficient_domain_codes=[],
        blueprint_posture="COMPLETE",
        verified_application_counter=0,
        certificants_issued_count=0,
        **knobs
    )
    mark_created(program)
    DB.programs[program["id"]] = program
    derive.recompute_blueprint_posture(program, bump=False)
    return created_response(serialize.program(program))


@bp.get("/programs/<program_id>")
@api
def read_program(program_id):
    authenticate([ROLE_PROGRAM_ADMIN, ROLE_ITEM_SPECIALIST, ROLE_PSYCHOMETRICIAN,
                  ROLE_PANELIST, ROLE_ELIGIBILITY_REVIEWER, ROLE_EXAM_OPERATIONS,
                  ROLE_ETHICS_OFFICER])
    return object_response(serialize.program(lookup.program(program_id)))


@bp.get("/programs")
@api
def list_programs():
    authenticate([ROLE_PROGRAM_ADMIN, ROLE_ITEM_SPECIALIST, ROLE_PSYCHOMETRICIAN,
                  ROLE_ELIGIBILITY_REVIEWER, ROLE_EXAM_OPERATIONS, ROLE_ETHICS_OFFICER])
    limit, offset = read_pagination()
    rows = ordered(DB.programs.values())
    rows = apply_filters(rows, {
        "credential_code": "credential_code",
        "status": "status",
        "blueprint_posture": "blueprint_posture",
    })
    return paginate(rows, serialize.program, limit, offset)


@bp.post("/programs/<program_id>/activate")
@api
def activate_program(program_id):
    authenticate([ROLE_PROGRAM_ADMIN])
    program = lookup.program(program_id)
    body = ensure_body(peek_body())
    opt_str(body, "activation_note")

    # Layer 8 sits above layer 12: the blueprint is re-checked before the state.
    _check_blueprint_weights(program["domain_specs"])

    if program["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    program["status"] = "ACTIVE"
    touch(program)

    # Activation supersedes the incumbent holder of the same credential_code.
    for other in ordered(DB.programs.values()):
        if other["id"] == program["id"]:
            continue
        if (other["credential_code"] == program["credential_code"]
                and other["status"] == "ACTIVE"):
            other["status"] = "SUPERSEDED"
            touch(other)

    derive.recompute_blueprint_posture(program)
    return object_response(serialize.program(program))


@bp.get("/programs/<program_id>/items")
@api
def list_program_items(program_id):
    authenticate([ROLE_PROGRAM_ADMIN, ROLE_ITEM_SPECIALIST, ROLE_PSYCHOMETRICIAN])
    program = lookup.program(program_id)
    limit, offset = read_pagination()
    rows = derive.items_of_program(program["id"])
    rows = apply_filters(rows, {
        "domain_code": "domain_code",
        "status": "status",
        "flag_reason": "flag_reason",
    })
    return paginate(rows, serialize.item, limit, offset)


@bp.get("/programs/<program_id>/forms")
@api
def list_program_forms(program_id):
    authenticate([ROLE_PROGRAM_ADMIN, ROLE_PSYCHOMETRICIAN, ROLE_EXAM_OPERATIONS])
    program = lookup.program(program_id)
    limit, offset = read_pagination()
    rows = derive.forms_of_program(program["id"])
    rows = apply_filters(rows, {"status": "status"})
    return paginate(rows, serialize.form, limit, offset)
