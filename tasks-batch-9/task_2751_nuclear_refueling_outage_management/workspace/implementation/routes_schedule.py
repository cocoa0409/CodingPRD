"""Schedule development, the activity chain and safety-function protection (PRD 3.4)."""
from flask import Blueprint, request

import lookup
import projections
from auth import ALL_ROLES, authorize
from calc import dec
from clock import clock
from db import all_rows, store, touch
from errors import api_error
from response import ok, paginated, parse_pagination
from serializers import serialize
from validators import F, bad, body, no_body

bp = Blueprint("schedule", __name__)


def _windows_overlap_closed(start_a, end_a, start_b, end_b):
    """Closed intervals: windows that merely touch at an endpoint DO conflict."""
    return start_a <= end_b and start_b <= end_a


def _check_safety_capacity(function, incoming_start, incoming_duration,
                           incoming_label, exclude_activity_id):
    incoming_end = incoming_start + incoming_duration
    labels = set([incoming_label])
    # The aggregate spans ALL outages: a safety function is a shared plant asset.
    for other in all_rows(store.schedule_activities):
        if other["id"] == exclude_activity_id:
            continue
        if other["oos_safety_function_id"] != function["id"]:
            continue
        if other["execution_status"] == "CANCELLED":
            continue
        other_start = dec(other["planned_start_offset_hours"])
        other_end = other_start + dec(other["planned_duration_hours"])
        if _windows_overlap_closed(incoming_start, incoming_end, other_start, other_end):
            labels.add(other["oos_train_label"])
    if len(labels) > function["max_concurrent_oos_trains"]:
        raise api_error("ERR_SAFETY_FUNCTION_CAPACITY_EXCEEDED",
                        "The aggregate out-of-service train count exceeds capacity.")


def _closes_cycle(activity_id, predecessor_id):
    seen = set()
    node = predecessor_id
    while node is not None:
        if node == activity_id or node in seen:
            return True
        seen.add(node)
        row = store.schedule_activities.get(node)
        node = row["predecessor_activity_id"] if row is not None else None
    return False


# ---------------------------------------------------------------------------
# POST /outages/{id}/schedule-activities
# ---------------------------------------------------------------------------
@bp.route("/outages/<outage_id>/schedule-activities", methods=["POST"])
@authorize("OutagePlanner")
def create_schedule_activity(outage_id):
    outage = lookup.outage(outage_id)
    payload = body([
        F("label", "str", min_len=1, max_len=200),
        F("planned_start_offset_hours", "num", ge=0),
        F("planned_duration_hours", "num", gt=0),
        F("work_order_id", "str", required=False, default=None, nullable=True),
        F("predecessor_activity_id", "str", required=False, default=None, nullable=True),
        F("oos_safety_function_id", "str", required=False, default=None, nullable=True),
        F("oos_train_label", "str", required=False, default=None, nullable=True,
          min_len=1, max_len=8),
    ])
    if payload["oos_safety_function_id"] is not None and payload["oos_train_label"] is None:
        raise bad("oos_train_label is required when oos_safety_function_id is supplied.")

    function = None
    if payload["oos_safety_function_id"] is not None:
        function = lookup.safety_function(payload["oos_safety_function_id"])
    work_order = None
    if payload["work_order_id"] is not None:
        work_order = lookup.work_order(payload["work_order_id"])
    predecessor = None
    if payload["predecessor_activity_id"] is not None:
        predecessor = lookup.schedule_activity(payload["predecessor_activity_id"])

    if function is not None:
        _check_safety_capacity(function,
                               dec(payload["planned_start_offset_hours"]),
                               dec(payload["planned_duration_hours"]),
                               payload["oos_train_label"], None)

    if predecessor is not None and predecessor["outage_id"] != outage["id"]:
        raise api_error("ERR_PREDECESSOR_OUTAGE_MISMATCH",
                        "The predecessor belongs to a different outage.")
    if work_order is not None and work_order["outage_id"] != outage["id"]:
        raise api_error("ERR_PREDECESSOR_OUTAGE_MISMATCH",
                        "The work order belongs to a different outage.")

    if predecessor is not None and _closes_cycle(None, predecessor["id"]):
        raise api_error("ERR_ACTIVITY_CYCLE", "The predecessor chain closes a loop.")

    activity = projections.mint_activity(
        outage,
        payload["label"],
        payload["planned_start_offset_hours"],
        payload["planned_duration_hours"],
        work_order_id=payload["work_order_id"],
        predecessor_activity_id=payload["predecessor_activity_id"],
        oos_safety_function_id=payload["oos_safety_function_id"],
        oos_train_label=payload["oos_train_label"],
    )
    projections.recompute_critical_path(outage)
    projections.recompute_schedule_posture(outage)
    return ok(serialize(activity), 201)


@bp.route("/schedule-activities/<row_id>", methods=["GET"])
@authorize(*ALL_ROLES)
def get_schedule_activity(row_id):
    return ok(serialize(lookup.schedule_activity(row_id)))


