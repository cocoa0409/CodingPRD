"""Permit dossiers: drafting, the bounded submission loop and authority decisions."""

from flask import Blueprint

import db
import middleware as M
import response
import serializers as S
import validators as V
from errors import ApiError
from services import calc, engine

bp = Blueprint("permits", __name__)

PERMIT_TYPES = ("IMPORT", "TRANSPORT", "POSSESSION")
DECISIONS = ("ISSUE", "DENY", "REQUEST_INFO", "REVOKE")

PERMIT_COMPUTED = (
    "status", "submission_round", "missing_document_codes", "valid_from", "valid_until",
    "issued_at", "decision_reason",
)
DECISION_COMPUTED = (
    "status", "submission_round", "missing_document_codes", "issued_at", "decision_reason",
)

LEGAL_DECISIONS = {
    "DRAFT": ("REVOKE",),
    "SUBMITTED": ("ISSUE", "DENY", "REQUEST_INFO", "REVOKE"),
    "INFO_REQUESTED": ("DENY", "REVOKE"),
    "ISSUED": ("REVOKE",),
}


def _protection_status(permit):
    acq = db.db.acquisition_requests.get(permit["acquisition_request_id"])
    species = engine.species_of_acquisition(acq) if acq is not None else None
    return species["protection_status"] if species is not None else "UNLISTED"


def _acquisition_precondition_ok(permit):
    acq = db.db.acquisition_requests.get(permit["acquisition_request_id"])
    if acq is None:
        return False
    if permit["permit_type"] == "TRANSPORT":
        return acq["status"] in ("PENDING_PERMIT", "CLEARED", "FULFILLED")
    return acq["status"] == "PENDING_PERMIT"


@bp.route("/aquarium/permits", methods=["POST"])
def create_permit():
    M.authenticate({M.PERMIT_OFFICER})
    body = M.json_body()
    acq = M.fetch_body_fk(body, "acquisition_request_id", "acquisition_requests")

    V.reject_computed(body, PERMIT_COMPUTED)
    V.as_id(body, "acquisition_request_id", required=True)
    permit_type = V.as_enum(body, "permit_type", PERMIT_TYPES, required=True)
    authority_reference = V.as_str(body, "authority_reference", required=True)
    document_codes = V.as_code_list(body, "document_codes", calc.DOCUMENT_CODES, required=True)

    species = engine.species_of_acquisition(acq)
    protection_status = species["protection_status"] if species is not None else "UNLISTED"

    row = db.new_row()
    row.update({
        "acquisition_request_id": acq["id"],
        "permit_type": permit_type,
        "authority_reference": authority_reference,
        "document_codes": document_codes,
        "status": "DRAFT",
        "submission_round": 0,
        "missing_document_codes": calc.missing_documents(
            permit_type, protection_status, document_codes),
        "valid_from": None,
        "valid_until": None,
        "issued_at": None,
        "decision_reason": None,
    })
    db.insert("permits", row)
    return response.object_response(S.permit(row), 201)


@bp.route("/aquarium/permits/<row_id>", methods=["GET"])
def get_permit(row_id):
    M.authenticate(M.NON_LIAISON)
    row = M.fetch("permits", row_id)
    return response.object_response(S.permit(row))


@bp.route("/aquarium/permits/<row_id>/submission", methods=["POST"])
def submit_permit(row_id):
    M.authenticate({M.PERMIT_OFFICER})
    permit = M.fetch("permits", row_id)
    body = M.json_body()
    V.reject_computed(body, PERMIT_COMPUTED)
    document_codes = V.as_code_list(body, "document_codes", calc.DOCUMENT_CODES)

    if permit["status"] not in ("DRAFT", "INFO_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE")
    if not _acquisition_precondition_ok(permit):
        raise ApiError("ERR_INVALID_STATE")

    supplied = document_codes if document_codes is not None else permit["document_codes"]
    missing = calc.missing_documents(
        permit["permit_type"], _protection_status(permit), supplied)
    if missing:
        # Persist the attempted dossier and the recomputed gap; no version bump because
        # the transition did not happen.
        permit["document_codes"] = list(supplied)
        permit["missing_document_codes"] = missing
        raise ApiError("ERR_MISSING_DOCUMENTS")
    if int(permit["submission_round"]) + 1 > engine.PERMIT_MAX_ROUNDS:
        raise ApiError("ERR_ROUND_LIMIT_EXCEEDED")

    permit["document_codes"] = list(supplied)
    permit["missing_document_codes"] = []
    permit["decision_reason"] = None
    permit["submission_round"] = int(permit["submission_round"]) + 1
    permit["status"] = "SUBMITTED"
    db.touch(permit)
    return response.object_response(S.permit(permit))


@bp.route("/aquarium/permits/<row_id>/decisions", methods=["POST"])
def decide_permit(row_id):
    M.authenticate({M.DIRECTOR})
    permit = M.fetch("permits", row_id)
    body = M.json_body()
    V.reject_computed(body, DECISION_COMPUTED)
    decision = V.as_enum(body, "decision", DECISIONS, required=True)
    reason = V.as_str(body, "reason")
    valid_from = V.as_dt(body, "valid_from")
    valid_until = V.as_dt(body, "valid_until")

    if permit["status"] in ("DENIED", "REVOKED", "EXPIRED"):
        raise ApiError("ERR_ENTITY_TERMINAL")
    if decision not in LEGAL_DECISIONS.get(permit["status"], ()):
        raise ApiError("ERR_INVALID_ACTION")

    if decision == "ISSUE":
        if not _acquisition_precondition_ok(permit):
            raise ApiError("ERR_INVALID_STATE")
        if valid_from is None or valid_until is None:
            V.bad("Fields 'valid_from' and 'valid_until' are required for an ISSUE decision")
        if valid_until <= valid_from:
            raise ApiError("ERR_INTERVAL_INVALID")
        if (valid_until - valid_from).total_seconds() > engine.PERMIT_MAX_VALIDITY_DAYS * 86400:
            raise ApiError("ERR_PERMIT_VALIDITY_TOO_LONG")
        permit["status"] = "ISSUED"
        permit["valid_from"] = valid_from
        permit["valid_until"] = valid_until
        permit["issued_at"] = db.db.clock
        permit["decision_reason"] = None
        db.touch(permit)
    elif decision == "REQUEST_INFO":
        permit["status"] = "INFO_REQUESTED"
        permit["decision_reason"] = reason
        db.touch(permit)
    elif decision == "DENY":
        permit["status"] = "DENIED"
        permit["decision_reason"] = reason
        db.touch(permit)
    else:
        engine.revoke_permit(permit, reason)

    return response.object_response(S.permit(permit))
