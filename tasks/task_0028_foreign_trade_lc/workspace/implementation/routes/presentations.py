"""Presentation, document, refusal flow."""

from flask import Blueprint, request, g
import middleware
import response
from services import presentation as svc

bp = Blueprint("presentations", __name__)


@bp.route("/letters-of-credit/<lc_id>/presentations", methods=["POST"])
def create_presentation(lc_id):
    middleware.require_auth()
    middleware.require_role("Beneficiary")
    return response.success(svc.create_presentation(lc_id, request.get_json(silent=True) or {}, g.user_id), 201)


@bp.route("/presentations/<presentation_id>", methods=["GET"])
def get_presentation(presentation_id):
    middleware.require_auth()
    middleware.require_role(
        "Applicant", "Beneficiary",
        "IssuingBank", "ConfirmingBank", "NegotiatingBank",
        "Operator", "Auditor",
    )
    return response.success(svc.get_presentation(presentation_id, g.role, g.user_id))


@bp.route("/letters-of-credit/<lc_id>/presentations", methods=["GET"])
def list_presentations(lc_id):
    middleware.require_auth()
    middleware.require_role(
        "Applicant", "Beneficiary",
        "IssuingBank", "ConfirmingBank", "NegotiatingBank",
        "Operator", "Auditor",
    )
    limit, offset = response.parse_pagination(request.args)
    filters = {}
    if request.args.get("status"):
        filters["status"] = request.args.get("status")
    items, total = svc.list_presentations_under_lc(lc_id, filters, limit, offset, g.role, g.user_id)
    return response.success_list(items, total, limit, offset)


@bp.route("/presentations/<presentation_id>/documents", methods=["POST"])
def attach_document(presentation_id):
    middleware.require_auth()
    middleware.require_role("Beneficiary")
    return response.success(svc.attach_document(presentation_id, request.get_json(silent=True) or {}, g.user_id), 201)


@bp.route("/presentations/<presentation_id>/start-examination", methods=["POST"])
def start_examination(presentation_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank")
    return response.success(svc.start_examination(presentation_id, request.get_json(silent=True) or {}, g.user_id), 201)


@bp.route("/presentations/<presentation_id>/applicant-decision", methods=["POST"])
def applicant_decision(presentation_id):
    middleware.require_auth()
    middleware.require_role("Applicant")
    return response.success(svc.applicant_decision(presentation_id, request.get_json(silent=True) or {}, g.user_id))


@bp.route("/presentations/<presentation_id>/refuse", methods=["POST"])
def refuse(presentation_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank")
    return response.success(svc.refuse_presentation(presentation_id, request.get_json(silent=True) or {}, g.user_id))


@bp.route("/presentations/<presentation_id>/applicant-override", methods=["POST"])
def applicant_override(presentation_id):
    middleware.require_auth()
    middleware.require_role("Applicant")
    return response.success(svc.applicant_override(presentation_id, request.get_json(silent=True) or {}, g.user_id))


@bp.route("/presentations/<presentation_id>/return-documents", methods=["POST"])
def return_documents(presentation_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank")
    return response.success(svc.return_documents(presentation_id, request.get_json(silent=True) or {}, g.user_id))
