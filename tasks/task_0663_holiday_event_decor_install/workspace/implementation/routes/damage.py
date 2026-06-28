"""DamageReport endpoints: open, assess, settle (fork), void."""
from flask import Blueprint, request

import errors
from db import db, base_fields, public, touch
from middleware import get_identity, require_role
from response import success, list_success
from validation import (get_json_body, require_str, require_int,
                        require_enum, parse_pagination, paginate)
from services.calculations import compute_damage_settlement

bp = Blueprint("damage", __name__)

RESOLUTION_PATHS = {"REPAIR", "RESTOCK"}


def _get_wo_or_404(wo_id):
    rec = db.work_orders.get(wo_id)
    if rec is None:
        raise errors.not_found("Work order not found")
    return rec


def _get_report_or_404(report_id):
    rec = db.damage_reports.get(report_id)
    if rec is None:
        raise errors.not_found("Damage report not found")
    return rec


@bp.post("/work-orders/<id>/damage-reports")
def open_report(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    _get_wo_or_404(id)
    body = get_json_body()
    inventory_item_id = require_str(body, "inventory_item_id")
    damaged_qty = require_int(body, "damaged_qty", minimum=1)
    if inventory_item_id not in db.inventory_items:
        raise errors.reference_not_found("inventory_item_id does not exist")

    rec = base_fields()
    rec.update({
        "work_order_id": id,
        "inventory_item_id": inventory_item_id,
        "damaged_qty": damaged_qty,
        "resolution_path": None,
        "replacement_cost_cents": None,
        "settlement_total_cents": None,
        "status": "OPEN",
    })
    db.damage_reports[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/work-orders/<id>/damage-reports")
def list_wo_reports(id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "PlatformAdmin"])
    _get_wo_or_404(id)
    limit, offset = parse_pagination()
    records = [r for r in db.damage_reports.values() if r["work_order_id"] == id]
    page, total = paginate(records, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/damage-reports/<id>")
def get_report(id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "PlatformAdmin"])
    rec = _get_report_or_404(id)
    return success(public(rec))


@bp.get("/damage-reports")
def list_reports():
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "PlatformAdmin"])
    limit, offset = parse_pagination()
    inventory_item_id = request.args.get("inventory_item_id")
    status = request.args.get("status")
    records = list(db.damage_reports.values())
    if inventory_item_id is not None:
        records = [r for r in records if r["inventory_item_id"] == inventory_item_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.post("/damage-reports/<id>/assess")
def assess_report(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    report = _get_report_or_404(id)
    body = get_json_body()
    resolution_path = require_enum(body, "resolution_path", RESOLUTION_PATHS)

    # state-machine guard (priority 8)
    if report["status"] != "OPEN":
        raise errors.invalid_state()

    # business: parent WO must be COMPLETED TAKEDOWN (priority 11)
    wo = db.work_orders.get(report["work_order_id"])
    if wo is None or wo["job_type"] != "TAKEDOWN" or wo["schedule_status"] != "COMPLETED":
        raise errors.damage_context_invalid()

    inventory_item = db.inventory_items.get(report["inventory_item_id"])
    contract = db.contracts.get(wo["contract_id"]) if wo else None

    replacement_cost, settlement_total = compute_damage_settlement(report, inventory_item, contract)
    report["resolution_path"] = resolution_path
    report["replacement_cost_cents"] = replacement_cost
    report["settlement_total_cents"] = settlement_total
    report["status"] = "ASSESSED"
    touch(report)
    return success(public(report))


@bp.post("/damage-reports/<id>/settle")
def settle_report(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    report = _get_report_or_404(id)
    if report["status"] != "ASSESSED":
        raise errors.invalid_state()

    if report["resolution_path"] == "RESTOCK":
        # CASCADE hop 2: mint a RestockOrder in REQUESTED
        ro = base_fields()
        ro.update({
            "damage_report_id": report["id"],
            "inventory_item_id": report["inventory_item_id"],
            "quantity": report["damaged_qty"],
            "status": "REQUESTED",
        })
        db.restock_orders[ro["id"]] = ro
        # CASCADE hop 3: decrement inventory on_hand_qty, floored at 0
        item = db.inventory_items.get(report["inventory_item_id"])
        if item is not None:
            item["on_hand_qty"] = max(0, item["on_hand_qty"] - report["damaged_qty"])
            touch(item)
    # REPAIR branch: no inventory movement.

    report["status"] = "SETTLED"
    touch(report)
    return success(public(report))


@bp.post("/damage-reports/<id>/void")
def void_report(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    report = _get_report_or_404(id)
    if report["status"] != "OPEN":
        raise errors.invalid_state()
    report["status"] = "VOID"
    touch(report)
    return success(public(report))
