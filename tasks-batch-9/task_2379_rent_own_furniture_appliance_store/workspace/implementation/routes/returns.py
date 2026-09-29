"""Voluntary return and the grading that closes the books."""

from flask import Blueprint

import middleware
import response
import validators
from db import base_row, db, public, touch
from errors import ApiError
from routes import common
from services import calc, domain

bp = Blueprint("returns", __name__)

GRADES = ("GRADE_A", "GRADE_B", "GRADE_C", "UNRENTABLE")


def open_inspection(agreement, unit, return_reason):
    inspection = base_row()
    inspection["agreement_id"] = agreement["id"]
    inspection["unit_id"] = unit["id"]
    inspection["return_reason"] = return_reason
    inspection["status"] = "PENDING"
    inspection["assessed_grade"] = None
    inspection["damage_deduction_cents"] = 0
    inspection["missing_parts_count"] = 0
    inspection["final_residual_value_cents"] = 0
    inspection["re_rent_rate_cents"] = 0
    inspection["depreciation_tier"] = "TIER_1"
    inspection["graded_by_user_id"] = ""
    db.inspections[inspection["id"]] = inspection
    return inspection


@bp.post("/agreements/<agreement_id>/return")
def accept_return(agreement_id):
    user_id, role = middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.CUSTOMER,
        )
    )
    agreement = domain.require_agreement(agreement_id)
    middleware.require_owner(role, user_id, agreement["customer_id"])
    body = validators.json_body()
    return_reason = validators.enum(body, "return_reason", ("VOLUNTARY_RETURN",))

    domain.check_payment_status(agreement, domain.OP_RETURN)
    domain.check_possession_status(agreement, domain.OP_RETURN)

    unit = domain.require_unit(agreement["unit_id"])
    inspection = open_inspection(agreement, unit, return_reason)

    agreement["possession_status"] = "RETURN_PENDING_INSPECTION"
    touch(agreement)

    unit["status"] = "RETURNED_PENDING_GRADE"
    domain.write_provisional_residual(unit)

    touched_stores = {unit["store_id"]}
    domain.void_open_tickets(agreement, touched_stores)
    domain.cancel_scheduled_delivery_orders(agreement)
    domain.expire_open_window(agreement)

    for store_id in sorted(touched_stores):
        store = db.stores.get(store_id)
        if store is not None:
            domain.sync_store(store)
    return response.object_response(public(inspection), 201)


@bp.get("/return-inspections/<inspection_id>")
def read_inspection(inspection_id):
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.SERVICE_TECHNICIAN,
        )
    )
    inspection = domain.require_inspection(inspection_id)
    return response.object_response(public(inspection))


@bp.get("/return-inspections")
def list_inspections():
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.SERVICE_TECHNICIAN,
        )
    )
    return common.paged(
        list(db.inspections.values()),
        filters=("agreement_id", "unit_id", "status"),
    )


@bp.post("/return-inspections/<inspection_id>/grade")
def grade_inspection(inspection_id):
    user_id, _ = middleware.authenticate(
        (middleware.PLATFORM_ADMIN, middleware.SERVICE_TECHNICIAN)
    )
    inspection = domain.require_inspection(inspection_id)
    body = validators.json_body()
    assessed_grade = validators.enum(body, "assessed_grade", GRADES)
    damage = validators.integer(body, "damage_deduction_cents", minimum=0)
    missing = validators.integer(body, "missing_parts_count", minimum=0, maximum=20)

    unit = db.units.get(inspection["unit_id"])
    if unit is None or unit["status"] != "RETURNED_PENDING_GRADE":
        raise ApiError("ERR_UNIT_NOT_AVAILABLE")
    if inspection["status"] != "PENDING":
        raise ApiError("ERR_INSPECTION_ALREADY_GRADED")

    final_residual = calc.final_residual_cents(unit, assessed_grade, damage, missing)
    tier = calc.depreciation_tier(final_residual, unit["cash_price_cents"])

    inspection["status"] = "GRADED"
    inspection["graded_by_user_id"] = user_id
    inspection["assessed_grade"] = assessed_grade
    inspection["damage_deduction_cents"] = damage
    inspection["missing_parts_count"] = missing
    inspection["final_residual_value_cents"] = final_residual
    inspection["re_rent_rate_cents"] = calc.re_rent_rate_cents(final_residual)
    inspection["depreciation_tier"] = tier
    touch(inspection)

    unit["residual_value_cents"] = final_residual
    unit["residual_valuation_basis"] = "FINAL"
    if tier == "WRITE_OFF":
        unit["status"] = "RETIRED"
        unit["retired_reason"] = "UNRENTABLE_ON_GRADING"
    else:
        unit["condition_grade"] = assessed_grade
        unit["rent_cycle_count"] += 1
        unit["status"] = "AVAILABLE"
    touch(unit)

    agreement = db.agreements.get(inspection["agreement_id"])
    if agreement is not None and agreement["possession_status"] == "RETURN_PENDING_INSPECTION":
        was_delinquent = agreement["payment_status"] == "DELINQUENT"
        agreement["possession_status"] = "RETURNED"
        agreement["payment_status"] = "CLOSED"
        if was_delinquent:
            domain.expire_open_window(agreement)
            agreement["collections_stage"] = "NONE"
        touch(agreement)
        customer = db.customers.get(agreement["customer_id"])
        if customer is not None:
            domain.sync_customer(customer)

    store = db.stores.get(unit["store_id"])
    if store is not None:
        domain.sync_store(store)
    return response.object_response(public(inspection))
