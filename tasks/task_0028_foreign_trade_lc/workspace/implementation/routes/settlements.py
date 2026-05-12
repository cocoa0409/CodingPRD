"""Settlement routes."""

from flask import Blueprint, request, g
import middleware
import response
from services import settlement as svc

bp = Blueprint("settlements", __name__)


@bp.route("/presentations/<presentation_id>/settlements", methods=["POST"])
def create_settlement(presentation_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank", "NegotiatingBank")
    return response.success(svc.create_settlement(presentation_id, request.get_json(silent=True) or {}, g.role, g.user_id), 201)


@bp.route("/settlements/<settlement_id>", methods=["GET"])
def get(settlement_id):
    middleware.require_auth()
    middleware.require_role(
        "Applicant", "Beneficiary",
        "IssuingBank", "NegotiatingBank", "ConfirmingBank",
        "Operator", "Auditor",
    )
    return response.success(svc.get_settlement(settlement_id))


@bp.route("/settlements/<settlement_id>/execute-sight", methods=["POST"])
def execute_sight(settlement_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank")
    return response.success(svc.execute_sight(settlement_id, request.get_json(silent=True) or {}, g.user_id))


@bp.route("/settlements/<settlement_id>/record-acceptance", methods=["POST"])
def record_acceptance(settlement_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank")
    return response.success(svc.record_acceptance(settlement_id, request.get_json(silent=True) or {}, g.user_id))


@bp.route("/settlements/<settlement_id>/negotiation-advance", methods=["POST"])
def negotiation_advance(settlement_id):
    middleware.require_auth()
    middleware.require_role("NegotiatingBank")
    return response.success(svc.negotiation_advance(settlement_id, request.get_json(silent=True) or {}, g.user_id))


@bp.route("/settlements/<settlement_id>/compensate", methods=["POST"])
def compensate(settlement_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank")
    return response.success(svc.compensate(settlement_id, request.get_json(silent=True) or {}, g.user_id))
