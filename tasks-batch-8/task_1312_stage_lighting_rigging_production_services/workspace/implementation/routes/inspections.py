"""SafetyInspection endpoints: begin/pass/fail/reschedule with type gates."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_RESOURCE_NOT_FOUND,
    ERR_SOD_VIOLATION,
    ERR_NOT_RESOURCE_OWNER,
    ERR_PREREQUISITE_INSPECTION_MISSING,
    ERR_RIGGING_NOT_APPROVED,
    ERR_POWER_PLAN_NOT_APPROVED,
)
from middleware import require_roles
from response import success_object
from services import calculations as calc
from services.domain import (
    check_declared,
    check_terminal,
    check_transition_owner,
    parse_to,
)
from util import get_json_body, require_string, serialize

bp = Blueprint("inspections", __name__)

INSPECTION_STATES = {"SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED", "CANCELLED"}
INSPECTION_TERMINAL = {"PASSED", "CANCELLED"}
INSPECTION_TO_OWNERS = {
    "IN_PROGRESS": {"SafetyInspector"},
    "PASSED": {"SafetyInspector"},
    "FAILED": {"SafetyInspector"},
    "SCHEDULED": {"ProductionManager"},
    # CANCELLED is cascade-driven only.
}
INSPECTION_DECLARED = {
    "SCHEDULED": {"IN_PROGRESS"},
    "IN_PROGRESS": {"PASSED", "FAILED"},
    "FAILED": {"SCHEDULED"},
}


def get_inspection_or_404(inspection_id: str) -> dict:
    insp = db.inspections.get(inspection_id)
    if insp is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "SafetyInspection id does not exist")
    return insp


def _current_approved_plot(production_id: str):
    for plot in db.plots.values():
        if plot["production_id"] == production_id and plot["status"] == "APPROVED":
            return plot
    return None


def _latest_attempt(production_id: str, inspection_type: str):
    """The inspection of the given type with the highest attempt_no."""
    best = None
    for insp in db.inspections.values():
        if insp["production_id"] != production_id or insp["inspection_type"] != inspection_type:
            continue
        if best is None or insp["attempt_no"] > best["attempt_no"]:
            best = insp
    return best


@bp.route("/inspections/<inspection_id>", methods=["GET"])
@require_roles("Any")
def get_inspection(inspection_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_inspection_or_404(inspection_id)))


@bp.route("/inspections/<inspection_id>/transition", methods=["POST"])
@require_roles("ProductionManager", "SafetyInspector")
def transition_inspection(inspection_id: str, _user_id: str, _role: str):
    body = get_json_body()
    to = parse_to(body, INSPECTION_STATES)
    check_transition_owner(to, INSPECTION_TO_OWNERS, _role)

    inspection = get_inspection_or_404(inspection_id)
    production = db.productions.get(inspection["production_id"])

    # Segregation of duties (priority 3) is evaluated before ownership
    # continuity (priority 4): a FINAL pass must not come from any engineer who
    # approved a point on the production's currently APPROVED plot.
    if to == "PASSED" and inspection["inspection_type"] == "FINAL":
        approved_plot = _current_approved_plot(inspection["production_id"])
        if approved_plot is not None:
            for point in db.rigging_points.values():
                if point["plot_id"] != approved_plot["id"]:
                    continue
                if point["status"] == "RELEASED":
                    continue
                reviewer = point.get("reviewed_by_user_id")
                if reviewer is not None and _user_id == reviewer:
                    raise_err(
                        ERR_SOD_VIOLATION,
                        "FINAL inspection passer must differ from every point approver",
                    )

    # Ownership continuity: passer/failer must be the inspector who began it.
    if to in ("PASSED", "FAILED"):
        if inspection.get("inspector_user_id") is None or _user_id != inspection["inspector_user_id"]:
            raise_err(ERR_NOT_RESOURCE_OWNER, "Only the inspector who began the inspection may record its outcome")

    # findings presence is schema (400) — after ownership per the pipeline.
    findings = None
    if to == "FAILED":
        findings = require_string(body, "findings")

    check_terminal(inspection, INSPECTION_TERMINAL, to, INSPECTION_DECLARED)
    check_declared(inspection, to, INSPECTION_DECLARED)

    if to == "IN_PROGRESS":
        itype = inspection["inspection_type"]
        if itype == "RIGGING":
            approved_plot = _current_approved_plot(inspection["production_id"])
            violation = approved_plot is None
            if not violation:
                for point in db.rigging_points.values():
                    if point["plot_id"] != approved_plot["id"]:
                        continue
                    if point["status"] == "RELEASED":
                        continue
                    if point["status"] != "APPROVED":
                        violation = True
                        break
            if violation:
                raise_err(ERR_RIGGING_NOT_APPROVED, "Every point on the approved plot must be APPROVED")
        elif itype == "ELECTRICAL":
            has_approved_plan = any(
                p["production_id"] == inspection["production_id"] and p["status"] == "APPROVED"
                for p in db.power_plans.values()
            )
            if not has_approved_plan:
                raise_err(ERR_POWER_PLAN_NOT_APPROVED, "Production has no APPROVED power plan")
        else:  # FINAL
            if production is None or production["status"] != "LOAD_IN":
                raise_err(ERR_INVALID_STATE, "FINAL inspection requires production LOAD_IN")
            rigging = _latest_attempt(inspection["production_id"], "RIGGING")
            electrical = _latest_attempt(inspection["production_id"], "ELECTRICAL")
            if (
                rigging is None
                or rigging["status"] != "PASSED"
                or electrical is None
                or electrical["status"] != "PASSED"
            ):
                raise_err(
                    ERR_PREREQUISITE_INSPECTION_MISSING,
                    "Latest RIGGING and ELECTRICAL inspections must both be PASSED",
                )
        inspection["inspector_user_id"] = _user_id
        inspection["status"] = "IN_PROGRESS"
        db.touch(inspection)
        return success_object(serialize(inspection))

    if to == "PASSED":
        inspection["status"] = "PASSED"
        db.touch(inspection)
        if inspection["inspection_type"] == "FINAL" and production is not None:
            if production["status"] == "LOAD_IN":
                production["status"] = "SHOW_READY"
                db.touch(production)
            calc.refresh_posture(production)
        return success_object(serialize(inspection))

    if to == "FAILED":
        inspection["findings"] = findings
        inspection["status"] = "FAILED"
        db.touch(inspection)
        if production is not None:
            if production["status"] == "SHOW_READY":
                production["status"] = "LOAD_IN"
                db.touch(production)
            calc.refresh_posture(production)
        return success_object(serialize(inspection))

    # to == "SCHEDULED" (re-inspection loop from FAILED)
    inspection["attempt_no"] = inspection["attempt_no"] + 1
    inspection["inspector_user_id"] = None
    inspection["findings"] = None
    inspection["status"] = "SCHEDULED"
    db.touch(inspection)
    return success_object(serialize(inspection))
