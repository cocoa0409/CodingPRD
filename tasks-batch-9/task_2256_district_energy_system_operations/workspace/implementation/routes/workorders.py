"""WorkOrder endpoints, the permit sweep and the isolation cascades (PRD 3.8)."""

from flask import Blueprint, g

import calc
import enums
import services as svc
from db import base_record, now, store, touch
from errors import fail
from middleware import ALL_STAFF, endpoint, paginate
from validators import (bad, get_bool, get_dt, get_enum, get_str, json_body,
                        present, query_enum, query_str)

bp = Blueprint("workorders", __name__, url_prefix="/district-energy")

OPEN_WORK_STATES = ("PERMIT_PENDING", "SCHEDULED", "EXCAVATING", "REPAIRING",
                    "BACKFILLED")
CANCELLABLE = ("DRAFT", "PERMIT_PENDING", "SCHEDULED")


def _optional_note(body, name):
    if present(body, name):
        get_str(body, name, min_len=0)


@endpoint(bp, "/work-orders", ["POST"], ["FieldTechnician"], status=201)
def create_work_order():
    body = json_body()
    segment_id = get_str(body, "segment_id")
    loop_id = get_str(body, "loop_id")
    work_type = get_enum(body, "work_type", enums.WORK_TYPE)
    start_raw, start_dt = get_dt(body, "window_start")
    end_raw, end_dt = get_dt(body, "window_end")
    requires_isolation = get_bool(body, "requires_isolation", required=False,
                                  default=False)
    if not end_dt > start_dt:
        bad("window_end must be after window_start")

    # Body foreign keys resolve in ladder order: loop_id before segment_id.
    loop = svc.fk_get("loops", loop_id)
    segment = svc.fk_get("segments", segment_id)

    if segment["loop_id"] != loop["id"]:
        fail("ERR_SEGMENT_LOOP_MISMATCH",
             "the segment belongs to loop '%s'" % segment["loop_id"])

    order = base_record()
    order.update({
        "segment_id": segment["id"],
        "loop_id": loop["id"],
        "work_type": work_type,
        "window_start": start_raw,
        "_window_start": start_dt,
        "window_end": end_raw,
        "_window_end": end_dt,
        "requires_isolation": requires_isolation,
        "reported_by_user_id": g.user_id,
        "completed_by_user_id": None,
        "permit_decision": "PENDING",
        "work_state": "DRAFT",
    })
    store.work_orders[order["id"]] = order
    return order


@endpoint(bp, "/work-orders", ["GET"], ALL_STAFF)
def list_work_orders():
    filters = {}
    segment_id = query_str("segment_id")
    loop_id = query_str("loop_id")
    work_state = query_enum("work_state", enums.WORK_STATE)
    work_type = query_enum("work_type", enums.WORK_TYPE)
    if segment_id is not None:
        filters["segment_id"] = segment_id
    if loop_id is not None:
        filters["loop_id"] = loop_id
    if work_state is not None:
        filters["work_state"] = work_state
    if work_type is not None:
        filters["work_type"] = work_type
    return paginate(svc.where("work_orders", **filters))


@endpoint(bp, "/work-orders/<work_order_id>", ["GET"], ALL_STAFF)
def get_work_order(work_order_id):
    return svc.path_get("work_orders", work_order_id)


@endpoint(bp, "/work-orders/<work_order_id>/submit-permit", ["POST"],
          ["FieldTechnician"])
def submit_permit(work_order_id):
    order = svc.path_get("work_orders", work_order_id)
    if order["work_state"] != "DRAFT":
        fail("ERR_WORK_ORDER_STATE_INVALID",
             "only a DRAFT work order can be submitted for a permit")

    peers = [w for w in svc.rows("work_orders")
             if w["segment_id"] == order["segment_id"] and w["id"] != order["id"]
             and w["work_state"] in OPEN_WORK_STATES]
    if calc.work_window_conflict(order, peers):
        fail("ERR_WORK_WINDOW_CONFLICT",
             "the requested window overlaps another open work order on this segment")

    order["work_state"] = "PERMIT_PENDING"
    order["permit_decision"] = "PENDING"
    touch(order)
    return order


@endpoint(bp, "/work-orders/<work_order_id>/permit-decision", ["POST"],
          ["NetworkEngineer"])
def permit_decision(work_order_id):
    body = json_body()
    decision = get_enum(body, "permit_decision", enums.PERMIT_CHOICE)
    _optional_note(body, "decision_note")

    order = svc.path_get("work_orders", work_order_id)
    if order["work_state"] != "PERMIT_PENDING":
        fail("ERR_WORK_ORDER_STATE_INVALID",
             "only a PERMIT_PENDING work order can receive a permit decision")

    order["permit_decision"] = decision
    order["work_state"] = "SCHEDULED" if decision == "GRANTED" else "DRAFT"
    touch(order)
    return order


