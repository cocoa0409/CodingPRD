from flask import Blueprint, request

import db
import errors
import validate
import serialize
from response import ok_object, ok_array
from middleware import require
from services import lookup

bp = Blueprint("insurance_assignments", __name__)


@bp.get("/insurance-assignments/<assignment_id>")
@require("Admin", "TrustOfficer")
def get_insurance_assignment(assignment_id):
    a = lookup.insurance_assignment(assignment_id)
    return ok_object(serialize.insurance_assignment(a), 200)


@bp.get("/insurance-assignments")
@require("Admin", "TrustOfficer")
def list_insurance_assignments():
    limit, offset = validate.pagination()
    contract_id = request.args.get("contract_id")
    items = list(db.insurance_assignments.values())
    if contract_id is not None:
        items = [a for a in items if a["contract_id"] == contract_id]
    window, total = validate.paginate(items, limit, offset)
    return ok_array([serialize.insurance_assignment(a) for a in window], limit, offset, total)


@bp.post("/insurance-assignments/<assignment_id>/verify")
@require("TrustOfficer")
def verify_assignment(assignment_id):
    a = lookup.insurance_assignment(assignment_id)
    # state (priority 6) before referential funding-type mismatch (priority 9)
    if a["status"] != "PENDING":
        raise errors.invalid_state("Only a PENDING assignment can be verified")
    contract = db.contracts.get(a["contract_id"])
    if not contract or contract["funding_type"] != "INSURANCE_ASSIGNMENT":
        raise errors.conflict(errors.ERR_FUNDING_TYPE_MISMATCH,
                              "Contract funding type is not INSURANCE_ASSIGNMENT")
    a["status"] = "VERIFIED"
    db.touch(a)
    # funded_amount recompute -> bump contract version
    if contract:
        db.touch(contract)
    return ok_object(serialize.insurance_assignment(a), 200)


@bp.post("/insurance-assignments/<assignment_id>/decline")
@require("TrustOfficer")
def decline_assignment(assignment_id):
    a = lookup.insurance_assignment(assignment_id)
    if a["status"] != "PENDING":
        raise errors.invalid_state("Only a PENDING assignment can be declined")
    a["status"] = "DECLINED"
    db.touch(a)
    return ok_object(serialize.insurance_assignment(a), 200)
