"""ContractAlert endpoints (PRD §3.9)."""

from flask import Blueprint, request

import db as _db
from errors import err_not_found, err_invalid_state, err_invalid_request
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.serializers import serialize_alert
from services.pricing import touch

bp = Blueprint("alerts", __name__)

ALERT_TYPES = {
    "TERM_EXPIRING_90", "TERM_EXPIRING_30", "TERM_EXPIRED",
    "ESCALATOR_UPCOMING", "AMENDMENT_EFFECTIVE",
}


@bp.get("/api/contract-alerts/<aid>")
def get_alert(aid):
    require_roles(ALL_ROLES)
    a = _db.store.alerts.get(aid)
    if a is None:
        raise err_not_found("ContractAlert not found")
    return success_object(serialize_alert(a))


@bp.get("/api/contract-alerts")
def list_alerts():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    contract_id = request.args.get("contract_id")
    escalator_id = request.args.get("escalator_id")
    amendment_id = request.args.get("amendment_id")
    alert_type = request.args.get("alert_type")
    status = request.args.get("status")
    if alert_type is not None and alert_type not in ALERT_TYPES:
        raise err_invalid_request("alert_type filter invalid")
    if status is not None and status not in {"TRIGGERED", "ACKNOWLEDGED", "DISMISSED"}:
        raise err_invalid_request("status filter invalid")
    items = list(_db.store.alerts.values())
    if contract_id is not None:
        items = [a for a in items if a["contract_id"] == contract_id]
    if escalator_id is not None:
        items = [a for a in items if a.get("escalator_id") == escalator_id]
    if amendment_id is not None:
        items = [a for a in items if a.get("amendment_id") == amendment_id]
    if alert_type is not None:
        items = [a for a in items if a["alert_type"] == alert_type]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: a["seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_alert(a) for a in page], limit, offset, total)


def _get_alert_or_404(aid):
    a = _db.store.alerts.get(aid)
    if a is None:
        raise err_not_found("ContractAlert not found")
    return a


@bp.post("/api/contract-alerts/<aid>/acknowledge")
def acknowledge_alert(aid):
    require_roles(["ContractManager"])
    a = _get_alert_or_404(aid)
    if a["status"] != "TRIGGERED":
        raise err_invalid_state("Only a TRIGGERED alert may be acknowledged")
    a["status"] = "ACKNOWLEDGED"
    touch(a)
    return success_object(serialize_alert(a))


@bp.post("/api/contract-alerts/<aid>/dismiss")
def dismiss_alert(aid):
    require_roles(["ContractManager"])
    a = _get_alert_or_404(aid)
    if a["status"] not in {"TRIGGERED", "ACKNOWLEDGED"}:
        raise err_invalid_state("Only a TRIGGERED or ACKNOWLEDGED alert may be dismissed")
    a["status"] = "DISMISSED"
    touch(a)
    return success_object(serialize_alert(a))