@bp.route("/schedule-activities", methods=["GET"])
@authorize(*ALL_ROLES)
def list_schedule_activities():
    limit, offset = parse_pagination(request.args)
    rows = all_rows(store.schedule_activities)
    for key in ("outage_id", "work_order_id", "predecessor_activity_id",
                "oos_safety_function_id", "execution_status", "constraint_status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r[key] == wanted]
    return paginated(rows, limit, offset, serialize)


# ---------------------------------------------------------------------------
# POST /schedule-activities/{id}/set-predecessor
# ---------------------------------------------------------------------------
@bp.route("/schedule-activities/<row_id>/set-predecessor", methods=["POST"])
@authorize("OutagePlanner")
def set_predecessor(row_id):
    activity = lookup.schedule_activity(row_id)
    payload = body([F("predecessor_activity_id", "str", nullable=True)])
    predecessor = None
    if payload["predecessor_activity_id"] is not None:
        predecessor = lookup.schedule_activity(payload["predecessor_activity_id"])
    if activity["execution_status"] != "NOT_STARTED":
        raise api_error("ERR_ACTIVITY_STATE_INVALID",
                        "Re-sequencing requires the activity to be in NOT_STARTED.")
    if predecessor is not None and predecessor["outage_id"] != activity["outage_id"]:
        raise api_error("ERR_PREDECESSOR_OUTAGE_MISMATCH",
                        "The predecessor belongs to a different outage.")
    if predecessor is not None and _closes_cycle(activity["id"], predecessor["id"]):
        raise api_error("ERR_ACTIVITY_CYCLE", "The predecessor chain closes a loop.")

    activity["predecessor_activity_id"] = (predecessor["id"]
                                           if predecessor is not None else None)
    activity["constraint_status"] = projections.constraint_status_for(predecessor)
    touch(activity)

    outage = store.outages[activity["outage_id"]]
    projections.recompute_critical_path(outage)
    projections.recompute_schedule_posture(outage)
    touch(outage)
    return ok(serialize(activity))


# ---------------------------------------------------------------------------
# NOT_STARTED -> IN_PROGRESS
# ---------------------------------------------------------------------------
@bp.route("/schedule-activities/<row_id>/start", methods=["POST"])
@authorize("OutagePlanner")
def start_activity(row_id):
    activity = lookup.schedule_activity(row_id)
    no_body()
    if activity["execution_status"] != "NOT_STARTED":
        raise api_error("ERR_ACTIVITY_STATE_INVALID",
                        "Starting requires the activity to be in NOT_STARTED.")
    if activity["constraint_status"] != "CLEAR":
        raise api_error("ERR_PREDECESSOR_NOT_COMPLETE",
                        "The activity's logic predecessor has not completed.")
    outage = store.outages[activity["outage_id"]]
    if outage["status"] != "EXECUTION":
        raise api_error("ERR_OUTAGE_STATE_INVALID",
                        "Activities become startable only once the outage is in EXECUTION.")
    work_order = None
    if activity["work_order_id"] is not None:
        work_order = store.work_orders[activity["work_order_id"]]
        if work_order["status"] not in ("APPROVED", "EXECUTING"):
            raise api_error("ERR_WORK_ORDER_NOT_APPROVED",
                            "The activity's work order is not approved.")

    activity["execution_status"] = "IN_PROGRESS"
    activity["started_at"] = clock.now_iso()
    touch(activity)
    if work_order is not None and work_order["status"] == "APPROVED":
        work_order["status"] = "EXECUTING"
        touch(work_order)
    return ok(serialize(activity))


# ---------------------------------------------------------------------------
# IN_PROGRESS -> COMPLETE
# ---------------------------------------------------------------------------
@bp.route("/schedule-activities/<row_id>/complete", methods=["POST"])
@authorize("OutagePlanner")
def complete_activity(row_id):
    activity = lookup.schedule_activity(row_id)
    no_body()
    if activity["execution_status"] != "IN_PROGRESS":
        raise api_error("ERR_ACTIVITY_STATE_INVALID",
                        "Completion requires the activity to be in IN_PROGRESS.")
    activity["execution_status"] = "COMPLETE"
    activity["completed_at"] = clock.now_iso()
    touch(activity)

    outage = store.outages[activity["outage_id"]]
    for successor in projections.activities_of_outage(outage["id"]):
        if successor["predecessor_activity_id"] == activity["id"]:
            if successor["constraint_status"] != "CLEAR":
                successor["constraint_status"] = "CLEAR"
                touch(successor)

    if activity["work_order_id"] is not None:
        projections.maybe_complete_work_order(
            store.work_orders[activity["work_order_id"]])

    projections.recompute_critical_path(outage)
    projections.recompute_schedule_posture(outage)
    touch(outage)
    return ok(serialize(activity))
