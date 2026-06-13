"""WorkOrder routes (PRD §3.7) — open, get, list, assign, complete, cancel."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, require_int, optional_int, require_enum,
    optional_bool, optional_iso_date, parse_pagination, paginate, filter_param,
)
from services import domain

bp = Blueprint("work_orders", __name__)

CATEGORIES = {"PLUMBING", "ELECTRICAL", "HVAC", "APPLIANCE", "STRUCTURAL", "OTHER"}
PRIORITIES = {"EMERGENCY", "URGENT", "ROUTINE"}


@bp.route("/work-orders", methods=["POST"])
def create_work_order():
    require_role({"PropertyManager", "Tenant"})
    body = get_json_body()
    unit_id = require_string(body, "unit_id")
    category = require_enum(body, "category", CATEGORIES)
    description = require_string(body, "description")
    priority = require_enum(body, "priority", PRIORITIES, default="ROUTINE")
    estimate = optional_int(body, "estimate_cents", 0, minimum=0)
    charge_to_owner = optional_bool(body, "charge_to_owner", True)
    with db.LOCK:
        if unit_id not in db.units:
            raise err(errors.ERR_FK_NOT_FOUND, "unit_id does not resolve")
        common = db.new_common()
        record = {
            **{k: common[k] for k in ("id", "created_at", "updated_at", "version", "_seq")},
            "unit_id": unit_id,
            "category": category,
            "priority": priority,
            "description": description,
            "estimate_cents": estimate,
            "actual_cost_cents": None,
            "charge_to_owner": charge_to_owner,
            "completed_date": None,
            "status": "OPEN",
        }
        db.work_orders[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/work-orders/<id>", methods=["GET"])
def get_work_order(id):
    require_role({"PropertyManager", "Owner", "Tenant"})
    with db.LOCK:
        record = db.work_orders.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Work order not found")
        return object_response(serialize(record), 200)


@bp.route("/work-orders", methods=["GET"])
def list_work_orders():
    require_role({"PropertyManager", "Owner", "Tenant"})
    unit_id = filter_param(request.args, "unit_id")
    status = filter_param(request.args, "status")
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.work_orders.values())
        if unit_id is not None:
            records = [r for r in records if r["unit_id"] == unit_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/work-orders/<id>/assign", methods=["POST"])
def assign_work_order(id):
    require_role({"PropertyManager"})
    with db.LOCK:
        wo = db.work_orders.get(id)
        if wo is None:
            raise err(errors.ERR_NOT_FOUND, "Work order not found")
        if wo["status"] != "OPEN":
            raise err(errors.ERR_INVALID_STATE, "Work order is not OPEN")
        wo["status"] = "ASSIGNED"
        db.touch(wo)
        return object_response(serialize(wo), 200)


@bp.route("/work-orders/<id>/complete", methods=["POST"])
def complete_work_order(id):
    require_role({"PropertyManager"})
    body = get_json_body()
    with db.LOCK:
        wo = db.work_orders.get(id)
        if wo is None:
            raise err(errors.ERR_NOT_FOUND, "Work order not found")
        if wo["status"] != "ASSIGNED":
            raise err(errors.ERR_INVALID_STATE, "Work order is not ASSIGNED")
        # actual_cost_cents required (ERR_ACTUAL_COST_REQUIRED).
        if "actual_cost_cents" not in body or body["actual_cost_cents"] is None:
            raise err(errors.ERR_ACTUAL_COST_REQUIRED, "actual_cost_cents is required")
        actual_cost = require_int(body, "actual_cost_cents", minimum=0)
        completed_date = optional_iso_date(body, "completed_date")

        # Trust solvency (priority 14) is the last guard: debit before mutating
        # the work order so an insufficient trust leaves the order ASSIGNED.
        if wo["charge_to_owner"]:
            prop = domain.property_of_unit(db.units.get(wo["unit_id"]))
            if prop is not None:
                domain.debit_trust(prop, actual_cost)

        wo["actual_cost_cents"] = actual_cost
        wo["completed_date"] = completed_date
        wo["status"] = "COMPLETED"
        db.touch(wo)
        return object_response(serialize(wo), 200)


@bp.route("/work-orders/<id>/cancel", methods=["POST"])
def cancel_work_order(id):
    require_role({"PropertyManager"})
    with db.LOCK:
        wo = db.work_orders.get(id)
        if wo is None:
            raise err(errors.ERR_NOT_FOUND, "Work order not found")
        if wo["status"] not in ("OPEN", "ASSIGNED"):
            raise err(errors.ERR_INVALID_STATE, "Work order is not OPEN or ASSIGNED")
        wo["status"] = "CANCELLED"
        db.touch(wo)
        return object_response(serialize(wo), 200)
