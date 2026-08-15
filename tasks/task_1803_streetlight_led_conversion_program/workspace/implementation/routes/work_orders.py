"""WorkOrder endpoints (PRD 3.4): dispatch gates, completion cascade, QC."""
from flask import Blueprint

from db import new_record, store, touch
from domain import (
    bump_program, compute_labor_cost, evaluate_auto_close, post_budget,
    program_of_work_order, require_active, rerate_estimated_lines_for_pole,
    ser_work_order,
)
from errors import raise_error
from middleware import ALL_ROLES, get_caller, locked, require_roles
from response import success_object
from util import CLOCK
from validate import get_body, req_enum, req_int
from routes.common import list_endpoint, require_record

bp = Blueprint("work_orders", __name__)

FS = ["FieldSupervisor"]
PM = ["ProgramManager"]
QA = ["QaInspector"]
SHIELDINGS = ["FULL_CUTOFF", "SEMI_CUTOFF", "NONE"]


def _wo_sort_key(wo):
    route = store.routes.get(wo["route_id"]) if wo["route_id"] else None
    window = route["window_start_date"] if route else None
    stop = store.stops.get(wo["stop_id"]) if wo["stop_id"] else None
    seq = stop["sequence_number"] if stop else None
    return (window is None, window or "", seq is None, seq or 0, wo["_seq"])


@bp.route("/streetlights/work-orders", methods=["GET"])
@locked
def list_work_orders():
    return list_endpoint(
        "work_orders", ser_work_order,
        ["route_id", "pole_id", "crew_id", "stop_id", "ticket_id",
         "execution_status", "qc_status"],
        sort_key=_wo_sort_key)


