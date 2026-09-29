"""Trunk augment order lifecycle (PRD 3.4)."""
from flask import Blueprint, request

import validation as v
from auth import (CARRIER_REPRESENTATIVE, NETWORK_PLANNER, PLATFORM_ADMIN,
                  authenticate, carrier_of_order, carrier_of_trunk_group,
                  scope_check, scope_filter)
from constants import DS1_TRUNKS
from envelope import object_response, paginate
from errors import ApiError
from lookup import get_augment_order, get_trunk_group
from services.sizing import (install_window, poi_provisioned_trunks,
                             recompute_posture, window_collides)
from store import db, now, ordered, touch

bp = Blueprint("augments", __name__)


@bp.get("/trunk-groups/<trunk_group_id>/augment-orders")
def list_trunk_group_orders(trunk_group_id):
    actor = authenticate((PLATFORM_ADMIN, NETWORK_PLANNER, CARRIER_REPRESENTATIVE))
    trunk_group = get_trunk_group(trunk_group_id)
    scope_check(actor, carrier_of_trunk_group(trunk_group))
    rows = [o for o in ordered(db.augment_orders)
            if o["trunk_group_id"] == trunk_group["id"]]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, request.args, lambda r: r)


@bp.get("/trunk-augment-orders/<order_id>")
def read_order(order_id):
    actor = authenticate((PLATFORM_ADMIN, NETWORK_PLANNER, CARRIER_REPRESENTATIVE))
    order = get_augment_order(order_id)
    scope_check(actor, carrier_of_order(order))
    return object_response(order)


@bp.get("/trunk-augment-orders")
def list_orders():
    actor = authenticate((PLATFORM_ADMIN, NETWORK_PLANNER, CARRIER_REPRESENTATIVE))
    rows = ordered(db.augment_orders)
    trunk_group_id = request.args.get("trunk_group_id")
    if trunk_group_id:
        rows = [r for r in rows if r["trunk_group_id"] == trunk_group_id]
    measurement_id = request.args.get("triggering_measurement_id")
    if measurement_id:
        rows = [r for r in rows if r["triggering_measurement_id"] == measurement_id]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = scope_filter(actor, rows, carrier_of_order)
    return paginate(rows, request.args, lambda r: r)


@bp.post("/trunk-augment-orders/<order_id>/accept")
def accept_order(order_id):
    actor = authenticate((CARRIER_REPRESENTATIVE,))
    order = get_augment_order(order_id)
    payload = v.body()
    committed_due_date = v.timestamp(payload, "committed_due_date")

    trunk_group = db.trunk_groups.get(order["trunk_group_id"])
    agreement = db.agreements.get(trunk_group["agreement_id"])
    scope_check(actor, agreement["carrier_id"])

    if order["status"] != "PENDING":
        raise ApiError("ERR_INVALID_AUGMENT_ORDER_STATE",
                       "only a PENDING augment order may be accepted")

    window_start, window_end = install_window(committed_due_date)
    if window_collides(order, agreement["id"], trunk_group["poi_clli_code"],
                       window_start, window_end):
        raise ApiError("ERR_AUGMENT_WINDOW_COLLISION",
                       "the buffered install window collides with an accepted order at this POI")
    if committed_due_date <= now():
        raise ApiError("ERR_INVALID_COMMITTED_DUE_DATE",
                       "committed_due_date must be strictly after the logical clock")

    order["status"] = "ACCEPTED"
    order["committed_due_date"] = committed_due_date
    order["install_window_start"] = window_start
    order["install_window_end"] = window_end
    touch(order)
    return object_response(order)


@bp.post("/trunk-augment-orders/<order_id>/reject")
def reject_order(order_id):
    actor = authenticate((CARRIER_REPRESENTATIVE,))
    order = get_augment_order(order_id)
    payload = v.body()
    reason = v.string(payload, "rejection_reason")

    trunk_group = db.trunk_groups.get(order["trunk_group_id"])
    agreement = db.agreements.get(trunk_group["agreement_id"])
    scope_check(actor, agreement["carrier_id"])

    if order["status"] != "PENDING":
        raise ApiError("ERR_INVALID_AUGMENT_ORDER_STATE",
                       "only a PENDING augment order may be rejected")

    order["status"] = "REJECTED"
    order["rejection_reason"] = reason
    touch(order)

    trunk_group["augment_status"] = "AUGMENT_BLOCKED"
    trunk_group["open_augment_order_count"] -= 1
    touch(trunk_group)

    agreement["poi_augment_pending_count"] -= 1
    recompute_posture(agreement)
    touch(agreement)
    return object_response(order)


@bp.post("/trunk-augment-orders/<order_id>/complete")
def complete_order(order_id):
    authenticate((NETWORK_PLANNER,))
    order = get_augment_order(order_id)
    payload = v.body()
    installed = v.integer(payload, "installed_trunks")

    trunk_group = db.trunk_groups.get(order["trunk_group_id"])
    agreement = db.agreements.get(trunk_group["agreement_id"])

    if order["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_AUGMENT_ORDER_STATE",
                       "only an ACCEPTED augment order may be completed")

    committed = poi_provisioned_trunks(agreement["id"], trunk_group["poi_clli_code"])
    if committed + installed > agreement["poi_facility_capacity_trunks"]:
        raise ApiError("ERR_POI_CAPACITY_EXCEEDED",
                       "the POI facility ceiling would be exceeded")

    if (installed <= 0 or installed % DS1_TRUNKS != 0
            or installed > order["requested_additional_trunks"]):
        raise ApiError("ERR_INSTALLED_TRUNKS_INVALID",
                       "installed_trunks must be a positive multiple of 24 no greater "
                       "than the requested quantity")

    order["status"] = "COMPLETED"
    order["installed_trunks"] = installed
    touch(order)

    trunk_group["provisioned_trunks"] += installed
    trunk_group["augment_status"] = "NONE"
    trunk_group["open_augment_order_count"] -= 1
    touch(trunk_group)

    agreement["total_in_service_trunks"] += installed
    agreement["poi_augment_pending_count"] -= 1
    recompute_posture(agreement)
    touch(agreement)
    return object_response(order)


@bp.post("/trunk-augment-orders/<order_id>/reverse")
def reverse_order(order_id):
    authenticate((NETWORK_PLANNER,))
    order = get_augment_order(order_id)
    payload = v.body()
    reason = v.string(payload, "reversal_reason")

    trunk_group = db.trunk_groups.get(order["trunk_group_id"])
    agreement = db.agreements.get(trunk_group["agreement_id"])

    if order["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_AUGMENT_ORDER_STATE",
                       "only a COMPLETED augment order may be reversed")
    if trunk_group["service_status"] not in ("PROVISIONED", "IN_SERVICE"):
        raise ApiError("ERR_INVALID_TRUNK_GROUP_STATE",
                       "the trunk group is no longer carrying the installed trunks")

    installed = order["installed_trunks"] or 0
    order["status"] = "REVERSED"
    order["reversed_at"] = now()
    order["_reversal_reason"] = reason
    touch(order)

    trunk_group["provisioned_trunks"] -= installed
    if trunk_group["augment_status"] == "NONE":
        trunk_group["augment_status"] = "GROOMING_REVIEW"
    touch(trunk_group)

    agreement["total_in_service_trunks"] -= installed
    touch(agreement)
    return object_response(order)
