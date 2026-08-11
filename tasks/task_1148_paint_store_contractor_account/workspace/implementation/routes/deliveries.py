"""Delivery scheduling, dispatch, completion, and failure."""
from flask import Blueprint, request

import db
import services as svc
from authz import require_roles, owner_or_forbid, owner_of_delivery
from envelope import ok_object, ok_list
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_VALIDATION,
    ERR_INVALID_STATE, ERR_ACCOUNT_SUSPENDED, ERR_JOB_NOT_OPEN,
    ERR_DELIVERY_NOT_DISPATCHABLE, ERR_DELIVERY_NOT_EN_ROUTE,
    ERR_DELIVERY_WINDOW_PAST, ERR_DELIVERY_WINDOW_CONFLICT,
    ERR_VOC_LIMIT_EXCEEDED, ERR_JOB_ACCOUNT_MISMATCH,
)
from serializers import ser_delivery, sorted_rows
from validate import body_json, req_str, req_dt, pagination_params, query_enum_filter

bp = Blueprint("deliveries", __name__)

MANAGER = ["StoreManager"]
READERS = ["CorporateAdmin", "StoreManager", "StoreAssociate", "Contractor"]
DELIVERY_STATUS = {"SCHEDULED", "EN_ROUTE", "DELIVERED", "FAILED"}


def _get_delivery(delivery_id):
    d = db.deliveries.get(delivery_id)
    if d is None:
        raise_err(ERR_NOT_FOUND, "delivery %s not found" % delivery_id)
    return d


@bp.post("/deliveries")
def create_delivery():
    require_roles(MANAGER)
    data = body_json()
    order_id = data.get("order_id")
    job_account_id = data.get("job_account_id")
    if isinstance(order_id, str) and order_id not in db.orders:
        raise_err(ERR_REFERENCE_NOT_FOUND, "order_id %s not found" % order_id)
    if isinstance(job_account_id, str) and job_account_id not in db.job_accounts:
        raise_err(ERR_REFERENCE_NOT_FOUND, "job_account_id %s not found" % job_account_id)
    if not isinstance(order_id, str):
        raise_err(ERR_VALIDATION, "field 'order_id' is required and must be a string")
    if not isinstance(job_account_id, str):
        raise_err(ERR_VALIDATION, "field 'job_account_id' is required and must be a string")
    window_start = req_dt(data, "window_start")
    window_end = req_dt(data, "window_end")
    if not window_end > window_start:
        raise_err(ERR_VALIDATION, "field 'window_end' must be after 'window_start'")

    order = db.orders[order_id]
    job = db.job_accounts[job_account_id]
    account = db.contractor_accounts.get(order["contractor_account_id"])

    # State guards.
    if account is not None and account["status"] != "ACTIVE":
        raise_err(ERR_ACCOUNT_SUSPENDED, "contractor account is SUSPENDED")
    if job["status"] != "OPEN":
        raise_err(ERR_JOB_NOT_OPEN, "job account is not OPEN")

    # Temporal guards: window must not start in the past; 30-minute clearance buffer.
    if window_start < db.now():
        raise_err(ERR_DELIVERY_WINDOW_PAST, "window_start is before the logical clock now")
    if svc.delivery_window_conflict(job_account_id, window_start, window_end):
        raise_err(ERR_DELIVERY_WINDOW_CONFLICT,
                  "window violates the 30-minute clearance buffer for this job")

    # Referential: the delivery's job must equal the order's job.
    if job_account_id != order["job_account_id"]:
        raise_err(ERR_JOB_ACCOUNT_MISMATCH, "delivery job differs from the order's job")

    d = svc.stamp_new({
        "order_id": order_id,
        "job_account_id": job_account_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
        "failure_reason": None,
        "dispatched_at": None,
        "delivered_at": None,
    })
    db.deliveries[d["id"]] = d
    return ok_object(ser_delivery(d), 201)


