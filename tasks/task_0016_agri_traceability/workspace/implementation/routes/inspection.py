"""Inspection-report state-transition endpoints."""

from flask import Blueprint

from middleware import require_roles
from response import success
from services import inspection as svc


bp = Blueprint("inspection", __name__)


@bp.route("/inspection-reports/<report_id>/issue", methods=["POST"])
@require_roles("Inspector")
def issue(report_id):
    return success(svc.issue_report(report_id))


@bp.route("/inspection-reports/<report_id>/revoke", methods=["POST"])
@require_roles("RegulatoryOfficer")
def revoke(report_id):
    return success(svc.revoke_report(report_id))
