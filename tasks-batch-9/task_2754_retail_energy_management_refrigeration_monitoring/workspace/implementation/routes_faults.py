"""Fault diagnostics, triage and maintenance execution (PRD 3.9)."""

from flask import Blueprint, g

import calc
import cascade
import common
import derive
import envelope
import serial
import validate as v
from common import (EQUIPMENT_CLASSES, SEVERITIES, TRIAGE_OUTCOMES,
                    WORK_ORDER_PRIORITIES, WORK_ORDER_STATES)
from db import db, new_row
from errors import ApiError
from security import (BMS_GATEWAY, MAINTENANCE_TECH, NON_GATEWAY_ROLES, roles)

bp = Blueprint("faults", __name__)


def _closed_overlap(new_start, new_end, other_start, other_end):
    """Work order windows are closed intervals for conflict detection."""
    return new_start <= other_end and other_start <= new_end


@bp.route("/stores/<store_id>/fault-diagnostics", methods=["POST"])
@roles(BMS_GATEWAY, MAINTENANCE_TECH)
def report_fault(store_id):
    body = v.body()
    equipment_ref = v.get_str(body, "equipment_ref", min_len=1)
    equipment_class = v.get_enum(body, "equipment_class", EQUIPMENT_CLASSES)
    fault_code = v.get_str(body, "fault_code", min_len=1)
    severity = v.get_enum(body, "severity", SEVERITIES)
    occurrence_count = v.get_int(body, "occurrence_count", min_=1)
    affected_load_kw = v.get_num(body, "affected_load_kw", 1, ge=0)
    store = common.get_store(store_id)
    common.require_bms_commissioned(store)
    fault = new_row(db.faults, {
        "store_id": store_id,
        "equipment_ref": equipment_ref,
        "equipment_class": equipment_class,
        "fault_code": fault_code,
        "severity": severity,
        "occurrence_count": occurrence_count,
        "affected_load_kw": affected_load_kw,
        "fault_score": calc.fault_score(severity, occurrence_count,
                                        affected_load_kw, equipment_class),
        "state": "DETECTED",
        "detected_at_iso": db.clock,
        "triaged_by_user_id": None,
    })
    return envelope.created(serial.fault(fault))


@bp.route("/fault-diagnostics/<fault_id>", methods=["GET"])
@roles(*(NON_GATEWAY_ROLES + [BMS_GATEWAY]))
def get_fault(fault_id):
    fault = common.get_fault(fault_id)
    return envelope.ok(serial.fault(fault))


@bp.route("/fault-diagnostics/<fault_id>/work-orders", methods=["GET"])
@roles(*NON_GATEWAY_ROLES)
def list_fault_work_orders(fault_id):
    limit, offset = v.query_pagination()
    state = v.query_enum("state", WORK_ORDER_STATES)
    priority = v.query_enum("priority", WORK_ORDER_PRIORITIES)
    common.get_fault(fault_id)
    items = derive.fault_work_orders(fault_id)
    items = common.apply_eq(items, "state", state)
    items = common.apply_eq(items, "priority", priority)
    return common.list_response(items, serial.work_order, limit, offset)


