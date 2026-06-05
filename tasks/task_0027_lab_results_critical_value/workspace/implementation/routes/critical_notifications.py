"""CriticalNotification routes: send, escalate, acknowledge, list."""
from __future__ import annotations

from typing import Dict, Any

from flask import Blueprint, request

import db
from errors import (
    APIError, ERR_INVALID_STATE, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
    ERR_STAT_REQUIRES_PHONE_CHANNEL, ERR_ACK_WINDOW_CLOSED,
    ERR_ACK_WRONG_RECIPIENT,
)
from middleware import require_auth, get_json_body, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields, require_string, require_enum, lookup_or_404,
)
from services.calculations import compute_ack_deadline


bp = Blueprint("critical_notifications", __name__)

CHANNELS = {"SMS", "PHONE"}
ACK_METHODS = {"SMS_REPLY", "IVR_KEYPRESS", "WEB_UI"}


# ---------- GET /critical-notifications/{id} -----------------------------

@bp.get("/critical-notifications/<nid>")
def get_notification(nid):
    require_auth(["LabTech", "LabDirector", "OrderingProvider"])()
    n = lookup_or_404(db.critical_notifications, nid, "CriticalNotification")
    return ok_object(n)


# ---------- GET /critical-notifications ----------------------------------

@bp.get("/critical-notifications")
def list_notifications():
    require_auth(["LabTech", "LabDirector", "OrderingProvider"])()
    limit, offset = paginate_params(request.args)
    items = list(db.critical_notifications.values())
    for key in ("result_id", "recipient_clinician_id", "escalation_target_clinician_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [n for n in items if n.get(key) == val]
    items.sort(key=lambda x: x["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---------- POST /critical-notifications/{id}/send -----------------------

@bp.post("/critical-notifications/<nid>/send")
def send_notification(nid):
    require_auth(["LabTech"])()
    n = lookup_or_404(db.critical_notifications, nid, "CriticalNotification")

    if n.get("status") != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Notification.status '{n.get('status')}' is not PENDING")

    # Notification.result.status must be RELEASED.
    result = db.results.get(n.get("result_id"))
    if result is None or result.get("status") != "RELEASED":
        raise APIError(ERR_INVALID_STATE, 409,
                       "Parent Result must be RELEASED to send the notification")

    # STAT priority safety rule.
    order = db.lab_orders.get(result.get("lab_order_id"))
    if order and order.get("priority") == "STAT" and n.get("channel") != "PHONE":
        raise APIError(ERR_STAT_REQUIRES_PHONE_CHANNEL, 422,
                       "STAT-priority orders require channel=PHONE")

    sent_at_dt = db.get_current_utc_dt()
    n["status"] = "SENT"
    n["sent_at"] = db._dt_to_iso(sent_at_dt)
    n["ack_deadline_at"] = db._dt_to_iso(compute_ack_deadline(sent_at_dt, n["channel"]))
    n["attempt_count"] = int(n.get("attempt_count", 0)) + 1
    db.bump(n)

    # First time reaching SENT for this notification: increment patient.critical_incidents_count.
    # Because we just transitioned from PENDING to SENT, attempt_count is now 1 if this is
    # the very first send. Increment unconditionally on the FIRST SENT transition.
    # Track via a private flag on the notification.
    if not n.get("_first_send_recorded", False):
        n["_first_send_recorded"] = True
        if order:
            patient = db.patients.get(order.get("patient_id"))
            if patient:
                patient["critical_incidents_count"] = int(patient.get("critical_incidents_count", 0)) + 1
                db.bump(patient)

    return ok_object(_strip_private(n))


# ---------- POST /critical-notifications/{id}/escalate -------------------

@bp.post("/critical-notifications/<nid>/escalate")
def escalate_notification(nid):
    require_auth(["LabTech"])()
    n = lookup_or_404(db.critical_notifications, nid, "CriticalNotification")

    if n.get("status") != "SENT":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Notification.status '{n.get('status')}' is not SENT")

    # Deadline must have passed (strictly).
    dl = db.parse_iso_dt(n.get("ack_deadline_at"))
    now_dt = db.get_current_utc_dt()
    if dl is None or now_dt <= dl:
        raise APIError(ERR_INVALID_STATE, 409,
                       "Cannot escalate before ack_deadline_at has passed")

    recip = db.clinicians.get(n.get("recipient_clinician_id"))
    if recip is None or recip.get("backup_clinician_id") in (None, ""):
        raise APIError(ERR_INVALID_STATE, 409,
                       "Recipient has no backup_clinician_id to escalate to")

    n["status"] = "ESCALATED"
    n["escalation_target_clinician_id"] = recip.get("backup_clinician_id")
    n["attempt_count"] = int(n.get("attempt_count", 0)) + 1
    db.bump(n)

    # Cascade SECOND HOP: LabOrder.compliance_incident -> true.
    result = db.results.get(n.get("result_id"))
    if result is not None:
        order = db.lab_orders.get(result.get("lab_order_id"))
        if order is not None:
            order["compliance_incident"] = True
            db.bump(order)

    return ok_object(_strip_private(n))


# ---------- POST /critical-notifications/{id}/acknowledgements -----------

@bp.post("/critical-notifications/<nid>/acknowledgements")
def acknowledge_notification(nid):
    require_auth(["OrderingProvider"])()
    n = lookup_or_404(db.critical_notifications, nid, "CriticalNotification")
    body = get_json_body()
    require_fields(body, ["ack_method", "attestation_text"])
    ack_method = body["ack_method"]
    attestation = body["attestation_text"]

    require_enum(ack_method, ACK_METHODS, "ack_method")
    require_string(attestation, "attestation_text", min_len=1, max_len=500)

    if n.get("status") != "SENT":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Notification.status '{n.get('status')}' is not SENT")

    # Recipient ownership check.
    if current_user_id() != n.get("recipient_clinician_id"):
        raise APIError(ERR_ACK_WRONG_RECIPIENT, 403,
                       "X-User-ID does not match the notification's recipient_clinician_id")

    # Deadline window: now <= ack_deadline_at.
    dl = db.parse_iso_dt(n.get("ack_deadline_at"))
    now_dt = db.get_current_utc_dt()
    if dl is None or now_dt > dl:
        raise APIError(ERR_ACK_WINDOW_CLOSED, 409,
                       "Acknowledgement window has closed")

    # Persist receipt (immutable: only id + created_at).
    receipt = {
        "critical_notification_id": n["id"],
        "acknowledging_clinician_id": current_user_id(),
        "ack_method": ack_method,
        "attestation_text": attestation,
    }
    db.stamp_immutable(receipt)
    db.acknowledgement_receipts[receipt["id"]] = receipt

    # Notification transition.
    n["status"] = "ACKNOWLEDGED"
    db.bump(n)

    return ok_object(receipt, http_status=201)


# ---------- GET /critical-notifications/{id}/acknowledgements ------------

@bp.get("/critical-notifications/<nid>/acknowledgements")
def list_acks_for_notification(nid):
    require_auth(["LabTech", "LabDirector", "OrderingProvider"])()
    lookup_or_404(db.critical_notifications, nid, "CriticalNotification")
    limit, offset = paginate_params(request.args)
    items = [
        a for a in db.acknowledgement_receipts.values()
        if a.get("critical_notification_id") == nid
    ]
    items.sort(key=lambda x: x["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---- helper to strip private fields before returning -----------------

def _strip_private(obj: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in obj.items() if not k.startswith("_")}
