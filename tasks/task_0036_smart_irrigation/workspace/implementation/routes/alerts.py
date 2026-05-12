"""Alert routes."""

from flask import Blueprint, g, request

from clock import CLOCK
from db import DB, LOCK
from errors import forbidden, invalid_state, not_found
from middleware import require_roles
from response import success_array, success_object
from services.calculations import compute_severity
from services.common import (
    bump_version,
    fetch_or_404,
    paginate,
    parse_pagination,
)
from services.serializers import alert_view


bp = Blueprint("alerts", __name__)


@bp.route("/alerts/<alert_id>", methods=["GET"])
def read_alert(alert_id):
    if g.role not in {"PlatformAdmin", "WaterAdmin", "Operator"}:
        raise forbidden()
    with LOCK:
        rec = fetch_or_404(DB.alerts, alert_id)
        # Reads recompute severity using the reconciled variant.
        sev, _ = compute_severity(rec, CLOCK.now(), reconciled=True)
    return success_object(alert_view(rec, severity_override=sev))


@bp.route("/alerts/<alert_id>/acknowledge", methods=["POST"])
@require_roles("Operator", "WaterAdmin")
def ack_alert(alert_id):
    with LOCK:
        rec = fetch_or_404(DB.alerts, alert_id)
        if rec["status"] not in ("TRIGGERED", "REOPENED"):
            raise invalid_state("Alert must be TRIGGERED or REOPENED to acknowledge")
        rec["status"] = "ACKNOWLEDGED"
        rec["acknowledged_by"] = g.user_id
        bump_version(rec)
    return success_object(alert_view(rec))


@bp.route("/alerts/<alert_id>/resolve", methods=["POST"])
@require_roles("Operator", "WaterAdmin")
def resolve_alert(alert_id):
    with LOCK:
        rec = fetch_or_404(DB.alerts, alert_id)
        if rec["status"] != "ACKNOWLEDGED":
            raise invalid_state("Alert must be ACKNOWLEDGED to resolve")
        rec["status"] = "RESOLVED"
        rec["resolved_by"] = g.user_id
        bump_version(rec)
    return success_object(alert_view(rec))


@bp.route("/alerts", methods=["GET"])
def list_alerts():
    if g.role not in {"PlatformAdmin", "WaterAdmin", "Operator"}:
        raise forbidden()
    limit, offset = parse_pagination()
    status = request.args.get("status")
    severity = request.args.get("severity")
    subject_type = request.args.get("subject_type")
    with LOCK:
        items = list(DB.alerts.values())
        if status:
            items = [a for a in items if a.get("status") == status]
        if subject_type:
            items = [a for a in items if a.get("subject_type") == subject_type]
        items.sort(key=lambda r: r.get("created_at"))
        # Compute reconciled severity for filter
        results = []
        now = CLOCK.now()
        for a in items:
            sev, _ = compute_severity(a, now, reconciled=True)
            if severity and sev != severity:
                continue
            results.append(alert_view(a, severity_override=sev))
        page, total, has_more = paginate(results, limit, offset)
    return success_array(page, limit, offset, total, has_more)
