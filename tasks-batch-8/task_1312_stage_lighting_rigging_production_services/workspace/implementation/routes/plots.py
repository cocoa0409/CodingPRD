"""LightingPlot endpoints: review lifecycle with supersede cascade."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_RESOURCE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_EMPTY_PLOT,
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

bp = Blueprint("plots", __name__)

PLOT_STATES = {"DRAFT", "SUBMITTED", "APPROVED", "SUPERSEDED"}
PLOT_TERMINAL = {"SUPERSEDED"}
PLOT_TO_OWNERS = {
    "SUBMITTED": {"ProductionManager"},
    "APPROVED": {"StructuralEngineer"},
    "DRAFT": {"StructuralEngineer"},
    # SUPERSEDED is system-fired only.
}
PLOT_DECLARED = {
    "DRAFT": {"SUBMITTED"},
    "SUBMITTED": {"APPROVED", "DRAFT"},
    "APPROVED": set(),
}


def get_plot_or_404(plot_id: str) -> dict:
    plot = db.plots.get(plot_id)
    if plot is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "LightingPlot id does not exist")
    return plot


@bp.route("/plots/<plot_id>", methods=["GET"])
@require_roles("Any")
def get_plot(plot_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_plot_or_404(plot_id)))


@bp.route("/plots/<plot_id>/transition", methods=["POST"])
@require_roles("ProductionManager", "StructuralEngineer")
def transition_plot(plot_id: str, _user_id: str, _role: str):
    body = get_json_body()
    to = parse_to(body, PLOT_STATES)
    check_transition_owner(to, PLOT_TO_OWNERS, _role)

    rejection_reason = None
    if to == "DRAFT":
        # Engineering reject requires the reason (schema category, before 404).
        rejection_reason = require_string(body, "rejection_reason")

    plot = get_plot_or_404(plot_id)
    check_terminal(plot, PLOT_TERMINAL, to, PLOT_DECLARED)
    check_declared(plot, to, PLOT_DECLARED)

    production = db.productions.get(plot["production_id"])

    if to == "SUBMITTED":
        if production is None or production["status"] != "PLANNING":
            raise_err(ERR_INVALID_STATE, "Plot submission requires production PLANNING")
        has_point = any(
            p["plot_id"] == plot["id"]
            and p["status"] in ("RESERVED", "UNDER_REVIEW", "APPROVED")
            for p in db.rigging_points.values()
        )
        if not has_point:
            raise_err(ERR_EMPTY_PLOT, "Plot has no rigging points in a countable state")
        plot["rejection_reason"] = None
        plot["status"] = "SUBMITTED"
        db.touch(plot)
        calc.refresh_posture(production)
        return success_object(serialize(plot))

    if to == "DRAFT":
        plot["rejection_reason"] = rejection_reason
        plot["status"] = "DRAFT"
        db.touch(plot)
        calc.refresh_posture(production)
        return success_object(serialize(plot))

    # to == "APPROVED"
    calc.check_bay_aggregate_for_plot(plot)

    plot["approved_by_user_id"] = _user_id
    plot["approved_at"] = db.get_current_utc()
    plot["status"] = "APPROVED"
    db.touch(plot)

    # Supersede cascade: every other APPROVED plot of this production.
    for other in db.plots.values():
        if other["id"] == plot["id"]:
            continue
        if other["production_id"] != plot["production_id"]:
            continue
        if other["status"] != "APPROVED":
            continue
        other["status"] = "SUPERSEDED"
        for point in db.rigging_points.values():
            if point["plot_id"] == other["id"] and point["status"] in (
                "RESERVED",
                "UNDER_REVIEW",
                "APPROVED",
                "REJECTED",
            ):
                point["status"] = "RELEASED"
                db.touch(point)
        calc.recompute_plot_total(other)
        db.touch(other)

    calc.refresh_posture(production)
    return success_object(serialize(plot))
