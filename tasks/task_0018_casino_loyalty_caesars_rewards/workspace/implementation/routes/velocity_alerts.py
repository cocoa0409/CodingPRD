"""VelocityAlert read-only endpoints."""
from flask import Blueprint, request

import db
from auth import require_role
from common import parse_pagination, paginate, get_or_404
from response import success_object, success_array
from services.serializers import velocity_alert_view


bp = Blueprint("velocity_alerts", __name__)


@bp.route("/velocity-alerts/<vid>", methods=["GET"])
def get_alert(vid):
    require_role({"ComplianceOfficer"})
    with db.lock:
        row = get_or_404(db.velocity_alerts, vid, "velocity alert")
        return success_object(velocity_alert_view(row), 200)


@bp.route("/velocity-alerts", methods=["GET"])
def list_alerts():
    require_role({"ComplianceOfficer"})
    member_id = request.args.get("member_id")
    severity = request.args.get("severity")
    limit, offset = parse_pagination()
    with db.lock:
        rows = list(db.velocity_alerts.values())
        if member_id is not None:
            rows = [r for r in rows if r["member_id"] == member_id]
        if severity is not None:
            rows = [r for r in rows if r["severity"] == severity]
        rows.sort(key=lambda r: r["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array([velocity_alert_view(r) for r in page], limit, offset, total, 200)
