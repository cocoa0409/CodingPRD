"""Discharge order endpoints."""

from datetime import datetime, time, timezone

from flask import Blueprint, request

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_UNAUTHORIZED_ROLE,
    ERR_DISCHARGE_ORDER_INVALID_STATE, ERR_PATIENT_NOT_ADMITTED,
    ERR_OPEN_STAT_CONSULT_BLOCKS_DISCHARGE,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import make_entity, touch, refresh_hospitalist_census
from services import serializers
import clock

bp = Blueprint("discharges", __name__)

ALL_ROLES = ["GroupAdmin", "Hospitalist", "ConsultingSpecialist"]
STAT_BLOCKING = {"OPEN", "ESCALATED", "ACKNOWLEDGED", "REOPENED"}


def _paginate(items, serializer):
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameters", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameters", 400)
    items = sorted(items, key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(i) for i in page], limit, offset, total)


def _body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be an object", 400)
    return data


@bp.route("/patients/<patient_id>/discharge-orders", methods=["POST"])
def create_discharge_order(patient_id):
    role, uid = require_roles(["Hospitalist"])
    body = _body()
    target_s = body.get("target_discharge_at")
    target = clock.parse_iso(target_s)
    if target is None:
        raise ApiError(ERR_INVALID_REQUEST, "target_discharge_at must be ISO8601 datetime", 400)

    patient = store["patients"].get(patient_id)
    if patient is None:
        raise ApiError(ERR_NOT_FOUND, "Patient not found", 404)

    # ownership: caller must hold the patient's ACTIVE assignment
    has_active = any(
        a["patient_id"] == patient_id and a["hospitalist_id"] == uid and a["status"] == "ACTIVE"
        for a in store["assignments"].values()
    )
    if not has_active:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, "caller does not hold the patient's ACTIVE assignment", 403)

    if patient["admission_status"] != "ADMITTED":
        raise ApiError(ERR_PATIENT_NOT_ADMITTED, "patient is not ADMITTED", 409)

    o = make_entity({
        "patient_id": patient_id,
        "ordering_hospitalist_id": uid,
        "status": "PLANNED",
        "target_discharge_at": target,
        "ordered_at": None,
        "executed_at": None,
        "meets_throughput_target": None,
    })
    store["discharge_orders"][o["id"]] = o
    return success_object(serializers.discharge_order(o), 201)


@bp.route("/discharge-orders", methods=["GET"])
def list_discharge_orders():
    require_roles(ALL_ROLES)
    items = list(store["discharge_orders"].values())
    pid = request.args.get("patient_id")
    if pid is not None:
        items = [o for o in items if o["patient_id"] == pid]
    ohid = request.args.get("ordering_hospitalist_id")
    if ohid is not None:
        items = [o for o in items if o["ordering_hospitalist_id"] == ohid]
    st = request.args.get("status")
    if st is not None:
        items = [o for o in items if o["status"] == st]
    return _paginate(items, serializers.discharge_order)


@bp.route("/discharge-orders/<oid>", methods=["GET"])
def get_discharge_order(oid):
    require_roles(ALL_ROLES)
    o = store["discharge_orders"].get(oid)
    if o is None:
        raise ApiError(ERR_NOT_FOUND, "DischargeOrder not found", 404)
    return success_object(serializers.discharge_order(o))


@bp.route("/discharge-orders/<oid>/order", methods=["POST"])
def order_discharge(oid):
    role, uid = require_roles(["Hospitalist"])
    o = store["discharge_orders"].get(oid)
    if o is None:
        raise ApiError(ERR_NOT_FOUND, "DischargeOrder not found", 404)
    if o["ordering_hospitalist_id"] != uid:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, "only the ordering hospitalist may order", 403)
    if o["status"] != "PLANNED":
        raise ApiError(ERR_DISCHARGE_ORDER_INVALID_STATE, "order requires status PLANNED", 409)
    o["status"] = "ORDERED"
    o["ordered_at"] = clock.now()
    touch(o)
    return success_object(serializers.discharge_order(o))


@bp.route("/discharge-orders/<oid>/execute", methods=["POST"])
def execute_discharge(oid):
    role, uid = require_roles(["Hospitalist"])
    o = store["discharge_orders"].get(oid)
    if o is None:
        raise ApiError(ERR_NOT_FOUND, "DischargeOrder not found", 404)
    if o["ordering_hospitalist_id"] != uid:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, "only the ordering hospitalist may execute", 403)
    if o["status"] != "ORDERED":
        raise ApiError(ERR_DISCHARGE_ORDER_INVALID_STATE, "execute requires status ORDERED", 409)

    patient = store["patients"].get(o["patient_id"])
    if patient is None:
        raise ApiError(ERR_NOT_FOUND, "Patient not found", 404)
    if patient["admission_status"] != "ADMITTED":
        raise ApiError(ERR_PATIENT_NOT_ADMITTED, "patient is not ADMITTED", 409)

    # safety: unresolved STAT consult blocks
    for c in store["consult_requests"].values():
        if (
            c["patient_id"] == o["patient_id"]
            and c["priority"] == "STAT"
            and c["status"] in STAT_BLOCKING
        ):
            raise ApiError(ERR_OPEN_STAT_CONSULT_BLOCKS_DISCHARGE, "an unresolved STAT consult blocks discharge", 422)

    now = clock.now()
    o["status"] = "EXECUTED"
    o["executed_at"] = now

    # throughput target: cutoff = date(target_discharge_at)T11:00:00Z; executed_at <= cutoff
    d = o["target_discharge_at"].date()
    cutoff = datetime.combine(d, time(11, 0, 0), tzinfo=timezone.utc)
    o["meets_throughput_target"] = now <= cutoff
    touch(o)

    # cascade: patient
    patient["admission_status"] = "DISCHARGED"
    if patient["observation_status"] == "OBS_ACTIVE":
        patient["observation_status"] = "OBS_CLOSED"
    touch(patient)

    # cascade: close ACTIVE assignment
    for a in store["assignments"].values():
        if a["patient_id"] == o["patient_id"] and a["status"] == "ACTIVE":
            a["status"] = "CLOSED"
            a["close_reason"] = "DISCHARGE"
            a["closed_at"] = now
            touch(a)
            h = store["hospitalists"].get(a["hospitalist_id"])
            if h is not None:
                refresh_hospitalist_census(h)
                touch(h)
            break

    return success_object(serializers.discharge_order(o))
