"""Examination routes."""

from flask import Blueprint, request, g
import middleware
import response
from services import presentation as svc

bp = Blueprint("examinations", __name__)


@bp.route("/examinations/<examination_id>/primary-review", methods=["POST"])
def primary_review(examination_id):
    middleware.require_auth()
    middleware.require_role("Operator")
    return response.success(svc.primary_review(examination_id, request.get_json(silent=True) or {}, g.user_id))


@bp.route("/examinations/<examination_id>/cross-check", methods=["POST"])
def cross_check(examination_id):
    middleware.require_auth()
    middleware.require_role("Operator")
    return response.success(svc.cross_check(examination_id, request.get_json(silent=True) or {}, g.user_id))


@bp.route("/examinations/<examination_id>/reset", methods=["POST"])
def reset(examination_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank")
    return response.success(svc.reset_examination(examination_id, request.get_json(silent=True) or {}, g.user_id))


@bp.route("/examinations/<examination_id>/finalize", methods=["POST"])
def finalize(examination_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank")
    return response.success(svc.finalize_examination(examination_id, request.get_json(silent=True) or {}, g.user_id))


@bp.route("/examinations/<examination_id>", methods=["GET"])
def get(examination_id):
    middleware.require_auth()
    middleware.require_role(
        "Applicant", "IssuingBank", "ConfirmingBank", "NegotiatingBank",
        "Operator", "Auditor",
    )
    return response.success(svc.get_examination(examination_id))


@bp.route("/examinations/<examination_id>/discrepancies", methods=["GET"])
def list_discrepancies(examination_id):
    middleware.require_auth()
    middleware.require_role("Applicant", "IssuingBank", "Operator", "Auditor")
    limit, offset = response.parse_pagination(request.args)
    items, total = svc.list_discrepancies(examination_id, limit, offset)
    return response.success_list(items, total, limit, offset)
