"""Dispute routes."""

from flask import Blueprint, request

from middleware import require_role
from response import success_response
from services import dispute as svc

bp = Blueprint("disputes", __name__)


@bp.route("/disputes", methods=["POST"])
def open_d():
    require_role("RightsHolder")
    body = request.get_json(silent=True) or {}
    data = svc.open_dispute(body)
    return success_response(data, status_code=201)


@bp.route("/disputes/<dispute_id>/submit-evidence", methods=["POST"])
def submit_evidence(dispute_id):
    require_role("RightsHolder", "DisputeOfficer")
    body = request.get_json(silent=True) or {}
    data = svc.submit_evidence(dispute_id, body)
    return success_response(data)


@bp.route("/disputes/<dispute_id>/start-investigation", methods=["POST"])
def start_investigation(dispute_id):
    require_role("DisputeOfficer")
    body = request.get_json(silent=True) or {}
    data = svc.start_investigation(dispute_id, body)
    return success_response(data)


@bp.route("/disputes/<dispute_id>/advance-to-mediation", methods=["POST"])
def advance_to_mediation(dispute_id):
    require_role("DisputeOfficer")
    body = request.get_json(silent=True) or {}
    data = svc.advance_to_mediation(dispute_id, body)
    return success_response(data)


@bp.route("/disputes/<dispute_id>/reopen-investigation", methods=["POST"])
def reopen_investigation(dispute_id):
    require_role("DisputeOfficer")
    body = request.get_json(silent=True) or {}
    data = svc.reopen_investigation(dispute_id, body)
    return success_response(data)


@bp.route("/disputes/<dispute_id>/advance-to-arbitration", methods=["POST"])
def advance_to_arbitration(dispute_id):
    require_role("DisputeOfficer")
    body = request.get_json(silent=True) or {}
    data = svc.advance_to_arbitration(dispute_id, body)
    return success_response(data)


@bp.route("/disputes/<dispute_id>/resolve", methods=["POST"])
def resolve(dispute_id):
    require_role("DisputeOfficer")
    body = request.get_json(silent=True) or {}
    data = svc.resolve_dispute(dispute_id, body)
    return success_response(data)


@bp.route("/disputes/<dispute_id>/withdraw", methods=["POST"])
def withdraw(dispute_id):
    require_role("RightsHolder")
    body = request.get_json(silent=True) or {}
    data = svc.withdraw_dispute(dispute_id, body)
    return success_response(data)
