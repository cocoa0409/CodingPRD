"""Fraud alerts: read/list (audit roles) and resolve (FraudInvestigator)."""

from flask import Blueprint, request

from db import store, touch, sorted_created
from errors import ApiError, ERR_FRAUD_ALERT_NOT_FOUND, ERR_ALERT_NOT_OPEN, ERR_INVALID_REQUEST
from middleware import (
    get_context,
    body_json,
    req_enum,
    opt_str,
    pagination_params,
    paginate,
    AUDIT_READ_ROLES,
    ROLE_FRAUD_INVESTIGATOR,
)
from response import success_object, success_list
from serialize import fraud_alert_view
from services.fraud import dismiss_alert, confirm_alert

bp = Blueprint("fraud", __name__)

RESOLUTIONS = {"CONFIRMED", "DISMISSED"}


@bp.route("/fraud-alerts/<aid>", methods=["GET"])
def get_fraud_alert(aid):
    get_context(AUDIT_READ_ROLES)
    alert = store.fraud_alerts.get(aid)
    if alert is None:
        raise ApiError(ERR_FRAUD_ALERT_NOT_FOUND, 404, "Fraud alert does not exist")
    return success_object(fraud_alert_view(alert))


@bp.route("/fraud-alerts", methods=["GET"])
def list_fraud_alerts():
    get_context(AUDIT_READ_ROLES)
    limit, offset = pagination_params()
    items = sorted_created(store.fraud_alerts.values())
    policyholder_id = request.args.get("policyholder_id")
    claim_id = request.args.get("claim_id")
    status = request.args.get("status")
    if policyholder_id is not None:
        items = [a for a in items if a["policyholder_id"] == policyholder_id]
    if claim_id is not None:
        items = [a for a in items if a["claim_id"] == claim_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([fraud_alert_view(a) for a in page], limit, offset, total)


@bp.route("/fraud-alerts/<aid>/resolve", methods=["POST"])
def resolve_fraud_alert(aid):
    get_context([ROLE_FRAUD_INVESTIGATOR])
    alert = store.fraud_alerts.get(aid)
    if alert is None:
        raise ApiError(ERR_FRAUD_ALERT_NOT_FOUND, 404, "Fraud alert does not exist")
    if alert["status"] != "OPEN":
        raise ApiError(ERR_ALERT_NOT_OPEN, 409, "resolve requires FraudAlert OPEN")
    data = body_json(required=True)
    resolution = req_enum(data, "resolution", RESOLUTIONS)
    notes = opt_str(data, "resolution_notes", None)
    if notes is not None:
        alert["resolution_notes"] = notes
    alert["status"] = resolution
    touch(alert)
    if resolution == "DISMISSED":
        dismiss_alert(alert)
    else:
        confirm_alert(alert)
    return success_object(fraud_alert_view(alert))
