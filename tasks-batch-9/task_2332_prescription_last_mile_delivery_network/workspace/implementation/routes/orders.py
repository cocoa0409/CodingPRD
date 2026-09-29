"""Order intake, release for scheduling, and the bounded hold loop."""

from flask import Blueprint

import middleware
import response
import serializers
import validation as v
from constants import CONTROLLED_SCHEDULES, LICENSE_COVERAGE, MAX_ORDER_HOLDS
from db import db, new_row, touch
from errors import api_error
from middleware import ROLE_PHARMACY, require_roles
from services import orders as order_service

bp = Blueprint("orders", __name__)


@bp.post("/pharmacy-orders")
@require_roles(ROLE_PHARMACY)
def create_order():
    body = v.json_body()
    pharmacy_id = v.string_field(body, "pharmacy_id")
    patient_id = v.string_field(body, "patient_id")
    health_plan_id = v.string_field(body, "health_plan_id", required=False, default=None)
    rx_line_count = v.int_field(body, "rx_line_count", minimum=1)
    cold = v.bool_field(body, "cold_chain_required", default=False)
    schedule = v.enum_field(body, "controlled_schedule", CONTROLLED_SCHEDULES,
                            required=False, default="NONE")
    total_value = v.int_field(body, "total_rx_value_cents", minimum=0)

    if pharmacy_id not in db.pharmacies:
        raise api_error("ERR_REFERENCE_NOT_FOUND", "The referenced pharmacy does not exist.")
    if patient_id not in db.patients:
        raise api_error("ERR_PATIENT_NOT_FOUND")
    if health_plan_id is not None and health_plan_id not in db.health_plans:
        raise api_error("ERR_REFERENCE_NOT_FOUND", "The referenced health plan does not exist.")

    row = new_row()
    row["pharmacy_id"] = pharmacy_id
    row["patient_id"] = patient_id
    row["health_plan_id"] = health_plan_id
    row["rx_line_count"] = rx_line_count
    row["cold_chain_required"] = cold
    row["controlled_schedule"] = schedule
    row["total_rx_value_cents"] = total_value
    row["hold_count"] = 0
    row["status"] = "INTAKE"
    order_service.apply_proof_requirements(row)
    db.pharmacy_orders[row["id"]] = row
    return response.single(serializers.pharmacy_order(row), 201)


def _load_order(order_id):
    """Rungs 3/4 then rung 8: scope decides before existence leaks."""
    order = db.pharmacy_orders.get(order_id)
    middleware.guard_order_scope(order)
    if order is None:
        raise api_error("ERR_ORDER_NOT_FOUND")
    return order


@bp.post("/pharmacy-orders/<order_id>/mark-ready")
@require_roles(ROLE_PHARMACY)
def mark_ready(order_id):
    order = _load_order(order_id)

    if order["status"] != "INTAKE":
        raise api_error("ERR_INVALID_ORDER_STATE",
                        "Only an INTAKE order may be released for scheduling.")

    patient = db.patients.get(order["patient_id"])
    if patient is None or patient["hipaa_consent_status"] != "GRANTED":
        raise api_error("ERR_CONSENT_NOT_GRANTED")

    pharmacy = db.pharmacies.get(order["pharmacy_id"])
    covered = LICENSE_COVERAGE.get(pharmacy["controlled_license_tier"], {"NONE"})
    if order["controlled_schedule"] not in covered:
        raise api_error("ERR_CONTROLLED_NOT_LICENSED",
                        "The dispensing site's controlled licence tier does not cover "
                        "this schedule.")
    if order["cold_chain_required"] and not pharmacy["cold_chain_certified"]:
        raise api_error("ERR_CONTROLLED_NOT_LICENSED",
                        "The dispensing site is not cold-chain certified.")

    order_service.apply_proof_requirements(order)
    order["status"] = "READY"
    touch(order)
    return response.single(serializers.pharmacy_order(order), 200)


@bp.post("/pharmacy-orders/<order_id>/hold")
@require_roles(ROLE_PHARMACY)
def hold_order(order_id):
    order = _load_order(order_id)

    body = v.json_body()
    v.string_field(body, "notes", required=False, default=None, max_len=1000)

    if order["status"] != "READY":
        raise api_error("ERR_ORDER_NOT_READY")
    if order["hold_count"] >= MAX_ORDER_HOLDS:
        raise api_error("ERR_MAX_HOLDS_EXCEEDED")

    order["hold_count"] += 1
    order["status"] = "INTAKE"
    touch(order)
    return response.single(serializers.pharmacy_order(order), 200)
