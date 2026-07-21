"""Delivery jobs and install referrals."""
from flask import Blueprint

import serializers
import services
from auth import require
from envelope import ok, created
from errors import err
from listing import list_response
from store import db, new_base, insert, touch, fetch, fk
from validation import get_body, req_datetime

bp = Blueprint("fulfillment", __name__)

GET_ALL = ("ShowroomAssociate", "StoreManager", "Designer", "FulfillmentCoordinator")


# --------------------------- DeliveryJob ---------------------------
@bp.post("/delivery-jobs")
@require("FulfillmentCoordinator", "StoreManager")
def create_delivery_job():
    body = get_body()
    order_id = body.get("order_id")
    if order_id is None:
        raise err("ERR_INVALID_REQUEST", "order_id is required")
    order = fk("orders", order_id)
    truck_id = body.get("delivery_truck_id")
    if truck_id is None:
        raise err("ERR_INVALID_REQUEST", "delivery_truck_id is required")
    fk("delivery_trucks", truck_id)
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")
    if window_end <= window_start:
        raise err("ERR_VALIDATION", "window_end must be after window_start")
    # truck buffer guard precedes the order-state guard (§2.8)
    if services.truck_window_conflict(truck_id, window_start, window_end):
        raise err("ERR_TRUCK_WINDOW_CONFLICT", "Delivery window conflicts on this truck")
    if order["fulfillment_status"] not in ("CONFIRMED", "COMPLETED"):
        raise err("ERR_ORDER_NOT_CONFIRMED", "Parent order is not CONFIRMED/COMPLETED")
    rec = new_base()
    rec.update(
        {
            "order_id": order_id,
            "delivery_truck_id": truck_id,
            "window_start": window_start,
            "window_end": window_end,
            "status": "SCHEDULED",
        }
    )
    insert("delivery_jobs", rec)
    return created(serializers.delivery_job(rec))


@bp.get("/delivery-jobs/<rec_id>")
@require(*GET_ALL)
def get_delivery_job(rec_id):
    return ok(serializers.delivery_job(fetch("delivery_jobs", rec_id)))


@bp.get("/delivery-jobs")
@require(*GET_ALL)
def list_delivery_jobs():
    return list_response(
        db.delivery_jobs.values(),
        serializers.delivery_job,
        {"order_id": "order_id", "delivery_truck_id": "delivery_truck_id"},
    )


@bp.post("/delivery-jobs/<rec_id>/deliver")
@require("FulfillmentCoordinator", "StoreManager")
def deliver(rec_id):
    rec = fetch("delivery_jobs", rec_id)
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Delivery job is not SCHEDULED")
    services.deliver_job(rec)
    return ok(serializers.delivery_job(rec))


# --------------------------- InstallReferral ---------------------------
@bp.post("/install-referrals")
@require("ShowroomAssociate", "FulfillmentCoordinator", "StoreManager")
def create_install_referral():
    body = get_body()
    order_id = body.get("order_id")
    if order_id is None:
        raise err("ERR_INVALID_REQUEST", "order_id is required")
    fk("orders", order_id)
    installer_id = body.get("installer_id")
    if installer_id is None:
        raise err("ERR_INVALID_REQUEST", "installer_id is required")
    installer = fk("installers", installer_id)
    delivery_job_id = body.get("delivery_job_id")
    if delivery_job_id is None:
        raise err("ERR_INVALID_REQUEST", "delivery_job_id is required")
    fk("delivery_jobs", delivery_job_id)
    rec = new_base()
    rec.update(
        {
            "order_id": order_id,
            "installer_id": installer_id,
            "delivery_job_id": delivery_job_id,
            "appointment_start": None,
            "appointment_end": None,
            "status": "REFERRED",
        }
    )
    insert("install_referrals", rec)
    installer["active_referral_count"] += 1
    touch(installer)
    return created(serializers.install_referral(rec))


@bp.get("/install-referrals/<rec_id>")
@require(*GET_ALL)
def get_install_referral(rec_id):
    return ok(serializers.install_referral(fetch("install_referrals", rec_id)))


@bp.get("/install-referrals")
@require(*GET_ALL)
def list_install_referrals():
    return list_response(
        db.install_referrals.values(),
        serializers.install_referral,
        {
            "order_id": "order_id",
            "installer_id": "installer_id",
            "delivery_job_id": "delivery_job_id",
        },
    )


@bp.post("/install-referrals/<rec_id>/schedule")
@require("FulfillmentCoordinator", "StoreManager")
def schedule_referral(rec_id):
    rec = fetch("install_referrals", rec_id)
    body = get_body()
    start = req_datetime(body, "appointment_start")
    end = req_datetime(body, "appointment_end")
    if rec["status"] != "REFERRED":
        raise err("ERR_INVALID_STATE", "Install referral is not REFERRED")
    job = db.delivery_jobs.get(rec["delivery_job_id"])
    if job is None or job["status"] != "DELIVERED":
        raise err("ERR_DELIVERY_NOT_READY", "Linked delivery job is not DELIVERED")
    if services.installer_has_overlap(rec["installer_id"], start, end, rec["id"]):
        raise err("ERR_INSTALLER_UNAVAILABLE", "Installer already booked in this window")
    rec["appointment_start"] = start
    rec["appointment_end"] = end
    rec["status"] = "SCHEDULED"
    touch(rec)
    return ok(serializers.install_referral(rec))


@bp.post("/install-referrals/<rec_id>/complete")
@require("FulfillmentCoordinator", "StoreManager")
def complete_referral(rec_id):
    rec = fetch("install_referrals", rec_id)
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Install referral is not SCHEDULED")
    rec["status"] = "COMPLETED"
    touch(rec)
    installer = db.installers.get(rec["installer_id"])
    if installer is not None:
        installer["active_referral_count"] -= 1
        touch(installer)
    return ok(serializers.install_referral(rec))
