"""Read-only report endpoints."""

from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import success_array
from errors import ERR_BAD_REQUEST, raise_error
from services.pagination import parse_pagination, paginate, sort_by_created_at_asc

bp = Blueprint("reports", __name__)


ANOMALY_RULES = {"ROLLING_WINDOW", "CUMULATIVE"}
ADJUSTMENT_TYPES = {"CANCEL", "EXCHANGE_TARGET", "INSERTION"}
ADJUSTMENT_REASONS = {"LOW_ATTENDANCE", "NEW_FILM_INSERTION", "INCIDENT"}
AUDIT_ACTIONS = {
    "FILM_RELEASE", "FILM_SHELVE", "FILM_DELIST", "SHOWTIME_CREATE", "SHOWTIME_CANCEL",
    "SETTLEMENT_POST", "SETTLEMENT_REVERSE", "TICKET_REFUND", "TICKET_EXCHANGE",
    "CLOCK_ADVANCE", "SWEEP_RUN",
}


@bp.route("/anomaly-alerts", methods=["GET"])
@require_roles({"PlatformAdmin", "CinemaOps", "FinanceOps", "Auditor"})
def list_anomaly_alerts():
    limit, offset = parse_pagination()
    showtime_id = request.args.get("showtime_id")
    buyer_external_id = request.args.get("buyer_external_id")
    rule = request.args.get("rule")
    if rule is not None and rule not in ANOMALY_RULES:
        raise_error(ERR_BAD_REQUEST, "invalid rule filter")
    items = []
    for a in db.anomaly_alerts.values():
        if showtime_id is not None and a["showtime_id"] != showtime_id:
            continue
        if buyer_external_id is not None and a["buyer_external_id"] != buyer_external_id:
            continue
        if rule is not None and a["rule"] != rule:
            continue
        items.append(dict(a))
    items = sort_by_created_at_asc(items)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total)


@bp.route("/schedule-adjustments", methods=["GET"])
@require_roles({"PlatformAdmin", "CinemaOps", "FinanceOps", "Auditor"})
def list_schedule_adjustments():
    limit, offset = parse_pagination()
    showtime_id = request.args.get("showtime_id")
    reason = request.args.get("reason")
    adjustment_type = request.args.get("adjustment_type")
    if reason is not None and reason not in ADJUSTMENT_REASONS:
        raise_error(ERR_BAD_REQUEST, "invalid reason filter")
    if adjustment_type is not None and adjustment_type not in ADJUSTMENT_TYPES:
        raise_error(ERR_BAD_REQUEST, "invalid adjustment_type filter")
    items = []
    for a in db.schedule_adjustments.values():
        if showtime_id is not None and a["showtime_id"] != showtime_id:
            continue
        if reason is not None and a["reason"] != reason:
            continue
        if adjustment_type is not None and a["adjustment_type"] != adjustment_type:
            continue
        items.append(dict(a))
    items = sort_by_created_at_asc(items)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total)


@bp.route("/audit-logs", methods=["GET"])
@require_roles({"PlatformAdmin", "Auditor"})
def list_audit_logs():
    limit, offset = parse_pagination()
    action = request.args.get("action")
    target_entity = request.args.get("target_entity")
    target_id = request.args.get("target_id")
    if action is not None and action not in AUDIT_ACTIONS:
        raise_error(ERR_BAD_REQUEST, "invalid action filter")
    items = []
    for a in db.audit_logs.values():
        if action is not None and a["action"] != action:
            continue
        if target_entity is not None and a["target_entity"] != target_entity:
            continue
        if target_id is not None and a["target_id"] != target_id:
            continue
        items.append(dict(a))
    items = sort_by_created_at_asc(items)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total)
