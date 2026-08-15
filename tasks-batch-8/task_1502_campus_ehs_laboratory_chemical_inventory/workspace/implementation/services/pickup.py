"""Waste pickup request cycle (PRD §3.4)."""
from datetime import timedelta

import db
from errors import (ApiError, ERR_PICKUP_STATE, ERR_PICKUP_EMPTY, ERR_LAB_FROZEN,
                    ERR_CONTAINER_STATE, ERR_CROSS_LAB_REFERENCE,
                    ERR_INVALID_WINDOW, ERR_DOCK_WINDOW_CONFLICT, forbidden_ownership)
from services.common import touch, refresh_posture, DOCK_BUFFER_MINUTES

EDITABLE_STATUSES = ("DRAFT", "REJECTED")


def create_request(lab, user_id):
    if user_id != lab["pi_worker_id"]:
        raise forbidden_ownership("Pickup request must be created by the lab's PI")
    if lab["posture"] == "FROZEN":
        raise ApiError(ERR_LAB_FROZEN, "Lab posture FROZEN blocks pickup request creation", 409)
    rec = {
        "id": db.new_id(),
        "lab_id": lab["id"],
        "status": "DRAFT",
        "dock_id": None,
        "window_start": None,
        "window_end": None,
        "rejection_reason": None,
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.waste_pickup_requests[rec["id"]] = rec
    return rec


def add_item(rec, container):
    if rec["status"] not in EDITABLE_STATUSES:
        raise ApiError(ERR_PICKUP_STATE,
                       "Items can only be added while DRAFT or REJECTED", 409)
    if container["state"] != "WASTE_TAGGED":
        raise ApiError(ERR_CONTAINER_STATE,
                       "Only WASTE_TAGGED containers can be added to a pickup request", 409)
    if container["lab_id"] != rec["lab_id"]:
        raise ApiError(ERR_CROSS_LAB_REFERENCE,
                       "Container belongs to a different lab than the request", 422)
    container["pickup_request_id"] = rec["id"]
    touch(container)
    touch(rec)
    return rec


def remove_item(rec, container):
    if rec["status"] not in EDITABLE_STATUSES:
        raise ApiError(ERR_PICKUP_STATE,
                       "Items can only be removed while DRAFT or REJECTED", 409)
    if container["pickup_request_id"] != rec["id"]:
        raise ApiError(ERR_CONTAINER_STATE,
                       "Container is not linked to this pickup request", 409)
    container["pickup_request_id"] = None
    touch(container)
    touch(rec)
    return rec


def submit(rec, lab, user_id):
    if rec["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError(ERR_PICKUP_STATE,
                       "Pickup request must be DRAFT or REJECTED to submit", 409)
    if user_id != lab["pi_worker_id"]:
        raise forbidden_ownership("Pickup request must be submitted by the lab's PI")
    if lab["posture"] == "FROZEN":
        raise ApiError(ERR_LAB_FROZEN, "Lab posture FROZEN blocks pickup submission", 409)
    linked = [c for c in db.containers.values() if c["pickup_request_id"] == rec["id"]]
    if len(linked) < 1:
        raise ApiError(ERR_PICKUP_EMPTY,
                       "Pickup request requires at least one linked container", 422)
    rec["status"] = "SUBMITTED"
    rec["rejection_reason"] = None
    touch(rec)
    return rec


def reject(rec, reason):
    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_PICKUP_STATE,
                       "Pickup request must be SUBMITTED to reject", 409)
    rec["status"] = "REJECTED"
    rec["rejection_reason"] = reason
    # Container links deliberately preserved for the revision loop.
    touch(rec)
    return rec


def schedule(rec, dock_id, window_start, window_end):
    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_PICKUP_STATE,
                       "Pickup request must be SUBMITTED to schedule", 409)
    if not (window_end > window_start):
        raise ApiError(ERR_INVALID_WINDOW, "window_end must be strictly after window_start", 400)
    buffer = timedelta(minutes=DOCK_BUFFER_MINUTES)
    for other in db.waste_pickup_requests.values():
        if other["id"] == rec["id"]:
            continue
        if other["status"] != "SCHEDULED" or other["dock_id"] != dock_id:
            continue
        # 30-minute buffered overlap: a gap of exactly 30 minutes on the
        # relevant side is allowed; anything less is a conflict.
        gap_ok = (window_start >= other["window_end"] + buffer) or \
                 (other["window_start"] >= window_end + buffer)
        if not gap_ok:
            raise ApiError(ERR_DOCK_WINDOW_CONFLICT,
                           "Dock window violates the 30-minute buffer", 409)
    rec["dock_id"] = dock_id
    rec["window_start"] = window_start
    rec["window_end"] = window_end
    rec["status"] = "SCHEDULED"
    touch(rec)
    return rec


def complete(rec, lab):
    if rec["status"] != "SCHEDULED":
        raise ApiError(ERR_PICKUP_STATE,
                       "Pickup request must be SCHEDULED to complete", 409)
    for c in db.containers.values():
        if c["pickup_request_id"] == rec["id"] and c["state"] == "WASTE_TAGGED":
            c["state"] = "PICKED_UP"
            # accumulation_area_id retained for audit; excluded from counts
            # because counts filter on state == WASTE_TAGGED.
            touch(c)
    rec["status"] = "COMPLETED"
    touch(rec)
    refresh_posture(lab)
    return rec


def cancel(rec):
    if rec["status"] != "SCHEDULED":
        raise ApiError(ERR_PICKUP_STATE,
                       "Pickup request must be SCHEDULED to cancel", 409)
    for c in db.containers.values():
        if c["pickup_request_id"] == rec["id"]:
            c["pickup_request_id"] = None
            touch(c)
    rec["status"] = "CANCELLED"
    touch(rec)
    return rec
