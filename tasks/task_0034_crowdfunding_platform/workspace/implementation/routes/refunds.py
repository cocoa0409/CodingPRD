"""Refund request endpoints."""

from flask import Blueprint, g

from db import DB, LOCK, new_id
from errors import (
    forbidden,
    invalid_state,
    not_found,
    refund_exceeds,
    validation_error,
)
from middleware import require_roles
from response import success_object
from services.audit import append_audit
from services.common import (
    bump_version,
    get_json_body,
    require_positive_int,
    require_str,
    stamp_create,
)
from services.refunds import execute_refund_internal
from services.serializers import refund_view


bp = Blueprint("refunds", __name__)


VALID_REASONS = {"PROJECT_FAILED", "PROJECT_CANCELLED", "DISPUTE", "PLATFORM_MANDATORY"}


@bp.route("/refund-requests", methods=["POST"])
@require_roles("Backer", "PlatformAdmin")
def create_refund():
    body = get_json_body()
    order_id = body.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        raise validation_error("order_id required")
    reason = body.get("reason")
    if reason not in VALID_REASONS:
        raise validation_error("reason invalid")
    requested = require_positive_int(body, "requested_amount_cents")

    with LOCK:
        order = DB.orders.get(order_id)
        if order is None:
            raise not_found()
        if g.role == "Backer" and order["backer_id"] != g.user_id:
            raise forbidden()
        if order["payment_status"] not in ("CHARGED", "PARTIALLY_REFUNDED"):
            raise invalid_state("Order not eligible for refund")
        remainder = int(order.get("refundable_remainder_cents", 0))
        if requested > remainder:
            raise refund_exceeds()
        triggered_by = "BACKER" if g.role == "Backer" else "PLATFORM_AUTO"
        rec = stamp_create({
            "id": new_id(),
            "order_id": order_id,
            "reason": reason,
            "requested_amount_cents": requested,
            "status": "PENDING_REVIEW",
            "approved_amount_cents": None,
            "rejection_reason": None,
            "triggered_by": triggered_by,
        })
        DB.refund_requests[rec["id"]] = rec
        append_audit(
            subject_type="REFUND_REQUEST",
            subject_id=rec["id"],
            event_type="STATUS_CHANGE",
            payload={"from": None, "to": "PENDING_REVIEW", "reason": reason, "amount": requested},
            actor_role=g.role,
            actor_id=g.user_id,
        )
    return success_object(refund_view(rec), status=201)


@bp.route("/refund-requests/<id>", methods=["GET"])
@require_roles("Backer", "Initiator", "PlatformAdmin")
def get_refund(id):
    with LOCK:
        rec = DB.refund_requests.get(id)
        if rec is None:
            raise not_found()
        if g.role == "Backer":
            order = DB.orders.get(rec["order_id"])
            if order is None or order["backer_id"] != g.user_id:
                raise forbidden()
        elif g.role == "Initiator":
            order = DB.orders.get(rec["order_id"])
            project = DB.projects.get(order["project_id"]) if order is not None else None
            if project is None or project["initiator_id"] != g.user_id:
                raise forbidden()
        return success_object(refund_view(rec))


@bp.route("/refund-requests/<id>/approve", methods=["POST"])
@require_roles("PlatformAdmin")
def approve_refund(id):
    with LOCK:
        rec = DB.refund_requests.get(id)
        if rec is None:
            raise not_found()
        if rec["status"] != "PENDING_REVIEW":
            raise invalid_state("Refund not in PENDING_REVIEW")
        order = DB.orders.get(rec["order_id"])
        if order is None:
            raise not_found()
        if order["payment_status"] not in ("CHARGED", "PARTIALLY_REFUNDED"):
            raise invalid_state("Order not eligible for refund")
        remainder = int(order.get("refundable_remainder_cents", 0))
        if int(rec["requested_amount_cents"]) > remainder:
            raise refund_exceeds()
        rec["status"] = "APPROVED"
        rec["approved_amount_cents"] = int(rec["requested_amount_cents"])
        bump_version(rec)
        append_audit(
            subject_type="REFUND_REQUEST",
            subject_id=rec["id"],
            event_type="STATUS_CHANGE",
            payload={"from": "PENDING_REVIEW", "to": "APPROVED"},
            actor_role=g.role,
            actor_id=g.user_id,
        )
        return success_object(refund_view(rec))


@bp.route("/refund-requests/<id>/reject", methods=["POST"])
@require_roles("PlatformAdmin")
def reject_refund(id):
    body = get_json_body()
    rejection_reason = require_str(body, "rejection_reason")
    with LOCK:
        rec = DB.refund_requests.get(id)
        if rec is None:
            raise not_found()
        if rec["status"] != "PENDING_REVIEW":
            raise invalid_state("Refund not in PENDING_REVIEW")
        rec["status"] = "REJECTED"
        rec["rejection_reason"] = rejection_reason
        bump_version(rec)
        append_audit(
            subject_type="REFUND_REQUEST",
            subject_id=rec["id"],
            event_type="STATUS_CHANGE",
            payload={"from": "PENDING_REVIEW", "to": "REJECTED", "reason": rejection_reason},
            actor_role=g.role,
            actor_id=g.user_id,
        )
        return success_object(refund_view(rec))


@bp.route("/refund-requests/<id>/execute", methods=["POST"])
@require_roles("PlatformAdmin")
def execute_refund(id):
    with LOCK:
        rec = DB.refund_requests.get(id)
        if rec is None:
            raise not_found()
        if rec["status"] != "APPROVED":
            raise invalid_state("Refund not in APPROVED")
        execute_refund_internal(rec, actor_role=g.role, actor_id=g.user_id)
        return success_object(refund_view(rec))
