"""Closing-audit endpoints."""

from flask import Blueprint, g

from common import get_json_body
from middleware import require_roles
from response import success
from services.closing_audit import (
    close_audit,
    create_audit,
    flag_rectification,
    get_audit_or_404,
    resubmit_audit,
    serialize_audit,
    submit_audit,
)


bp = Blueprint("closing_audits", __name__)


@bp.route("/closing-audits", methods=["POST"])
@require_roles("PrincipalInvestigator")
def post_audit():
    body = get_json_body()
    a = create_audit(g.user_id, body)
    return success(serialize_audit(a), 201)


@bp.route("/closing-audits/<audit_id>", methods=["GET"])
@require_roles("Any")
def get_audit(audit_id):
    a = get_audit_or_404(audit_id)
    return success(serialize_audit(a), 200)


@bp.route("/closing-audits/<audit_id>/submit", methods=["POST"])
@require_roles("PrincipalInvestigator")
def post_submit_audit(audit_id):
    a = submit_audit(audit_id, g.user_id)
    return success(serialize_audit(a), 200)


@bp.route("/closing-audits/<audit_id>/flag-rectification", methods=["POST"])
@require_roles("AuditOfficer")
def post_flag(audit_id):
    a = flag_rectification(audit_id)
    return success(serialize_audit(a), 200)


@bp.route("/closing-audits/<audit_id>/resubmit", methods=["POST"])
@require_roles("PrincipalInvestigator")
def post_resubmit(audit_id):
    body = get_json_body()
    a = resubmit_audit(audit_id, g.user_id, body)
    return success(serialize_audit(a), 200)


@bp.route("/closing-audits/<audit_id>/close", methods=["POST"])
@require_roles("AuditOfficer")
def post_close(audit_id):
    a = close_audit(audit_id)
    return success(serialize_audit(a), 200)
