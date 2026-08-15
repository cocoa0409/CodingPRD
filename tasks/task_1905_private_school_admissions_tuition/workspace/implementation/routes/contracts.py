"""Enrollment contract routes."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles, get_json_body, check_fields
from response import success, success_list
from services import serializers as ser
from services.helpers import (get_or_404, parent_scope_check, contract_family_id,
                              sort_created)
from services.lifecycle import enroll_contract, touch

bp = Blueprint("contracts", __name__)

READ_ROLES = ("AdmissionDirector", "AdmissionOfficer", "FinancialAidOfficer", "Parent")


@bp.get("/admissions/contracts")
@require_roles(*READ_ROLES)
def list_contracts(_uid, _role):
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    student_id = request.args.get("created_student_id")
    items = []
    for c in db.contracts.values():
        if application_id is not None and c["application_id"] != application_id:
            continue
        if status is not None and c["status"] != status:
            continue
        if student_id is not None and c["created_student_id"] != student_id:
            continue
        if _role == "Parent" and contract_family_id(c) != _uid:
            continue
        items.append(c)
    return success_list([ser.contract_view(c) for c in sort_created(items)])


@bp.get("/admissions/contracts/<contractId>")
@require_roles(*READ_ROLES)
def get_contract(contractId, _uid, _role):
    contract = get_or_404(db.contracts, contractId, "EnrollmentContract")
    parent_scope_check(_uid, _role, contract_family_id(contract))
    return success(ser.contract_view(contract))


@bp.post("/admissions/contracts/<contractId>/sign")
@require_roles("Parent")
def sign_contract(contractId, _uid, _role):
    contract = get_or_404(db.contracts, contractId, "EnrollmentContract")
    parent_scope_check(_uid, _role, contract_family_id(contract))
    if contract["status"] != "ISSUED":
        raise errors.err(errors.ERR_CONTRACT_NOT_ISSUED,
                         "Sign requires the contract to be ISSUED")
    contract["status"] = "SIGNED"
    touch(contract)
    return success(ser.contract_view(contract))


@bp.post("/admissions/contracts/<contractId>/deposit-payments")
@require_roles("Parent")
def deposit_payment(contractId, _uid, _role):
    body = get_json_body()
    vals = check_fields(body, {"amount_cents": "int_pos"}, {})
    contract = get_or_404(db.contracts, contractId, "EnrollmentContract")
    parent_scope_check(_uid, _role, contract_family_id(contract))
    if contract["status"] != "SIGNED":
        raise errors.err(errors.ERR_CONTRACT_NOT_SIGNED,
                         "Deposit payments require the contract to be SIGNED")
    remaining = contract["deposit_amount_cents"] - contract["paid_cents"]
    if vals["amount_cents"] > remaining:
        raise errors.err(errors.ERR_PAYMENT_EXCEEDS_BALANCE,
                         "Payment exceeds the remaining deposit balance")
    contract["paid_cents"] += vals["amount_cents"]
    touch(contract)
    if contract["paid_cents"] >= contract["deposit_amount_cents"]:
        enroll_contract(contract)
    return success(ser.contract_view(contract))
