"""WorkOrder endpoints: open, read, assign, request-info, submit-info,
resolve, escalate, close."""

from flask import Blueprint, request

import auth
import envelope
import projection
import state
import validators
from services import work_orders as svc


bp = Blueprint("work_orders", __name__)


_LEGAL_CATEGORIES = {
    "DELIVERY_LATE", "FOOD_QUALITY", "MISSING_ITEM", "RIDER_BEHAVIOR",
    "RESTAURANT_BEHAVIOR", "PAYMENT_ISSUE", "OTHER",
}

_LEGAL_OPENER_ROLES = {"CUSTOMER", "RIDER", "RESTAURANT", "CUSTOMER_SERVICE"}


def _read_payload():
    try:
        return request.get_json(silent=True) or {}
    except Exception:
        return {}


def _opener_role_for_user_role(role):
    return {
        "Customer": "CUSTOMER",
        "Rider": "RIDER",
        "Restaurant": "RESTAURANT",
        "CustomerService": "CUSTOMER_SERVICE",
        "PlatformAdmin": "CUSTOMER_SERVICE",
    }.get(role)


@bp.route("/api/work-orders", methods=["POST"])
def open_wo():
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("Customer", "Rider", "Restaurant",
                    "CustomerService", "PlatformAdmin"):
        return envelope.forbidden()

    payload = _read_payload()
    err = validators.require_body(payload)
    if err:
        return err

    if "category" not in payload or payload["category"] not in _LEGAL_CATEGORIES:
        return envelope.validation(
            "category must be one of " + ", ".join(sorted(_LEGAL_CATEGORIES))
        )

    opener_role = _opener_role_for_user_role(role)
    related_order_id = payload.get("related_order_id")
    related_return_id = payload.get("related_return_id")

    with state.lock():
        if related_order_id is not None and \
                related_order_id not in state.STORE.orders:
            return envelope.not_found("related_order_id not found.")
        if related_return_id is not None and \
                related_return_id not in state.STORE.returns:
            return envelope.not_found("related_return_id not found.")

        rec = svc.new_work_order(
            opened_by_role=opener_role,
            opened_by_id=user_id,
            category=payload["category"],
            related_order_id=related_order_id,
            related_return_id=related_return_id,
        )
        return envelope.created(projection.render(rec))


@bp.route("/api/work-orders/<wid>", methods=["GET"])
def get_wo(wid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("PlatformAdmin", "CustomerService", "Customer",
                    "Rider", "Restaurant"):
        return envelope.forbidden()
    with state.lock():
        rec = state.STORE.work_orders.get(wid)
        if rec is None:
            return envelope.not_found("WorkOrder not found.")
        # Openers can only read their own ticket.
        opener_role = _opener_role_for_user_role(role)
        if role in ("Customer", "Rider", "Restaurant"):
            if rec["opened_by_role"] != opener_role \
                    or rec["opened_by_id"] != user_id:
                return envelope.forbidden()
        return envelope.success(projection.render(rec))


@bp.route("/api/work-orders/<wid>/assign", methods=["POST"])
def assign(wid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("CustomerService", "PlatformAdmin"):
        return envelope.forbidden()
    with state.lock():
        rec = state.STORE.work_orders.get(wid)
        if rec is None:
            return envelope.not_found("WorkOrder not found.")
        if rec["status"] != "OPEN":
            return envelope.invalid_state(
                "WorkOrder must be OPEN to assign."
            )
        rec["status"] = "UNDER_REVIEW"
        rec["assigned_cs_user_id"] = user_id
        svc.bump(rec)
        return envelope.success(projection.render(rec))


@bp.route("/api/work-orders/<wid>/request-info", methods=["POST"])
def request_info(wid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("CustomerService", "PlatformAdmin"):
        return envelope.forbidden()
    with state.lock():
        rec = state.STORE.work_orders.get(wid)
        if rec is None:
            return envelope.not_found("WorkOrder not found.")
        if rec["status"] != "UNDER_REVIEW":
            return envelope.invalid_state(
                "WorkOrder must be UNDER_REVIEW to request info."
            )
        rec["status"] = "AWAITING_INFO"
        svc.bump(rec)
        return envelope.success(projection.render(rec))


@bp.route("/api/work-orders/<wid>/submit-info", methods=["POST"])
def submit_info(wid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("Customer", "Rider", "Restaurant"):
        return envelope.forbidden()
    with state.lock():
        rec = state.STORE.work_orders.get(wid)
        if rec is None:
            return envelope.not_found("WorkOrder not found.")
        if rec["status"] != "AWAITING_INFO":
            return envelope.invalid_state(
                "WorkOrder must be AWAITING_INFO to submit info."
            )
        if rec["opened_by_id"] != user_id:
            return envelope.forbidden()
        rec["status"] = "UNDER_REVIEW"
        svc.bump(rec)
        return envelope.success(projection.render(rec))


@bp.route("/api/work-orders/<wid>/resolve", methods=["POST"])
def resolve(wid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("CustomerService", "PlatformAdmin"):
        return envelope.forbidden()
    payload = _read_payload()
    err = validators.require_body(payload)
    if err:
        return err
    notes = payload.get("resolution_notes")
    if not isinstance(notes, str) or not notes.strip():
        return envelope.validation(
            "resolution_notes must be a non-empty string."
        )

    with state.lock():
        rec = state.STORE.work_orders.get(wid)
        if rec is None:
            return envelope.not_found("WorkOrder not found.")
        if rec["status"] not in ("UNDER_REVIEW", "ESCALATED"):
            return envelope.invalid_state(
                "WorkOrder must be UNDER_REVIEW or ESCALATED to resolve."
            )
        if rec["assigned_cs_user_id"] is None:
            return envelope.invalid_state(
                "WorkOrder must be assigned before resolving."
            )
        if rec.get("related_return_id"):
            linked = state.STORE.returns.get(rec["related_return_id"])
            if linked is not None and \
                    linked["status"] in ("REQUESTED", "ESCALATED"):
                return envelope.error(
                    422, "ERR_RELATED_RETURN_UNRESOLVED",
                    "Linked return is not yet resolved.",
                )
        rec["status"] = "RESOLVED"
        rec["resolution_notes"] = notes
        svc.bump(rec)
        return envelope.success(projection.render(rec))


@bp.route("/api/work-orders/<wid>/escalate", methods=["POST"])
def escalate(wid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("CustomerService", "PlatformAdmin"):
        return envelope.forbidden()
    with state.lock():
        rec = state.STORE.work_orders.get(wid)
        if rec is None:
            return envelope.not_found("WorkOrder not found.")
        if rec["status"] != "UNDER_REVIEW":
            return envelope.invalid_state(
                "WorkOrder must be UNDER_REVIEW to escalate."
            )
        rec["status"] = "ESCALATED"
        svc.bump(rec)
        return envelope.success(projection.render(rec))


@bp.route("/api/work-orders/<wid>/close", methods=["POST"])
def close(wid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("CustomerService", "PlatformAdmin"):
        return envelope.forbidden()
    with state.lock():
        rec = state.STORE.work_orders.get(wid)
        if rec is None:
            return envelope.not_found("WorkOrder not found.")
        if rec["status"] != "RESOLVED":
            return envelope.invalid_state(
                "WorkOrder must be RESOLVED to close."
            )
        rec["status"] = "CLOSED"
        svc.bump(rec)
        return envelope.success(projection.render(rec))
