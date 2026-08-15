"""Program proposal and the carrier-driven lifecycle (PRD sections 3.2, 3.8)."""
from flask import Blueprint, request

import serialize
from db import STORE, new_entity, touch
from errors import (
    raise_err, ERR_INVALID_STATE, ERR_PROGRAM_TERMINAL,
    ERR_PROGRAM_HAS_ACTIVE_POLICIES, ERR_OPEN_CLAIMS_EXIST,
    ERR_UNACCEPTED_BORDEREAUX, ERR_TRUST_NOT_ZERO,
)
from middleware import require_roles, require_carrier_owner, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, filter_query
from services import cascades
from validation import (
    get_body, req_str, req_enum, req_str_list, req_datetime, req_int_pos,
    req_int_nonneg, req_number, fk_or_404,
)
from errors import ERR_NOT_FOUND

bp = Blueprint("programs", __name__)

LINE_OF_BUSINESS = {
    "COMMERCIAL_AUTO", "GENERAL_LIABILITY", "PROPERTY",
    "WORKERS_COMPENSATION", "PROFESSIONAL_LIABILITY",
}
TERMINAL_PROGRAM_STATUSES = ("TERMINATED", "DECLINED")
OPEN_CLAIM_STATUSES = ("REPORTED", "UNDER_REVIEW", "REFERRED", "APPROVED", "REOPENED")
ACTIVE_POLICY_STATUSES = ("QUOTED", "BOUND", "ISSUED", "PENDING_CANCELLATION")
OPEN_BORDEREAU_STATUSES = ("DRAFT", "SUBMITTED", "REJECTED")


def require_program_not_terminal(program):
    """Terminal programs reject child creation and further transitions; this
    check is always evaluated before any merely-not-active check."""
    if program["status"] in TERMINAL_PROGRAM_STATUSES:
        raise_err(ERR_PROGRAM_TERMINAL, "Program is %s; no child creation or transition is allowed." % program["status"])


def _carrier_scoped_program(programId):
    """Role + existence + carrier ownership, in validation-priority order."""
    require_roles("CarrierUnderwriter")
    program = get_or_404(STORE.programs, programId, "Program")
    require_carrier_owner(program)
    return program


@bp.post("/mga/programs")
def create_program():
    require_roles("MGAUnderwriter")
    body = get_body()
    # Stage 3: body-carried FK existence before remaining well-formedness.
    fk_or_404(STORE.carriers, body, "carrier_id", "Carrier", ERR_NOT_FOUND)
    carrier_id = req_str(body, "carrier_id")
    name = req_str(body, "name")
    line_of_business = req_enum(body, "line_of_business", LINE_OF_BUSINESS)
    states_covered = req_str_list(body, "states_covered")
    inception_date = req_datetime(body, "inception_date")
    aggregate_limit_cents = req_int_pos(body, "aggregate_limit_cents")
    commission_rate_pct = req_number(body, "commission_rate_pct")
    corrective_threshold_pct = req_int_nonneg(body, "corrective_threshold_pct")
    termination_threshold_pct = req_int_nonneg(body, "termination_threshold_pct")
    min_trust_balance_cents = req_int_nonneg(body, "min_trust_balance_cents")
    min_earned_premium_for_ratio_cents = req_int_nonneg(body, "min_earned_premium_for_ratio_cents")
    p = new_entity()
    p.update({
        "carrier_id": carrier_id,
        "name": name,
        "line_of_business": line_of_business,
        "states_covered": list(states_covered),
        "inception_date": inception_date,
        "aggregate_limit_cents": aggregate_limit_cents,
        "commission_rate_pct": commission_rate_pct,
        "corrective_threshold_pct": corrective_threshold_pct,
        "termination_threshold_pct": termination_threshold_pct,
        "min_trust_balance_cents": min_trust_balance_cents,
        "min_earned_premium_for_ratio_cents": min_earned_premium_for_ratio_cents,
        "status": "PROPOSED",
        "consumed_aggregate_cents": 0,
        "trust_balance_cents": 0,
        "latest_incurred_loss_ratio_pct": None,
        "termination_reason": None,
    })
    STORE.programs[p["id"]] = p
    return success_object(serialize.program(p), status=201)


@bp.get("/mga/programs/<programId>")
def get_program(programId):
    require_roles(*ALL_ROLES)
    p = get_or_404(STORE.programs, programId, "Program")
    return success_object(serialize.program(p))


@bp.get("/mga/programs")
def list_programs():
    require_roles(*ALL_ROLES)
    items = filter_query(
        list(STORE.programs.values()),
        carrier_id=request.args.get("carrier_id"),
        status=request.args.get("status"),
    )
    return render_list(items, serialize.program)


