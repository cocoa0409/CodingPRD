"""RiggingPoint endpoints: reservation with OCC and the engineering loop."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_SOD_VIOLATION,
    ERR_POINT_ALREADY_RESERVED,
    ERR_ENGINEERING_DEADLINE_PASSED,
    ERR_PLOT_NOT_SUBMITTED,
    ERR_STALE_PLOT_REVISION,
)
from middleware import require_roles
from response import success_object, success_list
from services import calculations as calc
from services.domain import (
    check_declared,
    check_terminal,
    check_transition_owner,
    closed_windows_intersect,
    minus_hours,
    parse_to,
)
from util import (
    get_json_body,
    optional_int,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_enum,
    require_int,
    require_number,
    require_string,
    serialize,
    serialize_list,
    sort_by_created_at,
)

bp = Blueprint("rigging_points", __name__)

HANG_TYPES = {"STRAIGHT", "BRIDLE", "DEAD_HANG"}

POINT_STATES = {"RESERVED", "UNDER_REVIEW", "APPROVED", "REJECTED", "RELEASED"}
POINT_TERMINAL = {"RELEASED"}
POINT_TO_OWNERS = {
    "UNDER_REVIEW": {"RiggingSupervisor"},
    "APPROVED": {"StructuralEngineer"},
    "REJECTED": {"StructuralEngineer"},
    "RESERVED": {"RiggingSupervisor"},
    "RELEASED": {"RiggingSupervisor"},
}
POINT_DECLARED = {
    "RESERVED": {"UNDER_REVIEW", "RELEASED"},
    "UNDER_REVIEW": {"APPROVED", "REJECTED", "RELEASED"},
    "REJECTED": {"RESERVED", "RELEASED"},
    "APPROVED": {"RELEASED"},
}


def get_point_or_404(point_id: str) -> dict:
    point = db.rigging_points.get(point_id)
    if point is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "RiggingPoint id does not exist")
    return point


@bp.route("/plots/<plot_id>/rigging-points", methods=["POST"])
@require_roles("RiggingSupervisor")
def create_rigging_point(plot_id: str, _user_id: str, _role: str):
    body = get_json_body()
    point_label = require_string(body, "point_label")
    bay_index = require_int(body, "bay_index", minimum=0)
    hang_type = require_enum(body, "hang_type", HANG_TYPES)
    motor_count = optional_int(body, "motor_count", 0, minimum=0)
    deadweight_kg = require_number(body, "deadweight_kg", minimum=0, exclusive_min=True)
    expected_plot_version = require_int(body, "expected_plot_version")

    plot = db.plots.get(plot_id)
    if plot is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "LightingPlot id does not exist")
    if plot["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Rigging points may be reserved only on a DRAFT plot")
    if expected_plot_version != plot["version"]:
        raise_err(ERR_STALE_VERSION, "expected_plot_version does not match LightingPlot.version")

    production = db.productions.get(plot["production_id"])
    venue = db.venues.get(production["venue_id"])

    # Per-point capacity check (OCC fires before this; equality passes).
    factored, utilization = calc.compute_factored_load(hang_type, motor_count, deadweight_kg, venue)
    calc.check_point_capacity(factored, venue)

    # point_label uniqueness across intersecting closed occupancy windows at
    # the same venue (capacity check fires before this).
    new_in = parse_iso8601(production["load_in_at"], "load_in_at")
    new_out = parse_iso8601(production["load_out_at"], "load_out_at")
    for other in db.rigging_points.values():
        if other["point_label"] != point_label or other["status"] == "RELEASED":
            continue
        other_plot = db.plots.get(other["plot_id"])
        if other_plot is None:
            continue
        other_production = db.productions.get(other_plot["production_id"])
        if other_production is None or other_production["venue_id"] != venue["id"]:
            continue
        o_in = parse_iso8601(other_production["load_in_at"], "load_in_at")
        o_out = parse_iso8601(other_production["load_out_at"], "load_out_at")
        if closed_windows_intersect(new_in, new_out, o_in, o_out):
            raise_err(ERR_POINT_ALREADY_RESERVED, "point_label is already held at this venue window")

    point = {
        "plot_id": plot_id,
        "point_label": point_label,
        "bay_index": bay_index,
        "hang_type": hang_type,
        "motor_count": motor_count,
        "deadweight_kg": deadweight_kg,
        "factored_load_kg": float(factored),
        "utilization": float(utilization),
        "status": "RESERVED",
        "submitted_by_user_id": _user_id,
        "reviewed_by_user_id": None,
        "plot_version_at_submission": None,
    }
    db.stamp_new(point)
    db.rigging_points[point["id"]] = point
    # Every reservation mutates the plot's derived total, bumping its version.
    calc.recompute_plot_total(plot)
    calc.refresh_posture(production)
    return success_object(serialize(point), 201)


@bp.route("/plots/<plot_id>/rigging-points", methods=["GET"])
@require_roles("Any")
def list_plot_points(plot_id: str, _user_id: str, _role: str):
    plot = db.plots.get(plot_id)
    if plot is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "LightingPlot id does not exist")
    limit, offset = parse_pagination()
    items = [p for p in db.rigging_points.values() if p["plot_id"] == plot_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/rigging-points/<point_id>", methods=["GET"])
@require_roles("Any")
def get_rigging_point(point_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_point_or_404(point_id)))


@bp.route("/rigging-points/<point_id>/transition", methods=["POST"])
@require_roles("RiggingSupervisor", "StructuralEngineer")
def transition_rigging_point(point_id: str, _user_id: str, _role: str):
    body = get_json_body()
    to = parse_to(body, POINT_STATES)
    check_transition_owner(to, POINT_TO_OWNERS, _role)

    # Schema for the revision loop (to=RESERVED) is entity-independent (400).
    new_deadweight = None
    new_motor_count = None
    if to == "RESERVED":
        new_deadweight = require_number(body, "deadweight_kg", minimum=0, exclusive_min=True)
        new_motor_count = require_int(body, "motor_count", minimum=0)

    point = get_point_or_404(point_id)

    # Segregation of duties (priority 3) precedes state checks.
    if to == "APPROVED" and _user_id == point.get("submitted_by_user_id"):
        raise_err(ERR_SOD_VIOLATION, "Approver must differ from the point's submitter")

    check_terminal(point, POINT_TERMINAL, to, POINT_DECLARED)
    check_declared(point, to, POINT_DECLARED)

    plot = db.plots.get(point["plot_id"])
    production = db.productions.get(plot["production_id"])
    venue = db.venues.get(production["venue_id"])
    clock = db.clock_dt()

    if to == "UNDER_REVIEW":
        deadline = minus_hours(
            parse_iso8601(production["load_in_at"], "load_in_at"),
            venue["engineering_submission_lead_hours"],
        )
        if clock > deadline:
            raise_err(
                ERR_ENGINEERING_DEADLINE_PASSED,
                "Engineering submission deadline has passed",
            )
        if plot["status"] not in ("SUBMITTED", "APPROVED"):
            raise_err(ERR_PLOT_NOT_SUBMITTED, "Plot must be SUBMITTED or APPROVED")
        point["plot_version_at_submission"] = plot["version"]
        point["status"] = "UNDER_REVIEW"
        db.touch(point)
        calc.refresh_posture(production)
        return success_object(serialize(point))

    if to == "APPROVED":
        # PRD order: segregation of duties, then bay aggregate, then version pin.
        calc.check_bay_aggregate_for_point(point)
        if plot["version"] != point["plot_version_at_submission"]:
            raise_err(ERR_STALE_PLOT_REVISION, "Plot version advanced past the submission pin")
        point["reviewed_by_user_id"] = _user_id
        point["status"] = "APPROVED"
        db.touch(point)
        calc.refresh_posture(production)
        return success_object(serialize(point))

    if to == "REJECTED":
        point["status"] = "REJECTED"
        db.touch(point)
        calc.refresh_posture(production)
        return success_object(serialize(point))

    if to == "RESERVED":
        # Revision loop: recompute factored load; per-point capacity check with
        # the same equality-passes rule.
        factored, utilization = calc.compute_factored_load(
            point["hang_type"], new_motor_count, new_deadweight, venue
        )
        calc.check_point_capacity(factored, venue)
        point["deadweight_kg"] = new_deadweight
        point["motor_count"] = new_motor_count
        point["factored_load_kg"] = float(factored)
        point["utilization"] = float(utilization)
        point["status"] = "RESERVED"
        db.touch(point)
        calc.recompute_plot_total(plot)
        calc.refresh_posture(production)
        return success_object(serialize(point))

    # to == "RELEASED"
    was_approved = point["status"] == "APPROVED"
    point["status"] = "RELEASED"
    db.touch(point)
    calc.recompute_plot_total(plot)
    # Releasing an APPROVED point recomputes posture; refresh_posture also
    # performs the READY_FOR_LOADIN -> PLANNING downgrade when posture drops.
    calc.refresh_posture(production)
    return success_object(serialize(point))
