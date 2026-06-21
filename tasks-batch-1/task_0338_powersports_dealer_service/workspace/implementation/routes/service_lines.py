"""Service lines (PRD 3.7): append-only flat-rate operation lines."""

from decimal import Decimal

from flask import Blueprint, request

import errors
import calculations as calc
from common import get_body, stamp_new, serialize, paginate, as_number, as_str
from db import db
from lookups import get_service_line, get_repair_order
from middleware import get_user_context, require_role
from response import ok, ok_list

bp = Blueprint("service_lines", __name__)


@bp.route("/service-lines", methods=["POST"])
def create_service_line():
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor"})
    body = get_body()
    # existence: repair_order_id
    repair_order_id = as_str(body, "repair_order_id")
    ro = get_repair_order(repair_order_id)
    operation_code = as_str(body, "operation_code")
    flat_rate_hours = as_number(body, "flat_rate_hours", gt=0)

    # service lines are added to an OPEN repair order
    if ro["work_status"] != "OPEN":
        errors.err(errors.ERR_INVALID_STATE, "Service lines may only be added to an OPEN repair order")

    # preview extended labor against the current tier (final figures at RO complete)
    existing = calc.ro_service_lines(repair_order_id)
    total_hours = sum(Decimal(str(l["flat_rate_hours"])) for l in existing) + Decimal(str(flat_rate_hours))
    rate = calc.effective_labor_rate(total_hours, ro.get("is_warranty", False))
    extended = calc.line_extended_labor(flat_rate_hours, rate)

    rec = stamp_new({
        "repair_order_id": repair_order_id,
        "operation_code": operation_code,
        "flat_rate_hours": flat_rate_hours,
        "extended_labor_cents": extended,
    }, common=False)
    db.service_lines[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/service-lines", methods=["GET"])
def list_service_lines():
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor", "DealerPrincipal"})
    repair_order_id = request.args.get("repair_order_id")
    records = [sl for sl in db.service_lines.values()
               if repair_order_id is None or sl["repair_order_id"] == repair_order_id]
    items, limit, offset, total = paginate(records)
    return ok_list(items, limit, offset, total)


@bp.route("/service-lines/<slid>", methods=["GET"])
def get_service_line_route(slid):
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor", "DealerPrincipal"})
    rec = get_service_line(slid)
    return ok(serialize(rec), 200)
