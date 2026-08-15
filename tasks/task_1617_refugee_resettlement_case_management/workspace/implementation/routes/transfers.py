"""CaseTransfer endpoints: initiate, respond (accept/reject), withdraw."""

from flask import Blueprint

from db import store, new_id, stamp_new, touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_TRANSFER_ALREADY_OPEN,
)
from helpers import body_dict, req_string, opt_string, req_enum
from middleware import authenticate, authorize, CASE_MANAGER, AGENCY_DIRECTOR
from response import success_object, success_list
from serializers import ser_transfer
from services import transfers_of_case, sorted_records, transfer_out_cascade
from routes.cases import get_case_or_404

bp = Blueprint("transfers", __name__)

REASONS = {"SECONDARY_MIGRATION", "FAMILY_REUNIFICATION", "EMPLOYMENT_OPPORTUNITY"}
DECISIONS = {"ACCEPTED", "REJECTED"}


def get_transfer_or_404(transfer_id):
    t = store.case_transfers.get(transfer_id)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Case transfer not found.")
    return t


@bp.post("/case-transfers")
def create_transfer():
    uid, role = authenticate()
    authorize(role, {CASE_MANAGER})
    d = body_dict()
    # Priority 3: body FK existence
    case_id = req_string(d, "case_id")
    case = store.cases.get(case_id)
    if case is None:
        raise ApiError(ERR_NOT_FOUND, 404, "case_id does not identify an existing case.")
    # Priority 4: schema
    receiving = req_string(d, "receiving_affiliate_code")
    reason = req_enum(d, "reason", REASONS)
    # Priority 6: state — only ARRIVED cases can be transferred
    if case["status"] != "ARRIVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ARRIVED case can be transferred.")
    # Priority 9: at most one INITIATED transfer per case
    if case["open_transfer_id"] is not None:
        raise ApiError(ERR_TRANSFER_ALREADY_OPEN, 409, "Case already has an open transfer.")
    transfer = {
        "id": new_id(),
        "case_id": case["id"],
        "receiving_affiliate_code": receiving,
        "reason": reason,
        "status": "INITIATED",
        "initiated_by_user_id": uid,
        "responded_by_user_id": None,
        "decision_note": None,
    }
    stamp_new(transfer)
    store.case_transfers[transfer["id"]] = transfer
    # Initiating a transfer freezes the case and bumps its version.
    case["open_transfer_id"] = transfer["id"]
    touch(case)
    return success_object(ser_transfer(transfer), 201)


@bp.get("/cases/<case_id>/case-transfers")
def list_transfers_of_case(case_id):
    authenticate()
    case = get_case_or_404(case_id)
    return success_list(sorted_records(transfers_of_case(case["id"])), ser_transfer)


@bp.post("/case-transfers/<transfer_id>/respond")
def respond_transfer(transfer_id):
    uid, role = authenticate()
    authorize(role, {AGENCY_DIRECTOR})
    transfer = get_transfer_or_404(transfer_id)
    d = body_dict()
    # Priority 4: schema
    decision = req_enum(d, "decision", DECISIONS)
    decision_note = opt_string(d, "decision_note")
    # Priority 6: state — respond only from INITIATED
    if transfer["status"] != "INITIATED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an INITIATED transfer can be responded to.")
    case = store.cases[transfer["case_id"]]
    transfer["responded_by_user_id"] = uid
    transfer["decision_note"] = decision_note
    if decision == "REJECTED":
        # Reject branch: unfreeze, no service cascade.
        transfer["status"] = "REJECTED"
        touch(transfer)
        case["open_transfer_id"] = None
        touch(case)
    else:
        # Accept branch: transfer completes and the case runs the full
        # transfer-out cascade in the same request.
        transfer["status"] = "COMPLETED"
        touch(transfer)
        transfer_out_cascade(case)
    return success_object(ser_transfer(transfer), 200)


@bp.post("/case-transfers/<transfer_id>/withdraw")
def withdraw_transfer(transfer_id):
    _uid, role = authenticate()
    authorize(role, {CASE_MANAGER})
    transfer = get_transfer_or_404(transfer_id)
    if transfer["status"] != "INITIATED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an INITIATED transfer can be withdrawn.")
    transfer["status"] = "WITHDRAWN"
    touch(transfer)
    case = store.cases[transfer["case_id"]]
    case["open_transfer_id"] = None
    touch(case)
    return success_object(ser_transfer(transfer), 200)
