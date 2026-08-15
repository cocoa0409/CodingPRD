"""ChangeOrder endpoints: the growth-work adjudication loop."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CHANGE_BUDGET_EXCEEDED,
    ERR_CHANGE_ORDER_NOT_REVIEWABLE,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_OWNER_APPROVAL_NOT_REQUIRED,
    ERR_OWNERSHIP_MISMATCH,
    ERR_PROJECT_NOT_IN_DOCK,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from response import success_list, success_object
from services import project_ops
from services.project_ops import PRICING_MODES, OWNER_APPROVAL_THRESHOLD_CENTS
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_int,
    optional_number,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("change_orders", __name__)

READ_ROLES = ("YardAdmin", "ProjectManager", "CommercialApprover", "ShipownerRep")


def get_change_order_or_404(co_id: str) -> dict:
    co = db.change_orders.get(co_id)
    if co is None:
        raise_err(ERR_NOT_FOUND, "ChangeOrder id does not exist")
    return co


def _pricing_types_from_body(body: dict) -> dict:
    return {
        "quantity": optional_number(body, "quantity"),
        "unit_price_cents": optional_int(body, "unit_price_cents"),
        "estimated_hours": optional_number(body, "estimated_hours"),
        "hourly_rate_cents": optional_int(body, "hourly_rate_cents"),
        "materials_cost_cents": optional_int(body, "materials_cost_cents"),
    }


def _reprice(co: dict) -> None:
    co["proposed_cost_cents"] = project_ops.price_line(
        co["pricing_mode"],
        co.get("quantity"),
        co.get("unit_price_cents"),
        co.get("estimated_hours"),
        co.get("hourly_rate_cents"),
        co.get("materials_cost_cents", 0),
    )
    # Strictly greater than the threshold requires the countersign; exactly
    # equal does not.
    co["requires_owner_countersign"] = (
        co["proposed_cost_cents"] > OWNER_APPROVAL_THRESHOLD_CENTS
    )


@bp.route("/v1/change-orders", methods=["POST"])
@require_roles("ProjectManager")
def create_change_order(_user_id: str, _role: str):
    body = get_json_body()
    # Rung 3: well-formedness and field types.
    project_id = require_string(body, "project_id")
    expected_project_version = require_int(body, "expected_project_version")
    description = require_string(body, "description")
    trade_code = require_string(body, "trade_code")
    pricing_mode = require_enum(body, "pricing_mode", PRICING_MODES)
    duration_days = require_int(body, "duration_days")
    if duration_days < 1:
        raise_err(ERR_INVALID_REQUEST, "duration_days must be >= 1")
    schedule_delta_days = require_int(body, "schedule_delta_days")
    pricing = _pricing_types_from_body(body)

    # Rung 4: the project exists.
    project = db.projects.get(project_id)
    if project is None:
        raise_err(ERR_NOT_FOUND, "RepairProject id does not exist")

    # Rung 5: growth work is proposed only while IN_DOCK; OCC on the project.
    if project["status"] != "IN_DOCK":
        raise_err(ERR_PROJECT_NOT_IN_DOCK, "change orders require the project to be IN_DOCK")
    if expected_project_version != project["version"]:
        raise_err(
            ERR_STALE_VERSION,
            "expected_project_version does not match the project's current version",
        )

    # Rung 8: mode-conditional pricing inputs (credit pricing permitted here).
    project_ops.validate_pricing_inputs(pricing_mode, pricing, allow_negative_unit_price=True)

    materials = pricing["materials_cost_cents"]
    co = {
        "project_id": project_id,
        "description": description,
        "trade_code": trade_code,
        "pricing_mode": pricing_mode,
        "quantity": pricing["quantity"],
        "unit_price_cents": pricing["unit_price_cents"],
        "estimated_hours": pricing["estimated_hours"],
        "hourly_rate_cents": pricing["hourly_rate_cents"],
        "materials_cost_cents": materials if materials is not None else 0,
        "duration_days": duration_days,
        "schedule_delta_days": schedule_delta_days,
        "proposed_cost_cents": 0,
        "requires_owner_countersign": False,
        "proposed_by_user_id": _user_id,
        "commercial_approved_by": None,
        "owner_approved_by": None,
        "rejection_reason": None,
        "status": "UNDER_REVIEW",
        "approved_at_utc": None,
    }
    _reprice(co)
    db.stamp_new(co)
    db.change_orders[co["id"]] = co
    # Proposing a change order is a write against the project: version +1.
    db.touch(project)
    return success_object(serialize(co), 201)


@bp.route("/v1/change-orders", methods=["GET"])
@require_roles(*READ_ROLES)
def list_change_orders(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.change_orders.values()))
    items = apply_filters(items, ["project_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/v1/change-orders/<co_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_change_order(co_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_change_order_or_404(co_id)))


@bp.route("/v1/change-orders/<co_id>/approve", methods=["POST"])
@require_roles("CommercialApprover")
def approve_change_order(co_id: str, _user_id: str, _role: str):
    co = get_change_order_or_404(co_id)
    # Rung 5: defined only from UNDER_REVIEW.
    if co["status"] != "UNDER_REVIEW":
        raise_err(ERR_CHANGE_ORDER_NOT_REVIEWABLE, "approve requires status UNDER_REVIEW")
    # Rung 6: segregation of duties.
    if _user_id == co["proposed_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "the approver may not be the proposing user")
    project = db.projects[co["project_id"]]
    # Rung 11: the change budget ceiling (when the project carries one).
    if project.get("change_budget_cents") is not None:
        approved_sum = sum(
            c["proposed_cost_cents"]
            for c in project_ops.project_change_orders(project["id"])
            if c["status"] == "APPROVED"
        )
        if approved_sum + co["proposed_cost_cents"] > project["change_budget_cents"]:
            raise_err(
                ERR_CHANGE_BUDGET_EXCEEDED,
                "approval would exceed the project's change budget",
            )

    co["commercial_approved_by"] = _user_id
    awaiting_owner = co["requires_owner_countersign"] and co["owner_approved_by"] is None
    if not awaiting_owner:
        project_ops.fire_change_order_approval(co, project)
    db.touch(co)
    # Every approval call — final or not — advances the parent project.
    db.touch(project)
    return success_object(serialize(co))


@bp.route("/v1/change-orders/<co_id>/owner-approve", methods=["POST"])
@require_roles("ShipownerRep")
def owner_approve_change_order(co_id: str, _user_id: str, _role: str):
    co = get_change_order_or_404(co_id)
    # Rung 5: defined only from UNDER_REVIEW; only when a countersign is due.
    if co["status"] != "UNDER_REVIEW":
        raise_err(ERR_CHANGE_ORDER_NOT_REVIEWABLE, "owner-approve requires status UNDER_REVIEW")
    if not co["requires_owner_countersign"]:
        raise_err(
            ERR_OWNER_APPROVAL_NOT_REQUIRED,
            "this change order is at or below the owner threshold",
        )
    # Rung 6: the caller must be the owning ShipownerRep of the vessel.
    project = db.projects[co["project_id"]]
    vessel = db.vessels[project["vessel_id"]]
    if _user_id != vessel["owner_user_id"]:
        raise_err(ERR_OWNERSHIP_MISMATCH, "caller is not the vessel's owner representative")

    co["owner_approved_by"] = _user_id
    if co["commercial_approved_by"] is not None:
        project_ops.fire_change_order_approval(co, project)
    db.touch(co)
    db.touch(project)
    return success_object(serialize(co))


@bp.route("/v1/change-orders/<co_id>/reject", methods=["POST"])
@require_roles("CommercialApprover")
def reject_change_order(co_id: str, _user_id: str, _role: str):
    # Rung 3: a non-empty reason is part of well-formedness.
    body = get_json_body()
    reason = require_string(body, "reason")
    co = get_change_order_or_404(co_id)
    if co["status"] != "UNDER_REVIEW":
        raise_err(ERR_CHANGE_ORDER_NOT_REVIEWABLE, "reject requires status UNDER_REVIEW")
    co["status"] = "REJECTED"
    co["rejection_reason"] = reason
    db.touch(co)
    return success_object(serialize(co))


@bp.route("/v1/change-orders/<co_id>/revise", methods=["POST"])
@require_roles("ProjectManager")
def revise_change_order(co_id: str, _user_id: str, _role: str):
    body = get_json_body()
    # Rung 3: types of the revisable fields.
    pricing = _pricing_types_from_body(body)
    duration_days = optional_int(body, "duration_days")
    if duration_days is not None and duration_days < 1:
        raise_err(ERR_INVALID_REQUEST, "duration_days must be >= 1")
    schedule_delta_days = optional_int(body, "schedule_delta_days")

    # Rung 4: the change order exists.
    co = get_change_order_or_404(co_id)
    # Rung 5: only a REJECTED proposal loops back to UNDER_REVIEW.
    if co["status"] != "REJECTED":
        raise_err(ERR_CHANGE_ORDER_NOT_REVIEWABLE, "revise requires status REJECTED")

    # Apply the revision and reprice under the mode-conditional rules.
    for field, value in pricing.items():
        if value is not None:
            co[field] = value
    if duration_days is not None:
        co["duration_days"] = duration_days
    if schedule_delta_days is not None:
        co["schedule_delta_days"] = schedule_delta_days
    # Rung 8: repricing validates the merged mode-conditional inputs.
    project_ops.validate_pricing_inputs(
        co["pricing_mode"],
        {
            "quantity": co.get("quantity"),
            "unit_price_cents": co.get("unit_price_cents"),
            "estimated_hours": co.get("estimated_hours"),
            "hourly_rate_cents": co.get("hourly_rate_cents"),
            "materials_cost_cents": co.get("materials_cost_cents"),
        },
        allow_negative_unit_price=True,
    )
    _reprice(co)
    # Negotiation restarts from a clean sheet.
    co["commercial_approved_by"] = None
    co["owner_approved_by"] = None
    co["status"] = "UNDER_REVIEW"
    db.touch(co)
    return success_object(serialize(co))


@bp.route("/v1/change-orders/<co_id>/withdraw", methods=["POST"])
@require_roles("ProjectManager")
def withdraw_change_order(co_id: str, _user_id: str, _role: str):
    co = get_change_order_or_404(co_id)
    if co["status"] != "UNDER_REVIEW":
        raise_err(ERR_CHANGE_ORDER_NOT_REVIEWABLE, "withdraw requires status UNDER_REVIEW")
    co["status"] = "WITHDRAWN"
    db.touch(co)
    return success_object(serialize(co))
