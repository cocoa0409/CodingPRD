"""Loss-ratio evaluations: append-only snapshots; a TERMINATION_REVIEW outcome
auto-suspends an ACTIVE program with the full cascade (PRD section 3.8)."""
from flask import Blueprint, request

import serialize
from db import STORE, new_entity, now_dt
from errors import raise_err, ERR_INVALID_STATE
from middleware import require_roles, require_carrier_owner, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, filter_query
from routes.programs import require_program_not_terminal
from services import cascades, lossratio
from validation import get_body, req_str

bp = Blueprint("evaluations", __name__)

# Remittances and loss evaluations share this state gate.
EVALUATABLE_STATUSES = ("ACTIVE", "RUN_OFF", "SUSPENDED")


@bp.post("/mga/programs/<programId>/loss-evaluations")
def create_loss_evaluation(programId):
    require_roles("CarrierUnderwriter")
    program = get_or_404(STORE.programs, programId, "Program")
    require_carrier_owner(program)
    body = get_body()
    period_label = req_str(body, "period_label")
    require_program_not_terminal(program)
    if program["status"] not in EVALUATABLE_STATUSES:
        raise_err(ERR_INVALID_STATE, "Loss evaluations require program status ACTIVE, RUN_OFF or SUSPENDED.")
    result = lossratio.evaluate_program(program, now_dt())
    e = new_entity()
    e.update({
        "program_id": program["id"],
        "period_label": period_label,
        "earned_premium_cents": result["earned_premium_cents"],
        "paid_losses_cents": result["paid_losses_cents"],
        "case_reserves_cents": result["case_reserves_cents"],
        "paid_loss_ratio_pct": result["paid_loss_ratio_pct"],
        "incurred_loss_ratio_pct": result["incurred_loss_ratio_pct"],
        "outcome": result["outcome"],
    })
    STORE.loss_evaluations[e["id"]] = e
    program["latest_incurred_loss_ratio_pct"] = result["incurred_loss_ratio_pct"]
    if result["outcome"] == "TERMINATION_REVIEW" and program["status"] == "ACTIVE":
        cascades.suspend_program(program)
    return success_object(serialize.loss_evaluation(e), status=201)


@bp.get("/mga/programs/<programId>/loss-evaluations")
def list_program_loss_evaluations(programId):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.programs, programId, "Program")
    items = [e for e in STORE.loss_evaluations.values() if e["program_id"] == programId]
    return render_list(items, serialize.loss_evaluation)


@bp.get("/mga/loss-evaluations/<evaluationId>")
def get_loss_evaluation(evaluationId):
    require_roles(*ALL_ROLES)
    e = get_or_404(STORE.loss_evaluations, evaluationId, "LossEvaluation")
    return success_object(serialize.loss_evaluation(e))


@bp.get("/mga/loss-evaluations")
def list_loss_evaluations():
    require_roles(*ALL_ROLES)
    items = filter_query(
        list(STORE.loss_evaluations.values()),
        program_id=request.args.get("program_id"),
    )
    return render_list(items, serialize.loss_evaluation)
