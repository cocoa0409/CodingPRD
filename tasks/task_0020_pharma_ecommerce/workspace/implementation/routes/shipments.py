"""Cold-chain shipments — dispatch, readings, mark-in-transit, dispose, get."""

from __future__ import annotations

from flask import Blueprint, request

from db import (
    append_audit_log,
    db,
    emit_external_event,
    parse_iso,
    platform_clock,
    serialize,
    stamp_create,
    stamp_update,
)
from errors import err
from lookups import get_order, get_platform, get_shipment
from middleware import current_actor, require_roles
from response import success_object
from services.calculations import COLD_CHAIN_DISPOSE_THRESHOLD, excursion_score
from services.cascades import refund_if_paid, evaluate_prescription_archive
from validate import occ_check, require_field, require_json, require_pos_int

bp = Blueprint("shipments", __name__)


@bp.post("/pharma-platforms/<pid>/cold-chain-shipments")
@require_roles("PlatformAdmin")
def dispatch_shipment(pid: str):
    platform = get_platform(pid)
    body = require_json(request.get_json(silent=True))
    order_id = require_field(body, "order_id", kind=str)
    courier_id = require_field(body, "courier_pharmacist_id", kind=str)
    device_id = require_field(body, "device_id", kind=str)

    order = db.orders.get(order_id)
    if not order or order.get("platform_id") != pid:
        raise err("ERR_ORDER_NOT_FOUND", f"Order '{order_id}' not found.")
    if not order.get("cold_chain_required"):
        raise err(
            "ERR_COLD_CHAIN_NOT_APPLICABLE",
            "Order does not require cold chain.",
        )
    if order.get("dispensing_status") not in {"APPROVED", "DISPENSED"}:
        raise err(
            "ERR_COLD_CHAIN_NOT_APPLICABLE",
            "Cold-chain shipment may only be dispatched for APPROVED or DISPENSED orders.",
        )

    courier = db.pharmacists.get(courier_id)
    if not courier or courier.get("platform_id") != pid:
        raise err("ERR_COURIER_NOT_QUALIFIED", "Courier pharmacist not found.")
    if not courier.get("courier_qualified") or courier.get("qualification_status") != "ACTIVE":
        raise err("ERR_COURIER_NOT_QUALIFIED", "Courier must be courier_qualified and ACTIVE.")

    row = {
        "platform_id": pid,
        "order_id": order_id,
        "courier_pharmacist_id": courier_id,
        "device_id": device_id,
        "dispatched_at": platform_clock(platform),
        "temperature_readings": [],
        "excursion_score": 0,
        "status": "DISPATCHED",
    }
    stamp_create(row, platform)
    db.cold_chain_shipments[row["id"]] = row
    order["cold_chain_shipment_id"] = row["id"]
    stamp_update(order, platform)
    emit_external_event(
        platform=platform,
        channel="LOGISTICS",
        event_type="shipment.dispatched",
        subject_type="COLD_CHAIN_SHIPMENT",
        subject_id=row["id"],
        payload={"shipment_id": row["id"], "order_id": order_id, "version": row["version"]},
        idempotency_key=f"shipment.dispatched:{row['id']}:{row['version']}",
    )
    return success_object(serialize(row)), 201


@bp.post("/pharma-platforms/<pid>/cold-chain-shipments/<shipment_id>/readings")
@require_roles("PlatformAdmin", "Pharmacist")
def append_reading(pid: str, shipment_id: str):
    platform, s = get_shipment(pid, shipment_id)
    body = require_json(request.get_json(silent=True))
    recorded_at = require_field(body, "recorded_at", kind=str)
    try:
        parse_iso(recorded_at)
    except Exception as exc:
        raise err("ERR_INVALID_REQUEST", f"Bad recorded_at: {exc}")
    celsius_tenths = body.get("celsius_tenths")
    if not isinstance(celsius_tenths, int) or isinstance(celsius_tenths, bool):
        raise err("ERR_INVALID_REQUEST", "celsius_tenths must be an integer.")
    s["temperature_readings"].append({"recorded_at": recorded_at, "celsius_tenths": celsius_tenths})
    s["excursion_score"] = excursion_score(s["temperature_readings"])
    stamp_update(s, platform)
    return success_object(serialize(s)), 200


@bp.post("/pharma-platforms/<pid>/cold-chain-shipments/<shipment_id>/mark-in-transit")
@require_roles("PlatformAdmin")
def mark_in_transit(pid: str, shipment_id: str):
    platform, s = get_shipment(pid, shipment_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, s)
    if s.get("status") != "DISPATCHED":
        raise err("ERR_SHIPMENT_NOT_DISPOSABLE", "Shipment is not DISPATCHED.")
    s["status"] = "IN_TRANSIT"
    stamp_update(s, platform)
    return success_object(serialize(s)), 200


@bp.post("/pharma-platforms/<pid>/cold-chain-shipments/<shipment_id>/dispose")
@require_roles("PlatformAdmin")
def dispose_shipment(pid: str, shipment_id: str):
    platform, s = get_shipment(pid, shipment_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, s)
    if s.get("status") not in {"DISPATCHED", "IN_TRANSIT"}:
        raise err("ERR_SHIPMENT_NOT_DISPOSABLE", "Shipment is in a terminal state.")
    if int(s.get("excursion_score") or 0) <= COLD_CHAIN_DISPOSE_THRESHOLD:
        raise err(
            "ERR_DISPOSAL_NOT_JUSTIFIED",
            "excursion_score does not exceed the disposal threshold.",
        )
    s["status"] = "DISPOSED"
    stamp_update(s, platform)
    actor_id, actor_role = current_actor()
    append_audit_log(
        platform=platform,
        subject_type="COLD_CHAIN_SHIPMENT",
        subject_id=s["id"],
        action="COLD_CHAIN_DISPOSED",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"shipment_id": s["id"], "version": s["version"]},
    )
    # Cascade: order → REJECTED + refund cascade.
    order = db.orders.get(s["order_id"])
    if order is not None:
        order["dispensing_status"] = "REJECTED"
        stamp_update(order, platform)
        refund_if_paid(platform, order)
        evaluate_prescription_archive(platform, order.get("prescription_id"))
    return success_object(serialize(s)), 200


@bp.get("/pharma-platforms/<pid>/cold-chain-shipments/<shipment_id>")
@require_roles("PlatformAdmin", "Pharmacist", "RegulatoryGateway")
def get_shipment_route(pid: str, shipment_id: str):
    _, s = get_shipment(pid, shipment_id)
    return success_object(serialize(s)), 200