@bp.route("/streetlights/work-orders/<wid>", methods=["GET"])
@locked
def get_work_order(wid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("work_orders", wid, "ERR_WORK_ORDER_NOT_FOUND")
    return success_object(ser_work_order(rec))


def _valid_cct_waiver(pole_id, new_cct):
    """An APPROVED CCT_WAIVER covers the request when its ceiling reaches the
    requested value and valid_until has not passed on the logical clock
    (dispatch-time evaluation does not wait for refresh materialization)."""
    today = CLOCK.today()
    for e in store.exceptions.values():
        if (e["pole_id"] == pole_id and e["exception_kind"] == "CCT_WAIVER"
                and e["status"] == "APPROVED"
                and e["requested_cct_kelvin"] is not None
                and e["requested_cct_kelvin"] >= new_cct
                and e["valid_until"] >= str(today)):
            return True
    return False


@bp.route("/streetlights/work-orders/<wid>/dispatch", methods=["POST"])
@locked
def dispatch_work_order(wid):
    caller = get_caller()
    body = get_body()
    new_wattage = req_int(body, "new_fixture_wattage", positive=True)
    new_cct = req_int(body, "new_cct_kelvin", positive=True)
    shielding = req_enum(body, "shielding", SHIELDINGS)
    require_roles(caller, FS)
    wo = require_record("work_orders", wid, "ERR_WORK_ORDER_NOT_FOUND")
    # Stage 5 ownership: FieldSupervisor X-User-ID is the acting Crew id.
    if caller.user_id != wo["crew_id"]:
        raise_error("ERR_FORBIDDEN", "acting crew does not match the work order's crew")
    program = program_of_work_order(wo)
    require_active(program)
    # Stage 9: target state first, then route, then stop.
    if wo["execution_status"] not in ("PENDING", "REWORK_PENDING"):
        raise_error("ERR_WORK_ORDER_NOT_DISPATCHABLE",
                    "dispatch requires execution_status PENDING or REWORK_PENDING")
    from_rework = wo["execution_status"] == "REWORK_PENDING"
    route = store.routes.get(wo["route_id"]) if wo["route_id"] else None
    if route is not None and route["status"] == "SUSPENDED":
        raise_error("ERR_ROUTE_SUSPENDED", "route is SUSPENDED")
    # The linked-stop gate guards a first dispatch; on a rework dispatch the
    # stop is already COMPLETE and the order re-executes against it.
    stop = store.stops.get(wo["stop_id"]) if wo["stop_id"] else None
    if not from_rework and stop is not None and stop["status"] != "PENDING":
        raise_error("ERR_STOP_BLOCKED", "linked stop is not PENDING")
    pole = store.poles[wo["pole_id"]]
    district = store.districts[pole["district_id"]]
    # Stage 10: dark-sky CCT, then shielding.
    if new_cct > district["cct_cap_kelvin"] and not _valid_cct_waiver(pole["id"], new_cct):
        raise_error("ERR_CCT_EXCEEDS_ZONE_CAP", "new_cct_kelvin exceeds the district CCT cap")
    if district["full_cutoff_required"] and shielding != "FULL_CUTOFF":
        raise_error("ERR_SHIELDING_REQUIRED", "district requires FULL_CUTOFF shielding")
    # Stage 12: exclusivity, then wattage reduction.
    for other in store.work_orders.values():
        if (other["id"] != wo["id"] and other["pole_id"] == wo["pole_id"]
                and other["execution_status"] == "DISPATCHED"):
            raise_error("ERR_ACTIVE_WORK_ORDER_EXISTS",
                        "another DISPATCHED work order exists for this pole")
    if new_wattage * 5 > pole["effective_wattage"] * 4:
        raise_error("ERR_INSUFFICIENT_WATTAGE_REDUCTION",
                    "new fixture must be at most 80% of effective wattage")
    # Stage 14: fiscal gate.
    if wo["estimated_labor_cost_cents"] > program["budget_balance_cents"]:
        raise_error("ERR_PROGRAM_BUDGET_EXCEEDED",
                    "estimated labor cost exceeds the program budget balance")
    # Side effects.
    wo["new_fixture_wattage"] = new_wattage
    wo["new_cct_kelvin"] = new_cct
    wo["shielding"] = shielding
    wo["execution_status"] = "DISPATCHED"
    touch(wo)
    if not from_rework:
        post_budget(program, -wo["estimated_labor_cost_cents"])
        bump_program(program)
    if route is not None and route["status"] == "RELEASED":
        route["status"] = "IN_PROGRESS"
        touch(route)
    return success_object(ser_work_order(wo))


@bp.route("/streetlights/work-orders/<wid>/complete", methods=["POST"])
@locked
def complete_work_order(wid):
    caller = get_caller()
    require_roles(caller, FS)
    wo = require_record("work_orders", wid, "ERR_WORK_ORDER_NOT_FOUND")
    if caller.user_id != wo["crew_id"]:
        raise_error("ERR_FORBIDDEN", "acting crew does not match the work order's crew")
    program = program_of_work_order(wo)
    require_active(program)
    if wo["execution_status"] != "DISPATCHED":
        raise_error("ERR_WORK_ORDER_NOT_COMPLETABLE", "complete requires a DISPATCHED work order")
    crew = store.crews[wo["crew_id"]]
    pole = store.poles[wo["pole_id"]]
    completed_dt = CLOCK.now()
    first_completion = not wo["est_reconciled"]

    wo["execution_status"] = "COMPLETED"
    wo["qc_status"] = "AWAITING_QC"
    wo["completed_at"] = CLOCK.now_iso()
    wo["_completed_dt"] = completed_dt
    wo["performed_by_user_id"] = caller.user_id
    labor, prev, excess = compute_labor_cost(wo, crew, completed_dt)
    wo["labor_cost_cents"] = labor
    wo["cumulative_week_minutes_before"] = prev
    wo["overtime_minutes"] = excess
    # Ledger reconciliation (PRD 2.5).
    if first_completion:
        post_budget(program, -(labor - wo["estimated_labor_cost_cents"]))
        wo["est_reconciled"] = True
    else:
        post_budget(program, -labor)
    touch(wo)

    # Pole cascade: conversion orders move the pole; replacements refresh
    # wattage/date but leave the pole UNDER_REPAIR pending QC.
    if pole["pre_conversion_wattage"] is None:
        pole["pre_conversion_wattage"] = pole["effective_wattage"]
    pole["led_wattage"] = wo["new_fixture_wattage"]
    pole["led_in_service_date"] = completed_dt.date().isoformat()
    if not wo["is_replacement"]:
        if pole["status"] in ("SCHEDULED", "REWORK"):
            pole["status"] = "CONVERTED"
    touch(pole)

    # Exactly one salvage item per work order, at its first completion.
    if first_completion:
        new_record("salvage_items", {
            "batch_id": None,
            "pole_id": pole["id"],
            "fixture_class": pole["fixture_class"],
            "weight_lbs": 0.0,
            "mercury_flag": False,
        })

    rerate_estimated_lines_for_pole(pole)

    route = None
    if wo["stop_id"]:
        stop = store.stops.get(wo["stop_id"])
        if stop is not None and stop["status"] == "PENDING":
            stop["status"] = "COMPLETE"
            touch(stop)
        route = store.routes.get(stop["route_id"]) if stop else None
    elif wo["route_id"]:
        route = store.routes.get(wo["route_id"])
    if route is not None:
        evaluate_auto_close(route)
    bump_program(program)
    return success_object(ser_work_order(wo))


@bp.route("/streetlights/work-orders/<wid>/fail", methods=["POST"])
@locked
def fail_work_order(wid):
    caller = get_caller()
    require_roles(caller, FS)
    wo = require_record("work_orders", wid, "ERR_WORK_ORDER_NOT_FOUND")
    if caller.user_id != wo["crew_id"]:
        raise_error("ERR_FORBIDDEN", "acting crew does not match the work order's crew")
    require_active(program_of_work_order(wo))
    if wo["execution_status"] != "DISPATCHED":
        raise_error("ERR_WORK_ORDER_NOT_COMPLETABLE", "fail requires a DISPATCHED work order")
    # DISPATCHED -> FAILED -> PENDING: the automatic retry is immediate, so the
    # observable end state is PENDING; no money moves (estimate outstanding).
    wo["execution_status"] = "PENDING"
    touch(wo)
    return success_object(ser_work_order(wo))


@bp.route("/streetlights/work-orders/<wid>/cancel", methods=["POST"])
@locked
def cancel_work_order(wid):
    caller = get_caller()
    require_roles(caller, PM)
    wo = require_record("work_orders", wid, "ERR_WORK_ORDER_NOT_FOUND")
    program = program_of_work_order(wo)
    require_active(program)
    origin = wo["execution_status"]
    if origin not in ("PENDING", "DISPATCHED", "REWORK_PENDING"):
        raise_error("ERR_WORK_ORDER_NOT_CANCELLABLE",
                    "cancel requires PENDING, DISPATCHED, or REWORK_PENDING")
    if origin == "DISPATCHED" and not wo["est_reconciled"]:
        post_budget(program, wo["estimated_labor_cost_cents"])
    if wo["stop_id"]:
        stop = store.stops.get(wo["stop_id"])
        if stop is not None and stop["status"] == "PENDING":
            stop["status"] = "SKIPPED"
            touch(stop)
    pole = store.poles.get(wo["pole_id"])
    if origin in ("PENDING", "DISPATCHED"):
        if pole is not None and pole["status"] == "SCHEDULED":
            pole["status"] = "AUDIT_CLEARED"
            touch(pole)
    # From REWORK_PENDING the pole stays REWORK: a converted pole never reverts.
    wo["execution_status"] = "CANCELLED"
    touch(wo)
    if wo["route_id"]:
        route = store.routes.get(wo["route_id"])
        if route is not None:
            evaluate_auto_close(route)
    return success_object(ser_work_order(wo))


def _qc_gate(caller, wo):
    """Stage 6 SoD then stage 9 state, per the PRD 2.10 pipeline."""
    if wo["performed_by_user_id"] is not None and caller.user_id == wo["performed_by_user_id"]:
        raise_error("ERR_SEGREGATION_OF_DUTIES", "the completer may not decide QC")
    if wo["execution_status"] != "COMPLETED" or wo["qc_status"] != "AWAITING_QC":
        raise_error("ERR_QC_NOT_AWAITING", "QC requires a COMPLETED work order AWAITING_QC")


@bp.route("/streetlights/work-orders/<wid>/qc-pass", methods=["POST"])
@locked
def qc_pass_work_order(wid):
    caller = get_caller()
    require_roles(caller, QA)
    wo = require_record("work_orders", wid, "ERR_WORK_ORDER_NOT_FOUND")
    require_active(program_of_work_order(wo))
    _qc_gate(caller, wo)
    wo["qc_status"] = "QC_PASSED"
    wo["qc_by_user_id"] = caller.user_id
    touch(wo)
    pole = store.poles.get(wo["pole_id"])
    route = None
    if wo["is_replacement"]:
        # UNDER_REPAIR -> pre_repair_status mapping; clear the marker either way.
        if pole is not None and pole["status"] == "UNDER_REPAIR":
            pre = pole["pre_repair_status"]
            if pre == "SCHEDULED":
                pole["status"] = "SCHEDULED"
                for s in store.stops.values():
                    if s["pole_id"] == pole["id"] and s["status"] == "BLOCKED":
                        s["status"] = "PENDING"
                        touch(s)
                        route = store.routes.get(s["route_id"])
            else:
                pole["status"] = "VERIFIED"
            pole["pre_repair_status"] = None
            touch(pole)
    else:
        if pole is not None and pole["status"] == "CONVERTED":
            pole["status"] = "VERIFIED"
            touch(pole)
        if wo["route_id"]:
            route = store.routes.get(wo["route_id"])
    if route is not None:
        evaluate_auto_close(route)
    return success_object(ser_work_order(wo))


@bp.route("/streetlights/work-orders/<wid>/qc-fail", methods=["POST"])
@locked
def qc_fail_work_order(wid):
    caller = get_caller()
    require_roles(caller, QA)
    wo = require_record("work_orders", wid, "ERR_WORK_ORDER_NOT_FOUND")
    require_active(program_of_work_order(wo))
    _qc_gate(caller, wo)
    wo["qc_status"] = "QC_FAILED"
    wo["qc_by_user_id"] = caller.user_id
    wo["execution_status"] = "REWORK_PENDING"
    touch(wo)
    if not wo["is_replacement"]:
        pole = store.poles.get(wo["pole_id"])
        if pole is not None and pole["status"] == "CONVERTED":
            pole["status"] = "REWORK"
            touch(pole)
    return success_object(ser_work_order(wo))
