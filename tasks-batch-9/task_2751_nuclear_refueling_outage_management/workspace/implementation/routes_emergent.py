"""Emergent work discovery and disposition (PRD 3.8)."""
from flask import Blueprint, request

import lookup
import projections
from auth import ALL_ROLES, authorize
from calc import dec, q2
from db import all_rows, create_row, store, touch
from errors import api_error
from response import ok, paginated, parse_pagination
from serializers import serialize
from validators import F, body

bp = Blueprint("emergent", __name__)

DISPOSITIONS = ("APPROVED", "REJECTED", "ABSORBED")


@bp.route("/work-orders/<work_order_id>/emergent-items", methods=["POST"])
@authorize("OutagePlanner", "RadProtectionPlanner")
def report_item(work_order_id):
    work_order = lookup.work_order(work_order_id)
    payload = body([
        F("description", "str", min_len=1, max_len=500),
        F("estimated_hours", "num", gt=0),
        F("estimated_cost_usd", "num", ge=0),
        F("estimated_dose_mrem", "num", ge=0),
        F("discovered_during_inspection", "bool", required=False, default=True),
    ])
    item = create_row(store.emergent_items, {
        "discovered_from_work_order_id": work_order["id"],
        "description": payload["description"],
        "estimated_hours": q2(payload["estimated_hours"]),
        "estimated_cost_usd": q2(payload["estimated_cost_usd"]),
        "estimated_dose_mrem": q2(payload["estimated_dose_mrem"]),
        "discovered_during_inspection": payload["discovered_during_inspection"],
        "status": "REPORTED",
        "disposition_note": None,
        "created_work_order_id": None,
    })
    return ok(serialize(item), 201)


@bp.route("/emergent-items/<row_id>", methods=["GET"])
@authorize(*ALL_ROLES)
def get_item(row_id):
    return ok(serialize(lookup.emergent_item(row_id)))


@bp.route("/work-orders/<work_order_id>/emergent-items", methods=["GET"])
@authorize(*ALL_ROLES)
def list_items(work_order_id):
    work_order = lookup.work_order(work_order_id)
    limit, offset = parse_pagination(request.args)
    rows = projections.emergent_items_of_work_order(work_order["id"])
    wanted = request.args.get("status")
    if wanted is not None:
        rows = [r for r in rows if r["status"] == wanted]
    return paginated(rows, limit, offset, serialize)


def _approved_cascade(item, discovering, outage, note):
    # Step 1 -- item status and note.
    item["status"] = "APPROVED"
    item["disposition_note"] = note
    touch(item)

    # Step 2 -- mint the emergent work order.
    minted_wo = projections.mint_work_order(
        outage, "MAINTENANCE", "EMERGENT: " + item["description"],
        item["estimated_hours"], item["estimated_cost_usd"],
        item["estimated_dose_mrem"], False, discovering["safety_function_id"],
        discovering["requires_rad_work"], origin="EMERGENT", status="APPROVED")
    item["created_work_order_id"] = minted_wo["id"]

    # Step 3 -- mint the schedule activity behind the discovering work order's
    # terminal activity.
    predecessor = projections.terminal_activity(discovering["id"])
    duration = dec(item["estimated_hours"])
    if predecessor is None:
        start_offset = q2(0)
        predecessor_id = None
    else:
        start_offset = q2(dec(predecessor["planned_start_offset_hours"]) + duration)
        predecessor_id = predecessor["id"]
    projections.mint_activity(outage, "EMERGENT: " + item["description"],
                              start_offset, item["estimated_hours"],
                              work_order_id=minted_wo["id"],
                              predecessor_activity_id=predecessor_id)

    # Step 4 -- reproject schedule, emergent hours and the cost roll-up.
    posture_before = outage["schedule_posture"]
    projections.recompute_critical_path(outage)
    projections.recompute_emergent_hours(outage)
    projections.recompute_scope_cost(outage)

    # Step 5 -- schedule posture from the step 4 projection.
    projections.recompute_schedule_posture(outage)
    posture_after = outage["schedule_posture"]

    # Step 6 -- posture auto-deferral of discretionary un-started scope.
    deferred = []
    if posture_before == "ON_TRACK" and posture_after in ("AT_RISK", "RECOVERY_REQUIRED"):
        for candidate in projections.work_orders_of_outage(outage["id"]):
            if candidate["priority"] != "DISCRETIONARY":
                continue
            if candidate["status"] not in ("SCOPED", "PLANNED"):
                continue
            candidate["status"] = "DEFERRED"
            candidate["deferral_reason"] = "SCHEDULE_POSTURE_AUTO_DEFERRAL"
            touch(candidate)
            deferred.append(candidate)

    # Step 7 -- cascade from each deferred work order.
    previous_posture = outage["alara_posture"]
    for candidate in deferred:
        projections.defer_work_order_cascade(candidate, True)

    # Step 8 -- final reprojection; schedule_posture stays as step 5 left it.
    projections.recompute_critical_path(outage)
    projections.recompute_scope_cost(outage)
    projections.recompute_dose(outage, previous_posture)
    outage["schedule_posture"] = posture_after
    touch(outage)


def _absorbed_cascade(item, discovering, outage, note):
    target = projections.terminal_activity(discovering["id"])
    if target is None:
        raise api_error("ERR_ACTIVITY_STATE_INVALID",
                        "The discovering work order has no activity able to absorb the hours.")
    item["status"] = "ABSORBED"
    item["disposition_note"] = note
    touch(item)

    target["planned_duration_hours"] = q2(
        dec(target["planned_duration_hours"]) + dec(item["estimated_hours"]))
    projections.touch_row(target)

    projections.recompute_schedule(outage)
    touch(outage)


@bp.route("/emergent-items/<row_id>/dispose", methods=["POST"])
@authorize("OutageDirector")
def dispose_item(row_id):
    item = lookup.emergent_item(row_id)
    payload = body([
        F("disposition", "str", enum=DISPOSITIONS),
        F("disposition_note", "str", required=False, default=None, nullable=True),
    ])
    if item["status"] != "REPORTED":
        raise api_error("ERR_EMERGENT_ITEM_STATE_INVALID",
                        "Disposition requires the item to be in REPORTED.")
    discovering = store.work_orders[item["discovered_from_work_order_id"]]
    outage = store.outages[discovering["outage_id"]]
    if outage["status"] not in ("SCOPE_LOCKED", "EXECUTION"):
        raise api_error("ERR_OUTAGE_STATE_INVALID",
                        "Disposition requires the outage to be SCOPE_LOCKED or EXECUTION.")

    note = payload["disposition_note"]
    if payload["disposition"] == "APPROVED":
        _approved_cascade(item, discovering, outage, note)
    elif payload["disposition"] == "ABSORBED":
        _absorbed_cascade(item, discovering, outage, note)
    else:
        item["status"] = "REJECTED"
        item["disposition_note"] = note
        touch(item)
    return ok(serialize(item))
