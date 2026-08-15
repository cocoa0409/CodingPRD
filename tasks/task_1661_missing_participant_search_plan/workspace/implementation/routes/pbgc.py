"""PBGCTransfer endpoints (PRD section 3.4)."""

import db
import gates
import services
from errors import (
    ApiError,
    ERR_CASE_INVALID_STATE,
    ERR_PBGC_TRANSFER_ALREADY_OPEN,
    ERR_PBGC_TRANSFER_NOT_SUBMITTED,
    ERR_ZERO_BALANCE_TRANSFER,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import public_transfer
from util import (
    body_fk,
    body_json,
    check_no_fields,
    check_shape,
    paginate,
    pagination_params,
    path_entity,
)

bp = make_blueprint("pbgc")


@bp.post("/pbgc-transfers")
def create_transfer():
    user_id, _role = authenticate(["IndependentFiduciary"])
    body = body_json()
    check_shape(body, {
        "participant_id": {"type": "string", "required": True},
        "amount_basis": {
            "type": "enum",
            "values": {"SUBMISSION_NET", "EXHAUSTION_SNAPSHOT"},
            "required": True,
        },
    })
    participant = body_fk(body, "participant_id", "participants", "participant")
    _case, search_case = gates.case_and_missing_gates(participant)
    gates.distribution_gate(participant)
    gates.sod_and_doc_gates(search_case, user_id)
    # Priority 9: no second open transfer.
    if any(
        t["status"] == "SUBMITTED"
        for t in services.participant_transfers(participant["id"])
    ):
        raise ApiError(
            ERR_PBGC_TRANSFER_ALREADY_OPEN, 409,
            "a SUBMITTED PBGC transfer already exists for the participant",
        )
    # Priority 11: the search protocol must be exhausted.
    gates.require_exhausted(search_case)
    # Amount frozen per basis at creation.
    if body["amount_basis"] == "SUBMISSION_NET":
        amount = services.net_distributable(participant)
    else:
        amount = search_case["exhaustion_snapshot_cents"]
    # Priority 12: money rules.
    if amount == 0:
        raise ApiError(
            ERR_ZERO_BALANCE_TRANSFER, 422,
            "a zero transferable amount cannot be transferred",
        )
    transfer = db.new_entity("transfers", {
        "participant_id": participant["id"],
        "amount_basis": body["amount_basis"],
        "amount_cents": amount,
        "status": "SUBMITTED",
        "submitted_at": db.now(),
        "confirmed_at": None,
        "rejection_reason": None,
        "_excess_cents": 0,
    })
    return success_obj(public_transfer(transfer), 201)


@bp.get("/participants/<participant_id>/pbgc-transfers")
def list_participant_transfers(participant_id):
    authenticate(ALL_ROLES)
    participant = path_entity("participants", participant_id, "participant")
    limit, offset = pagination_params()
    items = services.participant_transfers(participant["id"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list(
        [public_transfer(t) for t in page], limit, offset, total, has_more
    )


@bp.post("/pbgc-transfers/<transfer_id>/confirm")
def confirm_transfer(transfer_id):
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_no_fields(body)
    transfer = path_entity("transfers", transfer_id, "pbgc transfer")
    if transfer["status"] != "SUBMITTED":
        raise ApiError(
            ERR_PBGC_TRANSFER_NOT_SUBMITTED, 409,
            "confirm requires a SUBMITTED transfer",
        )
    participant = db.get("participants", transfer["participant_id"])
    case = db.get("cases", participant["termination_case_id"])
    # Re-checked at confirm.
    if case["status"] not in gates.DISPOSITION_CASE_STATUSES:
        raise ApiError(
            ERR_CASE_INVALID_STATE, 409,
            "confirm requires case status DISTRIBUTION_IN_PROGRESS or "
            "FINAL_RECONCILIATION",
        )
    now = db.now()
    transfer["status"] = "ACCEPTED"
    transfer["confirmed_at"] = now
    # Sponsor make-whole: the frozen benefit above the participant's
    # post-expense net is funded by the sponsor.
    excess = max(
        0, transfer["amount_cents"] - services.net_distributable(participant)
    )
    transfer["_excess_cents"] = excess
    db.touch(transfer)
    participant["distribution_status"] = "PBGC_TRANSFERRED"
    db.touch(participant)
    return success_obj(public_transfer(transfer), 200)


@bp.post("/pbgc-transfers/<transfer_id>/record-rejection")
def record_rejection(transfer_id):
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_shape(body, {"reason": {"type": "string", "required": True}})
    transfer = path_entity("transfers", transfer_id, "pbgc transfer")
    if transfer["status"] != "SUBMITTED":
        raise ApiError(
            ERR_PBGC_TRANSFER_NOT_SUBMITTED, 409,
            "record-rejection requires a SUBMITTED transfer",
        )
    # The participant remains MISSING with distribution_status
    # PENDING_ELECTION; the plan must elect forfeiture or resubmit.
    transfer["status"] = "REJECTED"
    transfer["rejection_reason"] = body["reason"]
    db.touch(transfer)
    return success_obj(public_transfer(transfer), 200)
