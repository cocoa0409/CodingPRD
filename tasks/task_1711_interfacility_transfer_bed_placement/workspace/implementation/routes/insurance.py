"""Payer notification and the emergency exception (PRD 3.6)."""

from datetime import timedelta

from flask import Blueprint

from core import domain as D
from core import schema as S
from core.envelope import object_response, paginate, filter_exact
from core.errors import fail
from core.store import db, new_row, bump

bp = Blueprint("insurance", __name__)


@bp.post("/transfer-cases/<id>/insurance-notifications")
def create_notification(id):
    b = S.body()
    payer_id = S.need_str(b, "payer_id")
    channel = S.need_enum(b, "channel", D.PAYER_CHANNELS)
    case = D.get_case(id)
    if case is None:
        fail("ERR_CASE_NOT_FOUND", "TransferCase id does not exist.", 404)
    if case["status"] in ("INTAKE", "COMPLETED", "CANCELLED"):
        fail("ERR_INVALID_STATE",
             "The case must be past INTAKE and non-terminal.", 409)
    if D.live_notification_of(id) is not None:
        fail("ERR_DUPLICATE_NOTIFICATION",
             "The case already has a non-VOIDED InsuranceNotification.", 409)
    sla_due_at = case["emtala_determined_at"] + timedelta(
        minutes=D.SLA_MINUTES[case["emtala_obligation"]])
    row = new_row("insurance_notifications", {
        "transfer_case_id": id,
        "payer_id": payer_id,
        "channel": channel,
        "sla_due_at": sla_due_at,
        "notified_at": None,
        "status": "PENDING",
        "exception_reason": None,
    })
    return object_response(D.serialize_notification(row), 201)


@bp.get("/insurance-notifications")
def list_notifications():
    rows = db.ordered("insurance_notifications")
    rows = filter_exact(rows, "transfer_case_id")
    rows = filter_exact(rows, "status")
    return paginate(rows, D.serialize_notification)


@bp.get("/insurance-notifications/<id>")
def get_notification(id):
    row = db.insurance_notifications.get(id)
    if row is None:
        fail("ERR_NOTIFICATION_NOT_FOUND", "InsuranceNotification id does not exist.", 404)
    return object_response(D.serialize_notification(row), 200)


@bp.post("/insurance-notifications/<id>/notify")
def notify(id):
    row = db.insurance_notifications.get(id)
    if row is None:
        fail("ERR_NOTIFICATION_NOT_FOUND", "InsuranceNotification id does not exist.", 404)
    if row["status"] != "PENDING":
        fail("ERR_INVALID_STATE", "The notification is not PENDING.", 409)
    row["status"] = "NOTIFIED"
    row["notified_at"] = db.now
    bump(row)
    return object_response(D.serialize_notification(row), 200)


@bp.post("/insurance-notifications/<id>/claim-exception")
def claim_exception(id):
    b = S.body()
    reason = S.need_enum(b, "exception_reason", D.EXCEPTION_REASONS)
    row = db.insurance_notifications.get(id)
    if row is None:
        fail("ERR_NOTIFICATION_NOT_FOUND", "InsuranceNotification id does not exist.", 404)
    if row["status"] != "PENDING":
        fail("ERR_INVALID_STATE", "The notification is not PENDING.", 409)
    row["status"] = "EXCEPTION_CLAIMED"
    row["exception_reason"] = reason
    bump(row)
    return object_response(D.serialize_notification(row), 200)
