"""PowerPlan endpoints: sizing on submit, approval, supersede, revision loop."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_STATE
from middleware import require_roles
from response import success_object
from services import calculations as calc
from services.domain import (
    check_declared,
    check_terminal,
    check_transition_owner,
    parse_to,
)
from util import get_json_body, optional_int, serialize

bp = Blueprint("power_plans", __name__)

PLAN_STATES = {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"}
PLAN_TERMINAL: set[str] = set()  # scaffold declares no terminal states
PLAN_TO_OWNERS = {
    "SUBMITTED": {"ProductionManager"},
    "APPROVED": {"SafetyInspector"},
    "REJECTED": {"SafetyInspector"},
    "DRAFT": {"ProductionManager"},
    # SUPERSEDED is system-fired only.
}
PLAN_DECLARED = {
    "DRAFT": {"SUBMITTED"},
    "SUBMITTED": {"APPROVED", "REJECTED"},
    "REJECTED": {"DRAFT"},
    "APPROVED": set(),
    "SUPERSEDED": set(),
}


def get_plan_or_404(plan_id: str) -> dict:
    plan = db.power_plans.get(plan_id)
    if plan is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "PowerPlan id does not exist")
    return plan


@bp.route("/power-plans/<plan_id>", methods=["GET"])
@require_roles("Any")
def get_plan(plan_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_plan_or_404(plan_id)))


@bp.route("/power-plans/<plan_id>/transition", methods=["POST"])
@require_roles("ProductionManager", "SafetyInspector")
def transition_plan(plan_id: str, _user_id: str, _role: str):
    body = get_json_body()
    to = parse_to(body, PLAN_STATES)
    check_transition_owner(to, PLAN_TO_OWNERS, _role)

    # Revision-loop payload schema (optional revised inputs, type-checked).
    revised: dict = {}
    if to == "DRAFT":
        for name in ("phase_l1_watts", "phase_l2_watts", "phase_l3_watts", "feeder_length_m"):
            value = optional_int(body, name, None, minimum=0)
            if value is not None:
                revised[name] = value
        if "generator_required" in body and body["generator_required"] is not None:
            if not isinstance(body["generator_required"], bool):
                raise_err(ERR_INVALID_REQUEST, "Field generator_required must be a boolean")
            revised["generator_required"] = body["generator_required"]

    plan = get_plan_or_404(plan_id)
    check_terminal(plan, PLAN_TERMINAL, to, PLAN_DECLARED)
    check_declared(plan, to, PLAN_DECLARED)

    production = db.productions.get(plan["production_id"])

    if to == "SUBMITTED":
        venue = db.venues.get(production["venue_id"])
        # Runs the pinned sizing computation; on failure the plan stays DRAFT
        # with computed fields untouched.
        computed = calc.run_power_sizing(plan, venue)
        plan.update(computed)
        plan["status"] = "SUBMITTED"
        db.touch(plan)
        calc.refresh_posture(production)
        return success_object(serialize(plan))

    if to == "APPROVED":
        if production is None or production["status"] != "PLANNING":
            raise_err(ERR_INVALID_STATE, "Power plan approval requires production PLANNING")
        plan["status"] = "APPROVED"
        db.touch(plan)
        # Supersede any other APPROVED plan of this production.
        for other in db.power_plans.values():
            if (
                other["id"] != plan["id"]
                and other["production_id"] == plan["production_id"]
                and other["status"] == "APPROVED"
            ):
                other["status"] = "SUPERSEDED"
                db.touch(other)
        calc.refresh_posture(production)
        return success_object(serialize(plan))

    if to == "REJECTED":
        plan["status"] = "REJECTED"
        db.touch(plan)
        calc.refresh_posture(production)
        return success_object(serialize(plan))

    # to == "DRAFT" (revision loop): resupplied inputs; computed fields reset.
    for name, value in revised.items():
        plan[name] = value
    plan["total_load_watts"] = None
    plan["required_kva"] = None
    plan["selected_generator_tier_kva"] = None
    plan["max_phase_imbalance_pct"] = None
    plan["status"] = "DRAFT"
    db.touch(plan)
    calc.refresh_posture(production)
    return success_object(serialize(plan))