@bp.post("/mga/programs/<programId>/activate")
def activate_program(programId):
    p = _carrier_scoped_program(programId)
    require_program_not_terminal(p)
    if p["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, "Only a PROPOSED program can be activated.")
    carrier = STORE.carriers.get(p["carrier_id"])
    if carrier is None or carrier["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "A SUSPENDED carrier may not activate new programs.")
    if not any(g["program_id"] == p["id"] and g["status"] == "ACTIVE" for g in STORE.guidelines.values()):
        raise_err(ERR_INVALID_STATE, "Activation requires at least one ACTIVE underwriting guideline.")
    if not any(a["program_id"] == p["id"] and a["status"] in ("ACTIVE", "EXHAUSTED") for a in STORE.capacity_allocations.values()):
        raise_err(ERR_INVALID_STATE, "Activation requires a non-terminal capacity allocation.")
    if not any(f["program_id"] == p["id"] and f["status"] == "EFFECTIVE" for f in STORE.rate_filings.values()):
        raise_err(ERR_INVALID_STATE, "Activation requires at least one EFFECTIVE rate filing.")
    p["status"] = "ACTIVE"
    touch(p)
    return success_object(serialize.program(p))


@bp.post("/mga/programs/<programId>/suspend")
def suspend_program(programId):
    p = _carrier_scoped_program(programId)
    require_program_not_terminal(p)
    if p["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE program can be suspended.")
    cascades.suspend_program(p)
    return success_object(serialize.program(p))


@bp.post("/mga/programs/<programId>/resume")
def resume_program(programId):
    p = _carrier_scoped_program(programId)
    require_program_not_terminal(p)
    if p["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "Only a SUSPENDED program can be resumed.")
    for a in STORE.carrier_audits.values():
        if a["program_id"] == p["id"] and a["status"] == "ESCALATED":
            if any(f.get("severity") == "CRITICAL" and not f.get("resolved", False) for f in a["findings"]):
                raise_err(
                    ERR_INVALID_STATE,
                    "An ESCALATED audit with an unresolved CRITICAL finding bars resumption.",
                )
    # Suspended appointments are deliberately NOT auto-restored.
    p["status"] = "ACTIVE"
    touch(p)
    return success_object(serialize.program(p))


@bp.post("/mga/programs/<programId>/enter-runoff")
def enter_runoff(programId):
    p = _carrier_scoped_program(programId)
    require_program_not_terminal(p)
    if p["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE or SUSPENDED program can enter run-off.")
    p["status"] = "RUN_OFF"
    touch(p)
    return success_object(serialize.program(p))


@bp.post("/mga/programs/<programId>/terminate")
def terminate_program(programId):
    p = _carrier_scoped_program(programId)
    body = get_body()
    termination_reason = req_str(body, "termination_reason")
    require_program_not_terminal(p)
    if p["status"] != "RUN_OFF":
        raise_err(ERR_INVALID_STATE, "Only a RUN_OFF program can be terminated.")
    pid = p["id"]
    if any(x["program_id"] == pid and x["status"] in ACTIVE_POLICY_STATUSES for x in STORE.policies.values()):
        raise_err(ERR_PROGRAM_HAS_ACTIVE_POLICIES, "Program still has policies in QUOTED/BOUND/ISSUED/PENDING_CANCELLATION.")
    if any(c["program_id"] == pid and c["status"] in OPEN_CLAIM_STATUSES for c in STORE.claims.values()):
        raise_err(ERR_OPEN_CLAIMS_EXIST, "Program still has open claims.")
    if any(b["program_id"] == pid and b["status"] in OPEN_BORDEREAU_STATUSES for b in STORE.bordereaux.values()):
        raise_err(ERR_UNACCEPTED_BORDEREAUX, "Program still has bordereaux in DRAFT/SUBMITTED/REJECTED.")
    if p["trust_balance_cents"] != 0:
        raise_err(ERR_TRUST_NOT_ZERO, "Program trust balance must be exactly zero to terminate.")
    cascades.terminate_program(p, termination_reason)
    return success_object(serialize.program(p))


@bp.post("/mga/programs/<programId>/decline")
def decline_program(programId):
    p = _carrier_scoped_program(programId)
    body = get_body()
    termination_reason = req_str(body, "termination_reason")
    require_program_not_terminal(p)
    if p["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, "Only a PROPOSED program can be declined.")
    cascades.decline_program(p, termination_reason)
    return success_object(serialize.program(p))
