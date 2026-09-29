"""Interactive endpoints: durability index, prototypes and the warranty gate (PRD §3.8)."""

from flask import Blueprint

import calc
import helpers
import serializers
from auth import (ALL_ROLES, ROLE_CONSERVATOR, ROLE_CURATOR, ROLE_FABRICATION_LEAD,
                  ROLE_PROJECT_MANAGER, caller_id, check_segregation, endpoint)
from envelope import list_response, object_response, pagination, query_filter
from errors import ApiError
from helpers import touch
from store import db, new_row
from validate import bad, body_object, v_enum, v_int, v_num, v_str

bp = Blueprint("interactives", __name__)

INTERACTIVE_KINDS = ("TOUCHSCREEN", "MECHANICAL", "PROJECTION", "AUDIO", "AR_HEADSET")
PROTOTYPE_DECISIONS = ("APPROVE", "REJECT")


@bp.route("/exhibit-projects/<pid>/interactives", methods=["POST"])
@endpoint(roles=[ROLE_FABRICATION_LEAD, ROLE_CURATOR])
def create_interactive(pid):
    project = helpers.get_project(pid)
    body = body_object()
    code = v_str(body, "code", 1, 40)
    kind = v_enum(body, "kind", INTERACTIVE_KINDS)
    objective_code = v_str(body, "objective_code", 1, None)
    daily_uses = v_int(body, "expected_daily_uses", minimum=1)
    duty_hours = v_num(body, "duty_hours_per_day", gt=0, le=24)
    mtbf = v_int(body, "mtbf_cycles", minimum=1000)
    parts_years = v_int(body, "parts_availability_years", minimum=0, maximum=30)
    warranty_months = v_int(body, "warranty_months", minimum=0, maximum=120)
    if objective_code not in project["objective_codes"]:
        # No station exists outside the interpretive plan.
        bad("objective_code must name one of the project's objective_codes.")

    helpers.require_unique(db.interactives, project["id"], "code", code)
    helpers.require_phase(project, ("INTERPRETIVE", "SCHEMATIC", "DESIGN_DEV"))

    interactive = new_row("interactives", {
        "project_id": project["id"],
        "code": code,
        "kind": kind,
        "objective_code": objective_code,
        "expected_daily_uses": daily_uses,
        "duty_hours_per_day": duty_hours,
        "mtbf_cycles": mtbf,
        "parts_availability_years": parts_years,
        "warranty_months": warranty_months,
        "measured_daily_uses": None,
        "measured_mtbf_cycles": None,
        "durability_index_spec": None,
        "durability_index_verified": None,
        "prototype_iteration": 0,
        "status": "SPECIFIED",
        "submitted_by_user_id": caller_id(),
    })
    interactive["durability_index_spec"] = calc.durability_index_spec(interactive)
    db.interactives[interactive["id"]] = interactive
    return object_response(serializers.interactive_json(interactive), 201)


