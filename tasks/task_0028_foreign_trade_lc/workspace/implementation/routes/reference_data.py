"""Banks / Applicants / Beneficiaries routes."""

from flask import Blueprint, request, g
import middleware
import response
import db
from errors import raise_error, ERR_NOT_FOUND
from services import reference_data as svc

bp = Blueprint("reference_data", __name__)


@bp.route("/banks", methods=["POST"])
def create_bank():
    middleware.require_auth()
    middleware.require_role("Operator")
    return response.success(svc.create_bank(request.get_json(silent=True) or {}), 201)


@bp.route("/banks/<bank_id>", methods=["GET"])
def get_bank(bank_id):
    middleware.require_auth()
    middleware.require_role(
        "Operator", "Auditor",
        "IssuingBank", "AdvisingBank", "ConfirmingBank", "NegotiatingBank",
        "Applicant", "Beneficiary",
    )
    bank = db.get_by_id("banks", bank_id)
    if bank is None:
        raise_error(ERR_NOT_FOUND, "bank not found")
    return response.success(bank)


@bp.route("/applicants", methods=["POST"])
def create_applicant():
    middleware.require_auth()
    middleware.require_role("Operator")
    return response.success(svc.create_applicant(request.get_json(silent=True) or {}), 201)


@bp.route("/beneficiaries", methods=["POST"])
def create_beneficiary():
    middleware.require_auth()
    middleware.require_role("Operator")
    return response.success(svc.create_beneficiary(request.get_json(silent=True) or {}), 201)
