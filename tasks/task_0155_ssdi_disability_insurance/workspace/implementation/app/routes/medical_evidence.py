"""MedicalEvidence routes."""

from __future__ import annotations

from flask import Blueprint

from app.envelope import success_response
from app.routes._helpers import assert_claimant_self_access, get_json_body, with_auth
from app.serializers import serialize_medical_evidence
from app.services import medical_evidence as service


bp = Blueprint("medical_evidence", __name__)


@bp.route("/claimants/<claimant_id>/medical-evidence", methods=["POST"])
@with_auth("Claimant")
def submit_evidence(caller, claimant_id: str):
    assert_claimant_self_access(caller, claimant_id)
    body = get_json_body()
    record = service.submit_evidence(claimant_id, body)
    return success_response(serialize_medical_evidence(record), status=201)


@bp.route("/claimants/<claimant_id>/medical-evidence/<evidence_id>/accept", methods=["POST"])
@with_auth("DDS_Examiner")
def accept_evidence(caller, claimant_id: str, evidence_id: str):
    record = service.accept_evidence(claimant_id, evidence_id)
    return success_response(serialize_medical_evidence(record))


@bp.route("/claimants/<claimant_id>/medical-evidence/<evidence_id>/reject", methods=["POST"])
@with_auth("DDS_Examiner")
def reject_evidence(caller, claimant_id: str, evidence_id: str):
    record = service.reject_evidence(claimant_id, evidence_id)
    return success_response(serialize_medical_evidence(record))