@endpoint(bp, "/work-orders/<work_order_id>/begin-excavation", ["POST"],
          ["FieldTechnician"])
def begin_excavation(work_order_id):
    order = svc.path_get("work_orders", work_order_id)
    if order["work_state"] != "SCHEDULED" or order["permit_decision"] != "GRANTED":
        fail("ERR_WORK_ORDER_STATE_INVALID",
             "excavation requires a SCHEDULED work order with a granted permit")

    loop = store.loops.get(order["loop_id"])
    if order["requires_isolation"]:
        committed = [p for p in store.plans.values()
                     if p["loop_id"] == order["loop_id"]
                     and p["plan_state"] == "COMMITTED"]
        if committed:
            fail("ERR_ISOLATION_CLEARANCE_DENIED",
                 "a COMMITTED dispatch plan still holds the loop")

    moment = now()
    if moment < order["_window_start"] or moment > order["_window_end"]:
        fail("ERR_OUTSIDE_WORK_WINDOW",
             "the logical clock sits outside the approved work window")

    order["work_state"] = "EXCAVATING"
    touch(order)

    segment = store.segments.get(order["segment_id"])
    if segment is not None and segment["condition"] != "UNDER_REPAIR":
        was_suspect = segment["condition"] == "SUSPECT"
        segment["condition"] = "UNDER_REPAIR"
        touch(segment)
        if was_suspect and loop is not None:
            loop["suspect_segment_count"] = loop["suspect_segment_count"] - 1
            touch(loop)

    if order["requires_isolation"] and loop is not None:
        loop["posture"] = "ISOLATED"
        loop["open_isolation_count"] = loop["open_isolation_count"] + 1
        touch(loop)

    return order


@endpoint(bp, "/work-orders/<work_order_id>/begin-repair", ["POST"],
          ["FieldTechnician"])
def begin_repair(work_order_id):
    order = svc.path_get("work_orders", work_order_id)
    if order["work_state"] != "EXCAVATING":
        fail("ERR_WORK_ORDER_STATE_INVALID",
             "only an EXCAVATING work order can move to repair")
    order["work_state"] = "REPAIRING"
    touch(order)
    return order


@endpoint(bp, "/work-orders/<work_order_id>/backfill", ["POST"], ["FieldTechnician"])
def backfill(work_order_id):
    order = svc.path_get("work_orders", work_order_id)
    if order["work_state"] != "REPAIRING":
        fail("ERR_WORK_ORDER_STATE_INVALID",
             "only a REPAIRING work order can be backfilled")
    order["work_state"] = "BACKFILLED"
    touch(order)
    return order


@endpoint(bp, "/work-orders/<work_order_id>/complete", ["POST"], ["FieldTechnician"])
def complete_work_order(work_order_id):
    body = json_body()
    _optional_note(body, "completion_note")

    order = svc.path_get("work_orders", work_order_id)
    if order["work_state"] != "BACKFILLED":
        fail("ERR_WORK_ORDER_STATE_INVALID",
             "only a BACKFILLED work order can be completed")
    if g.user_id == order["reported_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the completing technician must differ from the reporter")

    order["work_state"] = "COMPLETED"
    order["completed_by_user_id"] = g.user_id
    touch(order)

    loop = store.loops.get(order["loop_id"])
    segment = store.segments.get(order["segment_id"])
    if segment is not None:
        segment["makeup_water_ratio"] = 0.0
        if order["work_type"] == "LEAK_REPAIR":
            segment["historical_leak_count"] = segment["historical_leak_count"] + 1
        score = calc.segment_leak_risk_score(segment, now().year)
        svc.apply_band(segment, score, loop)

    if order["requires_isolation"] and loop is not None:
        remaining = loop["open_isolation_count"] - 1
        loop["open_isolation_count"] = remaining if remaining > 0 else 0
        if loop["posture"] == "ISOLATED" and loop["open_isolation_count"] == 0:
            loop["posture"] = ("NORMAL" if loop["suspect_segment_count"] == 0
                               else "CONSTRAINED")
        touch(loop)

    return order


@endpoint(bp, "/work-orders/<work_order_id>/cancel", ["POST"], ["FieldTechnician"])
def cancel_work_order(work_order_id):
    body = json_body()
    _optional_note(body, "reason")

    order = svc.path_get("work_orders", work_order_id)
    if order["work_state"] not in CANCELLABLE:
        fail("ERR_WORK_ORDER_STATE_INVALID",
             "a '%s' work order cannot be cancelled" % order["work_state"])
    order["work_state"] = "CANCELLED"
    touch(order)
    return order
