"""RateSchedule endpoints (PRD 3.6)."""

from flask import Blueprint

import enums
import services as svc
from db import base_record, store
from middleware import endpoint, paginate
from validators import (get_enum, get_int, get_num, get_str, get_tiers,
                        json_body, query_enum)

bp = Blueprint("rates", __name__, url_prefix="/district-energy")

LIST_READERS = ("SystemController", "NetworkEngineer", "BillingAnalyst")
GET_READERS = ("SystemController", "NetworkEngineer", "BillingAnalyst", "CustomerAccount")


@endpoint(bp, "/rate-schedules", ["POST"], ["BillingAnalyst"], status=201)
def create_rate_schedule():
    body = json_body()
    code = get_str(body, "code")
    customer_class = get_enum(body, "customer_class", enums.CUSTOMER_CLASS)
    fixed_service_charge = get_num(body, "fixed_service_charge", ge=0)
    demand_charge_per_kw = get_num(body, "demand_charge_per_kw", ge=0)
    minimum_bill_amount = get_num(body, "minimum_bill_amount", ge=0)
    tiers = get_tiers(body, "tiers")
    ratchet_lookback_months = get_int(body, "ratchet_lookback_months", required=False,
                                     default=11, ge=0)

    svc.require_unique_code("rate_schedules", "code", code)

    rate = base_record()
    rate.update({
        "code": code,
        "customer_class": customer_class,
        "fixed_service_charge": fixed_service_charge,
        "demand_charge_per_kw": demand_charge_per_kw,
        "minimum_bill_amount": minimum_bill_amount,
        "ratchet_lookback_months": ratchet_lookback_months,
        "tiers": tiers,
    })
    store.rate_schedules[rate["id"]] = rate
    return rate


@endpoint(bp, "/rate-schedules", ["GET"], LIST_READERS)
def list_rate_schedules():
    filters = {}
    customer_class = query_enum("customer_class", enums.CUSTOMER_CLASS)
    if customer_class is not None:
        filters["customer_class"] = customer_class
    return paginate(svc.where("rate_schedules", **filters))


@endpoint(bp, "/rate-schedules/<rate_schedule_id>", ["GET"], GET_READERS)
def get_rate_schedule(rate_schedule_id):
    return svc.path_get("rate_schedules", rate_schedule_id)
