"""Primal purchase receiving and the landed-cost ledger (PRD §3.1, §2.6)."""

from flask import Blueprint

import errors
import middleware as mw
import validation as v
from calc import rhu
from db import db, make, sort_rows
from errors import ApiError
from response import list_response, object_response

bp = Blueprint("purchases", __name__)

PRIMAL_CODES = ("BEEF_RIBEYE_LIP_ON", "BEEF_STRIP_LOIN",
                "PORK_LOIN_BONELESS", "BEEF_CHUCK_ROLL")
PRODUCT_CLASSES = ("WHOLE_MUSCLE", "VAC_PACKED")
COUNTRIES = ("USA", "CAN", "MEX", "AUS")


@bp.route("/meat-ops/primal-purchases", methods=["POST"])
def create_purchase():
    mw.authenticate((mw.MEAT_CUTTER, mw.MEAT_MANAGER))
    payload = v.body()

    department_id = v.field_id(payload, "department_id", required=True)
    primal_code = v.field_enum(payload, "primal_code", PRIMAL_CODES, required=True)
    product_class = v.field_enum(payload, "product_class", PRODUCT_CLASSES,
                                 required=True)
    country = v.field_enum(payload, "country_of_origin", COUNTRIES, required=True)
    vendor_name = v.field_str(payload, "vendor_name", required=True,
                              min_len=1, max_len=120)
    gross_weight_lb = v.field_num(payload, "gross_weight_lb", required=True, gt=0,
                                  places=2)
    invoice_cost_cents = v.field_int(payload, "invoice_cost_cents", required=True,
                                     minimum=1)
    freight_cost_cents = v.field_int(payload, "freight_cost_cents", minimum=0,
                                     default=0)
    vendor_allowance_cents = v.field_int(payload, "vendor_allowance_cents", minimum=0,
                                         default=0)
    receiving_shrink_lb = v.field_num(payload, "receiving_shrink_lb", minimum=0,
                                      default=rhu(0, 2), places=2)
    received_at_raw, received_at = v.field_instant(payload, "received_at",
                                                   required=True)

    v.resolve("department", department_id)

    net_weight_lb = rhu(gross_weight_lb - receiving_shrink_lb, 2)
    if net_weight_lb <= 0:
        raise ApiError(errors.ERR_NET_WEIGHT_NOT_POSITIVE, 422,
                       "gross_weight_lb must exceed receiving_shrink_lb")

    landed_total = invoice_cost_cents + freight_cost_cents - vendor_allowance_cents

    purchase = make("PrimalPurchase", {
        "department_id": department_id,
        "primal_code": primal_code,
        "product_class": product_class,
        "country_of_origin": country,
        "vendor_name": vendor_name,
        "gross_weight_lb": rhu(gross_weight_lb, 2),
        "receiving_shrink_lb": rhu(receiving_shrink_lb, 2),
        "net_weight_lb": net_weight_lb,
        "invoice_cost_cents": invoice_cost_cents,
        "freight_cost_cents": freight_cost_cents,
        "vendor_allowance_cents": vendor_allowance_cents,
        "landed_cost_total_cents": landed_total,
        "landed_cost_per_lb_cents": rhu(landed_total / net_weight_lb, 4),
        "allocated_cost_cents": 0,
        "unallocated_cost_cents": landed_total,
        "received_at": received_at_raw,
        "status": "RECEIVED",
        "_received_at": received_at,
    })
    db.primal_purchases[purchase["id"]] = purchase
    return object_response(purchase, 201)


@bp.route("/meat-ops/primal-purchases/<purchase_id>", methods=["GET"])
def get_purchase(purchase_id):
    mw.authenticate(mw.NO_SERVICE_CLERK)
    purchase = v.resolve("primal_purchase", purchase_id)
    return object_response(purchase)


@bp.route("/meat-ops/departments/<department_id>/primal-purchases", methods=["GET"])
def list_department_purchases(department_id):
    mw.authenticate(mw.NO_SERVICE_CLERK)
    v.resolve("department", department_id)
    limit, offset = v.pagination()
    status = v.query_filter("status")
    rows = [row for row in db.primal_purchases.values()
            if row["department_id"] == department_id
            and (status is None or row["status"] == status)]
    return list_response(sort_rows(rows), limit, offset)
