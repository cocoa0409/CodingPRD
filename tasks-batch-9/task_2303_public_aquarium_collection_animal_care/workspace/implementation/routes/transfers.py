"""TransferRequest drafting, scoped reads, submission, decisions and completion."""

from flask import Blueprint

import db
import middleware as M
import response
import serializers as S
import validators as V
from errors import ApiError
from services import calc, engine

bp = Blueprint("transfers", __name__)

STATUSES = ("DRAFT", "SUBMITTED", "COUNTERED", "APPROVED", "DECLINED", "WITHDRAWN", "COMPLETED")
DECISIONS = ("APPROVE", "COUNTER", "DECLINE")
DECISION_ROLES = {
    "APPROVE": (M.DIRECTOR,),
    "COUNTER": (M.LIAISON,),
    "DECLINE": (M.LIAISON,),
}
LEGAL_DECISIONS = {
    "SUBMITTED": ("APPROVE", "COUNTER", "DECLINE"),
    "COUNTERED": ("DECLINE",),
    "APPROVED": ("DECLINE",),
}

TRANSFER_COMPUTED = (
    "counter_conditions", "status", "negotiation_round", "decided_by_user_id", "decided_at",
    "completed_at", "decline_reason",
)
DECISION_COMPUTED = tuple(f for f in TRANSFER_COMPUTED if f != "counter_conditions")


def _scope_check(transfer, user_id, role):
    if role == M.LIAISON and transfer["receiving_institution_id"] != user_id:
        raise ApiError("ERR_INSTITUTION_SCOPE_VIOLATION")


def _species_of(transfer):
    specimen = db.db.specimens.get(transfer["specimen_id"])
    if specimen is None:
        return None, None
    return specimen, db.db.species.get(specimen["species_id"])


@bp.route("/aquarium/transfer-requests", methods=["POST"])
def create_transfer():
    M.authenticate({M.PERMIT_OFFICER})
    body = M.json_body()
    specimen = M.fetch_body_fk(body, "specimen_id", "specimens")
    institution = M.fetch_body_fk(body, "receiving_institution_id", "institutions")
    permit = M.fetch_body_fk(body, "transport_permit_id", "permits")

    V.reject_computed(body, TRANSFER_COMPUTED)
    V.as_id(body, "specimen_id", required=True)
    V.as_id(body, "receiving_institution_id", required=True)
    proposed_transfer_at = V.as_dt(body, "proposed_transfer_at", required=True)
    welfare_conditions = V.as_code_list(
        body, "welfare_conditions", calc.WELFARE_CONDITION_CODES, required=True)
    V.as_id(body, "transport_permit_id")

    if permit is not None:
        if (permit["permit_type"] != "TRANSPORT"
                or permit["acquisition_request_id"] != specimen["acquisition_request_id"]
                or specimen["acquisition_request_id"] is None):
            raise ApiError("ERR_PERMIT_TYPE_MISMATCH")

    row = db.new_row()
    row.update({
        "specimen_id": specimen["id"],
        "receiving_institution_id": institution["id"],
        "transport_permit_id": permit["id"] if permit is not None else None,
        "proposed_transfer_at": proposed_transfer_at,
        "welfare_conditions": welfare_conditions,
        "counter_conditions": [],
        "status": "DRAFT",
        "negotiation_round": 0,
        "decided_by_user_id": None,
        "decided_at": None,
        "completed_at": None,
        "decline_reason": None,
    })
    db.insert("transfer_requests", row)
    return response.object_response(S.transfer_request(row), 201)


@bp.route("/aquarium/transfer-requests", methods=["GET"])
def list_transfers():
    user_id, role = M.authenticate(M.ANY_ROLE)
    specimen_id = M.str_param("specimen_id")
    institution_id = M.str_param("receiving_institution_id")
    permit_id = M.str_param("transport_permit_id")
    status = M.enum_param("status", STATUSES)
    limit, offset = M.pagination()

    if role == M.LIAISON and institution_id is not None and institution_id != user_id:
        raise ApiError("ERR_INSTITUTION_SCOPE_VIOLATION")

    def keep(row):
        if role == M.LIAISON and row["receiving_institution_id"] != user_id:
            return False
        if specimen_id is not None and row["specimen_id"] != specimen_id:
            return False
        if institution_id is not None and row["receiving_institution_id"] != institution_id:
            return False
        if permit_id is not None and row["transport_permit_id"] != permit_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    rows = db.ordered("transfer_requests", keep)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response([S.transfer_request(r) for r in page], limit, offset, total)


@bp.route("/aquarium/transfer-requests/<row_id>", methods=["GET"])
def get_transfer(row_id):
    user_id, role = M.authenticate(M.ANY_ROLE)
    transfer = M.fetch("transfer_requests", row_id)
    _scope_check(transfer, user_id, role)
    return response.object_response(S.transfer_request(transfer))