@bp.route("/exhibit-projects/<pid>/interactives", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_interactives(pid):
    project = helpers.get_project(pid)
    limit, offset = pagination()
    status = query_filter("status")
    tier = query_filter("maintenance_tier")
    rows = helpers.rows_of_project(db.interactives, project["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if tier is not None:
        rows = [r for r in rows if calc.maintenance_tier(r) == tier]
    return list_response(rows, serializers.interactive_json, limit, offset)


@bp.route("/interactives/<interactive_id>", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def get_interactive(interactive_id):
    interactive = helpers.get_interactive(interactive_id)
    return object_response(serializers.interactive_json(interactive))


@bp.route("/interactives/<interactive_id>/submit-prototype", methods=["POST"])
@endpoint(roles=[ROLE_FABRICATION_LEAD])
def submit_prototype(interactive_id):
    interactive = helpers.get_interactive(interactive_id)
    project = helpers.owning_project(interactive)
    body = body_object()
    measured_uses = v_int(body, "measured_daily_uses", minimum=1)
    measured_mtbf = v_int(body, "measured_mtbf_cycles", minimum=1000)

    helpers.require_phase(project, ("DESIGN_DEV", "FABRICATION"))
    helpers.require_not_frozen(project)
    if interactive["status"] not in ("SPECIFIED", "PROTOTYPE_REJECTED"):
        raise ApiError("ERR_INVALID_INTERACTIVE_STATE")

    interactive["measured_daily_uses"] = measured_uses
    interactive["measured_mtbf_cycles"] = measured_mtbf
    interactive["prototype_iteration"] = interactive["prototype_iteration"] + 1
    interactive["submitted_by_user_id"] = caller_id()
    interactive["status"] = "PROTOTYPE_SUBMITTED"
    touch(interactive)
    return object_response(serializers.interactive_json(interactive))


@bp.route("/interactives/<interactive_id>/prototype-decision", methods=["POST"])
@endpoint(roles=[ROLE_PROJECT_MANAGER, ROLE_CONSERVATOR])
def prototype_decision(interactive_id):
    interactive = helpers.get_interactive(interactive_id)
    project = helpers.owning_project(interactive)
    # Step 3: the submitter may not rule on their own bench work.
    check_segregation(interactive["submitted_by_user_id"])
    body = body_object()
    decision = v_enum(body, "decision", PROTOTYPE_DECISIONS)
    v_str(body, "note", None, None, required=False, default=None)

    # Step 11: ruling on an interactive prototype is frozen-blocked.
    helpers.require_not_frozen(project)
    if interactive["status"] != "PROTOTYPE_SUBMITTED":
        raise ApiError("ERR_INVALID_INTERACTIVE_STATE")

    if decision == "APPROVE":
        interactive["durability_index_verified"] = calc.durability_index_verified(interactive)
        interactive["status"] = "PROTOTYPE_APPROVED"
    else:
        # A rejected bench test never earns the credit: the measured figures and the
        # verified index are deliberately left untouched.
        interactive["status"] = "PROTOTYPE_REJECTED"
    touch(interactive)
    return object_response(serializers.interactive_json(interactive))


@bp.route("/interactives/<interactive_id>/mark-fabricated", methods=["POST"])
@endpoint(roles=[ROLE_FABRICATION_LEAD])
def mark_fabricated(interactive_id):
    interactive = helpers.get_interactive(interactive_id)
    project = helpers.owning_project(interactive)
    helpers.require_phase(project, ("FABRICATION", "INSTALLATION"))
    helpers.require_not_frozen(project)
    if interactive["status"] != "PROTOTYPE_APPROVED":
        raise ApiError("ERR_PROTOTYPE_NOT_APPROVED")
    interactive["status"] = "FABRICATED"
    touch(interactive)
    return object_response(serializers.interactive_json(interactive))


@bp.route("/interactives/<interactive_id>/commission", methods=["POST"])
@endpoint(roles=[ROLE_PROJECT_MANAGER])
def commission(interactive_id):
    interactive = helpers.get_interactive(interactive_id)
    project = helpers.owning_project(interactive)
    body = body_object(required=False)
    warranty_months = v_int(body, "warranty_months", minimum=0, maximum=120,
                            required=False, default=None)

    helpers.require_phase(project, ("COMMISSIONING",))
    if interactive["status"] != "FABRICATED":
        raise ApiError("ERR_INVALID_INTERACTIVE_STATE")

    # A supplied term replaces the stored value BEFORE the floor check is applied.
    # It is only written back once every precondition has passed, so a refused
    # commissioning leaves the row exactly as it was.
    effective_term = interactive["warranty_months"] if warranty_months is None else warranty_months

    # The blocking-defect scan is scoped to this station alone, not to the project.
    blocking = [p for p in db.punch_items.values()
                if p["interactive_id"] == interactive["id"]
                and p["severity"] == "BLOCKING" and p["status"] == "OPEN"]
    if blocking:
        raise ApiError("ERR_BLOCKING_PUNCH_ITEMS_OPEN")

    tier = calc.maintenance_tier(interactive)
    floor = calc.WARRANTY_FLOOR_MONTHS[tier]
    if effective_term < floor:
        raise ApiError("ERR_WARRANTY_TERM_TOO_SHORT",
                       "A %s station requires at least %d warranty months." % (tier, floor))

    interactive["warranty_months"] = effective_term
    interactive["status"] = "COMMISSIONED"
    touch(interactive)
    return object_response(serializers.interactive_json(interactive))
