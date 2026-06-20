"""Rate schedule endpoints (PRD §3.1)."""

from flask import Blueprint

from db import store
from errors import ERR_DUPLICATE, ERR_INVALID_REQUEST, err
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_body,
    require_fields,
    require_string,
    require_int,
    require_enum,
    optional_int,
    optional_number,
    attach_common_fields,
)
from services.serialize import view_rate_schedule
from services import lookup

bp = Blueprint("rate_schedules", __name__)


@bp.route("/rate-schedules", methods=["POST"])
def create_rate_schedule():
    principal = authenticate()
    require_role(principal, {"BillingAdmin"})
    body = get_body()
    require_fields(body, [
        "code", "customer_class",
        "fixed_customer_charge_cents", "distribution_rate_cents_per_therm",
    ])
    code = require_string(body, "code")
    customer_class = require_enum(body, "customer_class", {"RESIDENTIAL", "COMMERCIAL"})
    fixed_customer_charge_cents = require_int(body, "fixed_customer_charge_cents", minimum=0)
    distribution_rate_cents_per_therm = require_int(body, "distribution_rate_cents_per_therm", minimum=0)

    btu_factor = optional_number(body, "btu_factor")
    if btu_factor is None:
        btu_factor = 1.025
    else:
        if btu_factor < 0.9 or btu_factor > 1.2:
            raise err(ERR_INVALID_REQUEST, "btu_factor must be between 0.9 and 1.2 inclusive")

    minimum_bill_cents = optional_int(body, "minimum_bill_cents", minimum=0)
    if minimum_bill_cents is None:
        minimum_bill_cents = 0

    with store.lock:
        for rs in store.rate_schedules.values():
            if rs["code"] == code:
                raise err(ERR_DUPLICATE, "Rate schedule code already exists")
        rec = {
            "code": code,
            "customer_class": customer_class,
            "fixed_customer_charge_cents": fixed_customer_charge_cents,
            "distribution_rate_cents_per_therm": distribution_rate_cents_per_therm,
            "btu_factor": btu_factor,
            "minimum_bill_cents": minimum_bill_cents,
            "active": True,
        }
        attach_common_fields(rec)
        store.rate_schedules[rec["id"]] = rec
        return success(view_rate_schedule(rec), 201)


@bp.route("/rate-schedules/<rs_id>", methods=["GET"])
def get_rate_schedule(rs_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService"})
    rs = lookup.get_rate_schedule(rs_id)
    return success(view_rate_schedule(rs), 200)
