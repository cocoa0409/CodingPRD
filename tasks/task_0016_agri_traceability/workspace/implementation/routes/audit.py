"""Audit-log query endpoints."""

from flask import Blueprint, request

from middleware import require_roles
from response import paginated
from services import audit_query as svc


bp = Blueprint("audit", __name__)


@bp.route("/audit-logs", methods=["GET"])
@require_roles("RegulatoryOfficer")
def list_():
    items, limit, offset, total = svc.list_audit_logs(request.args)
    return paginated(items, limit, offset, total)
