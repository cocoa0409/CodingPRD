"""CostLineItem endpoints."""

from flask import Blueprint, request

import clock
from db import db
from errors import err_invalid_state, err_not_found
from middleware import require_roles
from serializers import cost_line_out
from services.core import (compute_line_total, recompute_case_subtotal, touch)
from util import (get_pagination, new_id, paginate, parse_body, require_enum,
                  require_positive_int, require_positive_number, require_string,
                  success_envelope)

bp = Blueprint("cost_lines", __name__)

ALL_ROLES = ("IntakeCoordinator", "DamageInvestigator", "ClaimsAdjuster",
             "RecoveryManager", "Excavator", "Locator")


@bp.route("/damage-recovery/cost-line-items", methods=["POST"])
def create_cost_line():
    require_roles("ClaimsAdjuster")
    body = parse_body(required_fields=["damage_case_id", "category", "description", "quantity", "unit_cost_cents"])
    case = db.damage_cases.get(body["damage_case_id"])
    if case is None:
        raise err_not_found("damage case not found")
    category = require_enum(body["category"], ("LABOR", "MATERIAL", "EQUIPMENT", "RESTORATION"), "category")
    description = require_string(body["description"], "description")
    quantity = require_positive_number(body["quantity"], "quantity")
    unit_cost = require_positive_int(body["unit_cost_cents"], "unit_cost_cents")
    if case["investigation_status"] == "CLOSED":
        raise err_invalid_state("case is CLOSED")
    if case["recovery_status"] not in ("UNBILLED", "COSTING"):
        raise err_invalid_state("case recovery is already INVOICED or later")
    line_total = compute_line_total(category, quantity, unit_cost, case["severity"])
    now = clock.get_current_utc()
    lid = new_id()
    line = {
        "id": lid,
        "damage_case_id": case["id"],
        "category": category,
        "description": description,
        "quantity": quantity,
        "unit_cost_cents": unit_cost,
        "line_total_cents": line_total,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    db.cost_line_items[lid] = line
    if case["recovery_status"] == "UNBILLED":
        case["recovery_status"] = "COSTING"
    recompute_case_subtotal(case)
    touch(case)
    return success_envelope(cost_line_out(line), "object", 201)


@bp.route("/damage-recovery/cost-line-items/<lid>", methods=["GET"])
def get_cost_line(lid):
    require_roles(*ALL_ROLES)
    line = db.cost_line_items.get(lid)
    if line is None:
        raise err_not_found("cost line item not found")
    return success_envelope(cost_line_out(line), "object", 200)


@bp.route("/damage-recovery/cost-line-items", methods=["GET"])
def list_cost_lines():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.cost_line_items.values())
    case_id = request.args.get("damage_case_id")
    category = request.args.get("category")
    if case_id is not None:
        items = [e for e in items if e["damage_case_id"] == case_id]
    if category is not None:
        items = [e for e in items if e["category"] == category]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([cost_line_out(e) for e in page], "array", 200, meta)


@bp.route("/damage-recovery/cost-line-items/<lid>", methods=["DELETE"])
def delete_cost_line(lid):
    require_roles("ClaimsAdjuster")
    line = db.cost_line_items.get(lid)
    if line is None:
        raise err_not_found("cost line item not found")
    case = db.damage_cases.get(line["damage_case_id"])
    if case is None:
        raise err_not_found("damage case not found")
    if case["recovery_status"] != "COSTING":
        raise err_invalid_state("case recovery is not COSTING")
    del db.cost_line_items[lid]
    recompute_case_subtotal(case)
    touch(case)
    return success_envelope({}, "object", 204)