@bp.get("/deliveries")
def list_deliveries():
    uid, role = require_roles(READERS)
    limit, offset = pagination_params()
    order_filter = request.args.get("order_id")
    job_filter = request.args.get("job_account_id")
    status_filter = query_enum_filter("status", DELIVERY_STATUS)
    rows = list(db.deliveries.values())
    if order_filter is not None:
        rows = [d for d in rows if d["order_id"] == order_filter]
        order = db.orders.get(order_filter)
        if role == "Contractor" and order is not None:
            owner_or_forbid(uid, role, order["contractor_account_id"])
    if job_filter is not None:
        rows = [d for d in rows if d["job_account_id"] == job_filter]
        job = db.job_accounts.get(job_filter)
        if role == "Contractor" and job is not None:
            owner_or_forbid(uid, role, job["contractor_account_id"])
    if role == "Contractor" and order_filter is None and job_filter is None:
        def owned(d):
            order = db.orders.get(d["order_id"])
            return order is not None and order["contractor_account_id"] == uid
        rows = [d for d in rows if owned(d)]
    if status_filter is not None:
        rows = [d for d in rows if d["status"] == status_filter]
    rows = sorted_rows(rows)
    total = len(rows)
    return ok_list([ser_delivery(d) for d in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/deliveries/<delivery_id>")
def get_delivery(delivery_id):
    uid, role = require_roles(READERS)
    d = _get_delivery(delivery_id)
    owner_of_delivery(uid, role, d)
    return ok_object(ser_delivery(d))


@bp.post("/deliveries/<delivery_id>/dispatch")
def dispatch_delivery(delivery_id):
    require_roles(MANAGER)
    d = _get_delivery(delivery_id)
    order = db.orders.get(d["order_id"])
    job = db.job_accounts.get(d["job_account_id"])
    # Guards in order: job OPEN, delivery SCHEDULED, order PAID, VOC at dispatch instant.
    if job is not None and job["status"] != "OPEN":
        raise_err(ERR_JOB_NOT_OPEN, "job account is not OPEN")
    if d["status"] != "SCHEDULED":
        raise_err(ERR_DELIVERY_NOT_DISPATCHABLE, "delivery is not SCHEDULED")
    if order is None or order["payment_status"] != "PAID":
        raise_err(ERR_INVALID_STATE, "order is not PAID")
    now = db.now()
    if job is not None:
        for line in db.order_lines.values():
            if line["order_id"] != order["id"]:
                continue
            product = db.products.get(line["product_id"])
            if product is None:
                continue
            rule = svc.voc_rule_at(job["jurisdiction_id"], product["category"], now)
            if rule is not None and product["voc_gpl"] > rule["max_voc_gpl"]:
                raise_err(ERR_VOC_LIMIT_EXCEEDED,
                          "product voc_gpl %d exceeds the effective limit %d at dispatch"
                          % (product["voc_gpl"], rule["max_voc_gpl"]))
    d["status"] = "EN_ROUTE"
    d["dispatched_at"] = now
    svc.bump(d)
    if order["fulfillment_status"] == "PENDING":
        order["fulfillment_status"] = "OUT_FOR_DELIVERY"
        svc.bump(order)
    return ok_object(ser_delivery(d))


@bp.post("/deliveries/<delivery_id>/mark-delivered")
def mark_delivered(delivery_id):
    require_roles(MANAGER)
    d = _get_delivery(delivery_id)
    if d["status"] != "EN_ROUTE":
        raise_err(ERR_DELIVERY_NOT_EN_ROUTE, "delivery is not EN_ROUTE")
    d["status"] = "DELIVERED"
    d["delivered_at"] = db.now()
    svc.bump(d)
    order = db.orders.get(d["order_id"])
    if order is not None and order["fulfillment_status"] == "OUT_FOR_DELIVERY":
        remaining_open = any(
            other["status"] in {"SCHEDULED", "EN_ROUTE"}
            for other in svc.deliveries_of_order(order["id"])
            if other["id"] != d["id"]
        )
        if not remaining_open:
            order["fulfillment_status"] = "DELIVERED"
            svc.bump(order)
    return ok_object(ser_delivery(d))


@bp.post("/deliveries/<delivery_id>/mark-failed")
def mark_failed(delivery_id):
    require_roles(MANAGER)
    d = _get_delivery(delivery_id)
    data = body_json()
    failure_reason = req_str(data, "failure_reason")
    if d["status"] != "EN_ROUTE":
        raise_err(ERR_DELIVERY_NOT_EN_ROUTE, "delivery is not EN_ROUTE")
    d["status"] = "FAILED"
    d["failure_reason"] = failure_reason
    svc.bump(d)
    # The order's fulfillment_status is deliberately unchanged; re-delivery is a
    # fresh Delivery row on the same order.
    return ok_object(ser_delivery(d))
