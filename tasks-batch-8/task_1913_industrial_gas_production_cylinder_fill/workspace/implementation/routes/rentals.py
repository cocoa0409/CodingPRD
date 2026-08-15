"""CylinderRental endpoints (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint

from constants import RETURN_CONDITIONS
from db import store
from errors import (
    ERR_ACCOUNT_NOT_ACTIVE,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_CYLINDER_NOT_AVAILABLE,
    ERR_HYDRO_RETEST_OVERDUE,
    ERR_RENTAL_NOT_ACTIVE,
    ApiError,
    bad_request,
    not_found,
)
from middleware import ANY_ROLE, get_body, locked, req_enum, req_int, req_str, require_roles
from response import success
from routes.listing import list_response
from services import calc
from services.ops import base_record, credit_evaluate, rental_out
from util import clock_date, touch

bp = Blueprint("rentals", __name__)


def _get_rental(rentalId):
    r = store.rentals.get(rentalId)
    if r is None:
        not_found("rental not found")
    return r


@bp.post("/api/rentals")
@locked
def create_rental():
    require_roles("BillingClerk")
    body = get_body()
    customer_id = req_str(body, "customer_id")
    cylinder_id = req_str(body, "cylinder_id")
    daily_rate = req_int(body, "daily_rate_cents")
    planned_days = req_int(body, "planned_days")
    if daily_rate <= 0:
        bad_request("daily_rate_cents must be > 0")
    if planned_days <= 0:
        bad_request("planned_days must be > 0")
    customer = store.customers.get(customer_id)
    if customer is None:
        not_found("customer not found")
    cylinder = store.cylinders.get(cylinder_id)
    if cylinder is None:
        not_found("cylinder not found")
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_NOT_ACTIVE, 409, "customer account is not ACTIVE")
    if cylinder["status"] != "FILLED":
        raise ApiError(ERR_CYLINDER_NOT_AVAILABLE, 409, "cylinder must be FILLED")
    if calc.hydro_status(cylinder) == "OVERDUE":
        raise ApiError(ERR_HYDRO_RETEST_OVERDUE, 422, "cylinder hydrostatic retest is overdue")
    estimate = calc.variant_base_cents(customer, daily_rate, planned_days)
    if customer["outstanding_balance_cents"] + estimate > customer["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 402, "projected balance exceeds the credit limit")

    out_date = clock_date()
    r = base_record()
    r.update(
        {
            "customer_id": customer_id,
            "cylinder_id": cylinder_id,
            "daily_rate_cents": daily_rate,
            "planned_days": planned_days,
            "out_date_d": out_date,
            "due_date_d": out_date + timedelta(days=planned_days),
            "return_date_d": None,
            "billed_through_date_d": out_date + timedelta(days=planned_days),
            "demurrage_billed_cents": 0,
            "final_charge_cents": None,
            "status": "ACTIVE",
        }
    )
    store.rentals[r["id"]] = r
    cylinder["status"] = "ON_RENT"
    touch(cylinder)
    return success(rental_out(r), status=201)


@bp.get("/api/rentals")
@locked
def list_rentals():
    require_roles(*ANY_ROLE)
    return list_response(
        store.rentals.values(),
        rental_out,
        [("customer_id", "customer_id"), ("cylinder_id", "cylinder_id"), ("status", "status")],
    )


@bp.get("/api/rentals/<rentalId>")
@locked
def get_rental(rentalId):
    require_roles(*ANY_ROLE)
    return success(rental_out(_get_rental(rentalId)))


@bp.post("/api/rentals/<rentalId>/return")
@locked
def return_rental(rentalId):
    require_roles("BillingClerk")
    body = get_body()
    condition = req_enum(body, "return_condition", RETURN_CONDITIONS)
    r = _get_rental(rentalId)
    if r["status"] not in ("ACTIVE", "OVERDUE", "RECALL_HOLD"):
        raise ApiError(ERR_RENTAL_NOT_ACTIVE, 409, "rental is not returnable from its current state")
    was_recall_hold = r["status"] == "RECALL_HOLD"
    customer = store.customers[r["customer_id"]]
    cylinder = store.cylinders[r["cylinder_id"]]
    end = clock_date()
    charge = calc.rental_close_charge(r, customer, cylinder, end)
    r["return_date_d"] = end
    r["final_charge_cents"] = charge
    r["status"] = "RETURNED"
    touch(r)
    if was_recall_hold or condition == "DAMAGED":
        cylinder["status"] = "QUARANTINED"
    else:
        cylinder["status"] = "IN_STOCK"
    touch(cylinder)
    customer["outstanding_balance_cents"] += charge
    touched = {customer["id"]}
    touch(customer)
    credit_evaluate(customer, touched)
    return success(rental_out(r))


@bp.post("/api/rentals/<rentalId>/settle-loss")
@locked
def settle_loss(rentalId):
    require_roles("BillingClerk")
    get_body()
    r = _get_rental(rentalId)
    if r["status"] not in ("ACTIVE", "OVERDUE"):
        raise ApiError(ERR_RENTAL_NOT_ACTIVE, 409, "rental must be ACTIVE or OVERDUE to settle a loss")
    customer = store.customers[r["customer_id"]]
    cylinder = store.cylinders[r["cylinder_id"]]
    end = clock_date()
    charge = calc.rental_close_charge(r, customer, cylinder, end, include_loss_fee=True)
    r["final_charge_cents"] = charge
    r["status"] = "LOST_SETTLED"
    touch(r)
    cylinder["status"] = "LOST"
    touch(cylinder)
    customer["outstanding_balance_cents"] += charge
    touched = {customer["id"]}
    touch(customer)
    credit_evaluate(customer, touched)
    return success(rental_out(r))