@bp.route("/fault-diagnostics/<fault_id>/triage", methods=["POST"])
@roles(MAINTENANCE_TECH)
def triage(fault_id):
    body = v.body()
    outcome = v.get_enum(body, "outcome", TRIAGE_OUTCOMES)
    fault = common.get_fault(fault_id)
    if fault["state"] != "DETECTED":
        raise ApiError("ERR_FAULT_STATE_INVALID")
    store = db.stores.get(fault["store_id"])
    work_order = None
    escalated = 0
    if outcome == "SUPPRESS":
        if fault["fault_score"] >= calc.SUPPRESSION_MAX_SCORE:
            raise ApiError("ERR_FAULT_SUPPRESSION_FORBIDDEN")
        fault["state"] = "SUPPRESSED"
        fault["triaged_by_user_id"] = g.user_id
        cascade.touch(fault)
    else:
        fault["state"] = "TRIAGED"
        fault["triaged_by_user_id"] = g.user_id
        cascade.touch(fault)
        urgent = fault["fault_score"] >= calc.WORK_ORDER_URGENT_THRESHOLD
        work_order = new_row(db.work_orders, {
            "fault_id": fault["id"],
            "priority": "URGENT" if urgent else "ROUTINE",
            "state": "OPEN",
            "scheduled_start_iso": None,
            "scheduled_end_iso": None,
            "completed_at_iso": None,
            "completion_note": None,
        })
        if urgent:
            cascade.touch(store)
            if (fault["equipment_class"] == "REFRIGERATION" and store is not None
                    and store["bms_status"] == "ACTIVE"):
                store["bms_status"] = "DEGRADED"
        result = cascade.recompute_posture(store)
        escalated = result["escalated_retrofit_count"]
    return envelope.ok({
        "fault_id": fault["id"],
        "fault_state": fault["state"],
        "fault_score": serial.q(fault["fault_score"], 1),
        "work_order_id": work_order["id"] if work_order else None,
        "work_order_priority": work_order["priority"] if work_order else None,
        "work_order_state": work_order["state"] if work_order else None,
        "store_bms_status": store["bms_status"] if store else None,
        "store_energy_posture": store["energy_posture"] if store else None,
        "urgent_work_order_count": (derive.urgent_work_order_count(store["id"])
                                    if store else 0),
        "escalated_retrofit_count": escalated,
    })


@bp.route("/work-orders/<work_order_id>/schedule", methods=["POST"])
@roles(MAINTENANCE_TECH)
def schedule_work_order(work_order_id):
    body = v.body()
    start = v.get_dt(body, "scheduled_start_iso")
    end = v.get_dt(body, "scheduled_end_iso")
    v.window(start, end, "scheduled_start_iso", "scheduled_end_iso")
    work_order = common.get_work_order(work_order_id)
    if work_order["state"] == "COMPLETED":
        raise ApiError("ERR_WORK_ORDER_STATE_INVALID")
    fault = derive.fault_of_work_order(work_order)
    equipment_ref = fault["equipment_ref"] if fault is not None else None
    store = derive.store_of_work_order(work_order)
    for other in derive._by_created(list(db.work_orders.values())):
        if other["id"] == work_order["id"] or other["state"] != "SCHEDULED":
            continue
        other_fault = derive.fault_of_work_order(other)
        if other_fault is None or other_fault["equipment_ref"] != equipment_ref:
            continue
        if _closed_overlap(start, end, other["scheduled_start_iso"],
                           other["scheduled_end_iso"]):
            raise ApiError("ERR_WORK_ORDER_WINDOW_CONFLICT")
    if store is not None:
        overlapping = 0
        for other in derive.store_work_orders(store["id"]):
            if other["id"] == work_order["id"] or other["state"] != "SCHEDULED":
                continue
            if _closed_overlap(start, end, other["scheduled_start_iso"],
                               other["scheduled_end_iso"]):
                overlapping += 1
        if overlapping >= calc.WORK_ORDER_STORE_CAPACITY:
            raise ApiError("ERR_WORK_ORDER_CAPACITY_EXCEEDED")
    work_order["scheduled_start_iso"] = start
    work_order["scheduled_end_iso"] = end
    work_order["state"] = "SCHEDULED"
    cascade.touch(work_order)
    return envelope.ok(serial.work_order(work_order))


@bp.route("/work-orders/<work_order_id>/complete", methods=["POST"])
@roles(MAINTENANCE_TECH)
def complete_work_order(work_order_id):
    body = v.body()
    note = v.get_str(body, "completion_note", min_len=1)
    work_order = common.get_work_order(work_order_id)
    if work_order["state"] not in ("OPEN", "SCHEDULED"):
        raise ApiError("ERR_WORK_ORDER_STATE_INVALID")
    work_order["state"] = "COMPLETED"
    work_order["completed_at_iso"] = db.clock
    work_order["completion_note"] = note
    cascade.touch(work_order)
    fault = derive.fault_of_work_order(work_order)
    if fault is not None and fault["state"] == "TRIAGED":
        fault["state"] = "RESOLVED"
        cascade.touch(fault)
    store = derive.store_of_work_order(work_order)
    if work_order["priority"] == "URGENT":
        cascade.touch(store)
    cascade.recompute_posture(store)
    return envelope.ok(serial.work_order(work_order))
