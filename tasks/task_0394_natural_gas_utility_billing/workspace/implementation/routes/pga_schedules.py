"""PGA schedule endpoints (PRD §3.1)."""

from flask import Blueprint

from db import store
from errors import ERR_DUPLICATE, err
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_body,
    require_fields,
    require_enum,
    require_int,
    require_month,
    optional_int,
    attach_common_fields,
)
from services.serialize import view_pga_schedule
from services import lookup

bp = Blueprint("pga_schedules", __name__)


@bp.route("/pga-schedules", methods=["POST"])
def create_pga_schedule():
    principal = authenticate()
    require_role(principal, {"BillingAdmin"})
    body = get_body()
    require_fields(body, ["effective_month", "customer_class", "commodity_rate_cents_per_therm"])
    effective_month = require_month(body, "effective_month")
    customer_class = require_enum(body, "customer_class", {"RESIDENTIAL", "COMMERCIAL"})
    commodity_rate_cents_per_therm = require_int(body, "commodity_rate_cents_per_therm", minimum=0)
    supplier_refund_cents_per_therm = optional_int(body, "supplier_refund_cents_per_therm", minimum=0)
    if supplier_refund_cents_per_therm is None:
        supplier_refund_cents_per_therm = 0

    with store.lock:
        for p in store.pga_schedules.values():
            if p["customer_class"] == customer_class and p["effective_month"] == effective_month:
                raise err(ERR_DUPLICATE, "PGA schedule already exists for class and month")
        rec = {
            "effective_month": effective_month,
            "customer_class": customer_class,
            "commodity_rate_cents_per_therm": commodity_rate_cents_per_therm,
            "supplier_refund_cents_per_therm": supplier_refund_cents_per_therm,
        }
        attach_common_fields(rec)
        store.pga_schedules[rec["id"]] = rec
        return success(view_pga_schedule(rec), 201)


@bp.route("/pga-schedules/<pga_id>", methods=["GET"])
def get_pga_schedule(pga_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService"})
    pga = lookup.get_pga_schedule(pga_id)
    return success(view_pga_schedule(pga), 200)
