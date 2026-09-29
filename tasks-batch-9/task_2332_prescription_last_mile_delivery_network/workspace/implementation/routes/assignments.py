"""Courier responses to an offer, and the operator revocation path."""

from flask import Blueprint

import middleware
import response
import serializers
import validation as v
from db import db, touch
from errors import api_error
from middleware import ROLE_COURIER, ROLE_OPS, require_roles
from services import cascades
from services import couriers as courier_service

bp = Blueprint("assignments", __name__)


def _load_assignment(assignment_id, courier_scope=False):
    assignment = db.courier_assignments.get(assignment_id)
    if assignment is not None and courier_scope:
        middleware.guard_courier_scope(assignment["courier_id"])
    if assignment is None:
        raise api_error("ERR_ASSIGNMENT_NOT_FOUND")
    return assignment


@bp.post("/courier-assignments/<assignment_id>/accept")
@require_roles(ROLE_COURIER)
def accept(assignment_id):
    assignment = _load_assignment(assignment_id, courier_scope=True)
    delivery = db.deliveries.get(assignment["delivery_id"])
    courier = db.couriers.get(assignment["courier_id"])

    if assignment["status"] != "OFFERED":
        raise api_error("ERR_INVALID_ASSIGNMENT_STATE",
                        "Only an OFFERED assignment may be accepted.")
    if db.clock >= assignment["offer_expires_at"]:
        raise api_error("ERR_OFFER_EXPIRED", "The offer's time to live has elapsed.")

    if courier["status"] == "SUSPENDED":
        raise api_error("ERR_COURIER_SUSPENDED")
    if courier["status"] == "OFFLINE":
        raise api_error("ERR_COURIER_UNAVAILABLE")

    if delivery["custody_status"] != "QUEUED":
        raise api_error("ERR_INVALID_CUSTODY_STATE",
                        "The delivery is no longer QUEUED.")

    window = db.delivery_windows.get(delivery["window_id"])
    if courier_service.has_overlap_conflict(courier, window,
                                           exclude_delivery_id=delivery["id"]):
        raise api_error("ERR_COURIER_OVERLAP_CONFLICT",
                        "The courier already holds a leg whose buffered interval "
                        "touches this window.")

    assignment["status"] = "ACCEPTED"
    assignment["responded_at"] = db.clock
    touch(assignment)

    delivery["custody_status"] = "ASSIGNED"
    delivery["courier_id"] = courier["id"]
    touch(delivery)

    if courier["status"] == "AVAILABLE":
        courier["status"] = "ON_ROUTE"
    touch(courier)

    return response.single(serializers.courier_assignment(assignment), 200)


@bp.post("/courier-assignments/<assignment_id>/decline")
@require_roles(ROLE_COURIER)
def decline(assignment_id):
    assignment = _load_assignment(assignment_id, courier_scope=True)
    delivery = db.deliveries.get(assignment["delivery_id"])

    body = v.json_body()
    notes = v.string_field(body, "notes", required=False, default=None, max_len=1000)

    if assignment["status"] != "OFFERED":
        raise api_error("ERR_INVALID_ASSIGNMENT_STATE",
                        "Only an OFFERED assignment may be declined.")

    assignment["status"] = "DECLINED"
    assignment["responded_at"] = db.clock
    if notes is not None:
        assignment["notes"] = notes
    touch(assignment)

    cascades.exclude_courier(delivery, assignment["courier_id"])
    touch(delivery)
    return response.single(serializers.courier_assignment(assignment), 200)


@bp.post("/courier-assignments/<assignment_id>/revoke")
@require_roles(ROLE_OPS)
def revoke(assignment_id):
    assignment = _load_assignment(assignment_id)
    delivery = db.deliveries.get(assignment["delivery_id"])
    courier = db.couriers.get(assignment["courier_id"])

    body = v.json_body()
    notes = v.string_field(body, "notes", required=False, default=None, max_len=1000)

    if assignment["status"] not in {"OFFERED", "ACCEPTED"}:
        raise api_error("ERR_INVALID_ASSIGNMENT_STATE",
                        "Only an OFFERED or ACCEPTED assignment may be revoked.")
    was_accepted = assignment["status"] == "ACCEPTED"
    if was_accepted and delivery["custody_status"] not in {"QUEUED", "ASSIGNED"}:
        raise api_error("ERR_INVALID_CUSTODY_STATE",
                        "An accepted leg may only be pulled back before pickup.")

    assignment["status"] = "REVOKED"
    assignment["revoked_by_ops_user_id"] = middleware.actor_id()
    if notes is not None:
        assignment["notes"] = notes
    touch(assignment)

    cascades.exclude_courier(delivery, assignment["courier_id"])
    if was_accepted and delivery["custody_status"] == "ASSIGNED":
        delivery["custody_status"] = "QUEUED"
        delivery["courier_id"] = None
    touch(delivery)

    if was_accepted:
        courier_service.release_courier(courier)
    else:
        touch(courier)

    return response.single(serializers.courier_assignment(assignment), 200)