@bp.route("/aquarium/transfer-requests/<row_id>/submission", methods=["POST"])
def submit_transfer(row_id):
    M.authenticate({M.PERMIT_OFFICER})
    transfer = M.fetch("transfer_requests", row_id)
    body = M.json_body()
    V.reject_computed(body, TRANSFER_COMPUTED)
    welfare_conditions = V.as_code_list(
        body, "welfare_conditions", calc.WELFARE_CONDITION_CODES)

    if transfer["status"] not in ("DRAFT", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE")
    specimen, species = _species_of(transfer)
    if specimen is None:
        raise ApiError("ERR_SPECIMEN_NOT_FOUND")
    resubmission = transfer["status"] == "COUNTERED"
    if resubmission:
        if specimen["disposition_status"] != "TRANSFER_PENDING":
            raise ApiError("ERR_INVALID_STATE")
    elif specimen["disposition_status"] not in ("CLEARED", "ON_EXHIBIT"):
        raise ApiError("ERR_INVALID_STATE")
    if specimen["health_status"] != "HEALTHY":
        raise ApiError("ERR_SPECIMEN_NOT_HEALTHY")

    institution = db.db.institutions.get(transfer["receiving_institution_id"])
    if institution is None:
        raise ApiError("ERR_INSTITUTION_NOT_FOUND")
    if not institution["is_receiving_eligible"]:
        raise ApiError("ERR_RECEIVER_NOT_ELIGIBLE")

    supplied = (welfare_conditions if welfare_conditions is not None
                else transfer["welfare_conditions"])
    missing = calc.missing_conditions(
        institution, species, specimen, transfer["counter_conditions"], supplied)
    if missing:
        raise ApiError("ERR_TRANSFER_CONDITIONS_INCOMPLETE")

    transfer["welfare_conditions"] = list(supplied)
    transfer["status"] = "SUBMITTED"
    db.touch(transfer)

    if not resubmission:
        specimen["pre_transfer_disposition"] = specimen["disposition_status"]
        specimen["disposition_status"] = "TRANSFER_PENDING"
        db.touch(specimen)

    return response.object_response(S.transfer_request(transfer))


@bp.route("/aquarium/transfer-requests/<row_id>/decisions", methods=["POST"])
def decide_transfer(row_id):
    user_id, role = M.authenticate({M.DIRECTOR, M.LIAISON})
    transfer = M.fetch("transfer_requests", row_id)
    body = M.json_body()
    decision = V.as_enum(body, "decision", DECISIONS, required=True)
    M.require_action_role(role, decision, DECISION_ROLES)
    _scope_check(transfer, user_id, role)

    V.reject_computed(body, DECISION_COMPUTED)
    counter_conditions = V.as_code_list(
        body, "counter_conditions", calc.WELFARE_CONDITION_CODES)
    reason = V.as_str(body, "reason")
    if decision == "COUNTER" and not counter_conditions:
        V.bad("Field 'counter_conditions' is required for a COUNTER decision")

    if transfer["status"] in ("DECLINED", "WITHDRAWN", "COMPLETED"):
        raise ApiError("ERR_ENTITY_TERMINAL")
    if transfer["status"] == "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    if decision not in LEGAL_DECISIONS.get(transfer["status"], ()):
        raise ApiError("ERR_INVALID_ACTION")

    if decision == "APPROVE":
        specimen, species = _species_of(transfer)
        if species is not None and species["permit_required"]:
            permit = (db.db.permits.get(transfer["transport_permit_id"])
                      if transfer["transport_permit_id"] else None)
            if (permit is None or permit["permit_type"] != "TRANSPORT"
                    or permit["status"] != "ISSUED"):
                raise ApiError("ERR_PERMIT_NOT_ISSUED")
        institution = db.db.institutions.get(transfer["receiving_institution_id"])
        if institution is None or not institution["is_receiving_eligible"]:
            raise ApiError("ERR_RECEIVER_NOT_ELIGIBLE")
        transfer["status"] = "APPROVED"
        transfer["decided_by_user_id"] = user_id
        transfer["decided_at"] = db.db.clock
        db.touch(transfer)
    elif decision == "COUNTER":
        if int(transfer["negotiation_round"]) + 1 > engine.TRANSFER_MAX_COUNTERS:
            raise ApiError("ERR_ROUND_LIMIT_EXCEEDED")
        transfer["counter_conditions"] = list(counter_conditions)
        transfer["negotiation_round"] = int(transfer["negotiation_round"]) + 1
        transfer["status"] = "COUNTERED"
        transfer["decided_by_user_id"] = user_id
        transfer["decided_at"] = db.db.clock
        db.touch(transfer)
    else:
        transfer["decided_by_user_id"] = user_id
        transfer["decided_at"] = db.db.clock
        engine.decline_transfer(transfer, "LIAISON_DECLINED")

    return response.object_response(S.transfer_request(transfer))


@bp.route("/aquarium/transfer-requests/<row_id>/completion", methods=["POST"])
def complete_transfer(row_id):
    M.authenticate({M.PERMIT_OFFICER})
    transfer = M.fetch("transfer_requests", row_id)
    body = M.json_body()
    V.reject_computed(body, TRANSFER_COMPUTED)

    if transfer["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")
    specimen = db.db.specimens.get(transfer["specimen_id"])
    if specimen is None:
        raise ApiError("ERR_SPECIMEN_NOT_FOUND")
    if specimen["disposition_status"] != "TRANSFER_PENDING":
        raise ApiError("ERR_INVALID_STATE")
    if specimen["health_status"] != "HEALTHY":
        raise ApiError("ERR_SPECIMEN_NOT_HEALTHY")
    if db.db.clock < transfer["proposed_transfer_at"]:
        raise ApiError("ERR_TRANSFER_DATE_NOT_REACHED")

    former_exhibit_id = specimen["exhibit_id"]
    transfer["status"] = "COMPLETED"
    transfer["completed_at"] = db.db.clock
    db.touch(transfer)

    specimen["disposition_status"] = "TRANSFERRED"
    specimen["pre_transfer_disposition"] = None
    specimen["exhibit_id"] = None
    db.touch(specimen)

    if former_exhibit_id is not None:
        exhibit = db.db.exhibits.get(former_exhibit_id)
        if exhibit is not None:
            engine.recompute_exhibit(exhibit, force=True)

    return response.object_response(S.transfer_request(transfer))
