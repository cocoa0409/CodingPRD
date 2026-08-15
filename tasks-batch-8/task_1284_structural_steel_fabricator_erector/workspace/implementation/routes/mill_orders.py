"""Mill order endpoints."""

from flask import Blueprint

import domain
from envelope import ok_object
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_WEIGHT_OUT_OF_TOLERANCE,
)
from store import new_record, store, touch, public
from validate import authenticate, get_body, req_enum, req_int, req_pos_int, req_str, require_role
from . import list_response

bp = Blueprint("mill_orders", __name__)

ADMIN = {"FABRICATOR_ADMIN"}
READERS = {"FABRICATOR_ADMIN", "DETAILER", "EOR", "FOREMAN", "WELDER", "QC_INSPECTOR", "GC_PM"}


def view(m):
    return public(m)


def get_order_or_404(mid):
    m = store.mill_orders.get(mid)
    if m is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Mill order not found.")
    return m


@bp.post("/mill-orders")
def create_mill_order():
    uid, role = authenticate()
    require_role(role, ADMIN)
    body = get_body()
    # Rung 3: body FK existence
    job_id = body.get("job_id")
    if job_id is not None and job_id not in store.jobs:
        raise ApiError(ERR_NOT_FOUND, 404, "Job not found.")
    # Rung 4: shape
    job_id = req_str(body, "job_id")
    material_grade = req_enum(body, "material_grade", ("A36", "A572", "A992"))
    ordered_weight_lbs = req_pos_int(body, "ordered_weight_lbs")
    unit_price = req_pos_int(body, "unit_price_per_cwt_cents")
    billing_mode = req_enum(body, "billing_mode", ("NOMINAL", "ACTUAL"))
    # Rung 6: material buying starts only once the job is awarded
    job = store.jobs[job_id]
    if job["status"] == "ESTIMATING":
        raise ApiError(ERR_INVALID_STATE, 409, "Mill orders may not be placed while the job is ESTIMATING.")
    m = new_record()
    m.update(
        {
            "job_id": job_id,
            "material_grade": material_grade,
            "ordered_weight_lbs": ordered_weight_lbs,
            "unit_price_per_cwt_cents": unit_price,
            "billing_mode": billing_mode,
            "received_weight_lbs": None,
            "invoice_amount_cents": None,
            "status": "PLACED",
        }
    )
    store.mill_orders[m["id"]] = m
    return ok_object(view(m), 201)


@bp.get("/mill-orders")
def list_mill_orders():
    uid, role = authenticate()
    require_role(role, READERS)
    return list_response(
        store.mill_orders.values(), view, [("job_id", "job_id"), ("status", "status")]
    )


@bp.get("/mill-orders/<mid>")
def get_mill_order(mid):
    uid, role = authenticate()
    require_role(role, READERS)
    return ok_object(view(get_order_or_404(mid)))


@bp.post("/mill-orders/<mid>/receive")
def receive_mill_order(mid):
    uid, role = authenticate()
    require_role(role, ADMIN)
    m = get_order_or_404(mid)
    body = get_body()
    received = req_int(body, "received_weight_lbs")
    if m["status"] != "PLACED":
        raise ApiError(ERR_INVALID_STATE, 409, "Mill order must be PLACED to receive.")
    # Rung 9: tolerance gate applies to both billing variants before invoicing
    if not domain.within_mill_tolerance(m["ordered_weight_lbs"], received):
        raise ApiError(
            ERR_WEIGHT_OUT_OF_TOLERANCE,
            409,
            "received_weight_lbs is outside +/-10% of ordered_weight_lbs.",
        )
    m["received_weight_lbs"] = received
    m["invoice_amount_cents"] = domain.mill_order_invoice(m)
    m["status"] = "RECEIVED"
    touch(m)
    return ok_object(view(m))
