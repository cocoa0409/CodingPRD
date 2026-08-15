"""InstructorContract endpoints (PRD 3.3)."""
from flask import Blueprint, request

import store
from auth import ALL_ROLES, authenticate, authorize
from errors import raise_err
from util import (
    body_json,
    bump,
    check_int_range,
    get_or_404,
    list_response,
    new_record,
    req_enum,
    req_int,
    req_str,
    serialize,
    success_object,
)

bp = Blueprint("contracts", __name__)

FIELDS = [
    "id",
    "session_id",
    "instructor_id",
    "revenue_share_bp",
    "guarantee_min_cents",
    "cancellation_guarantee_cents",
    "settlement_basis",
    "settlement_headcount",
    "settlement_amount_cents",
    "payout_cents",
    "status",
    "created_at",
    "updated_at",
    "version",
]

SETTLEMENT_BASES = ["ENROLLMENT_BASIS", "ATTENDANCE_BASIS"]


def contract_out(rec):
    return serialize(rec, FIELDS)


@bp.route("/instructor-contracts", methods=["POST"])
def create_contract():
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    body = body_json()
    session_id = req_str(body, "session_id")
    instructor_id = req_str(body, "instructor_id")
    revenue_share_bp = req_int(body, "revenue_share_bp")
    guarantee_min_cents = req_int(body, "guarantee_min_cents")
    cancellation_guarantee_cents = req_int(body, "cancellation_guarantee_cents")
    settlement_basis = req_enum(body, "settlement_basis", SETTLEMENT_BASES)
    check_int_range(revenue_share_bp, 0, 10000, "revenue_share_bp")
    check_int_range(guarantee_min_cents, 0, None, "guarantee_min_cents")
    check_int_range(cancellation_guarantee_cents, 0, None, "cancellation_guarantee_cents")
    session = get_or_404(store.sessions, session_id, "ClassSession")
    get_or_404(store.instructors, instructor_id, "Instructor")
    # The duplicate guard is evaluated before the instructor-mismatch guard (PRD 3.3).
    for c in store.contracts.values():
        if c["session_id"] == session_id and c["status"] in ("OFFERED", "ACCEPTED"):
            raise_err("ERR_DUPLICATE_CONTRACT", "A non-terminal contract already exists for this session")
    if instructor_id != session["instructor_id"]:
        raise_err("ERR_CONTRACT_INSTRUCTOR_MISMATCH", "Contract instructor_id must equal the session's instructor_id")
    rec = new_record()
    rec.update(
        session_id=session_id,
        instructor_id=instructor_id,
        revenue_share_bp=revenue_share_bp,
        guarantee_min_cents=guarantee_min_cents,
        cancellation_guarantee_cents=cancellation_guarantee_cents,
        settlement_basis=settlement_basis,
        settlement_headcount=None,
        settlement_amount_cents=None,
        payout_cents=None,
        status="OFFERED",
    )
    store.contracts[rec["id"]] = rec
    return success_object(contract_out(rec), 201)


@bp.route("/instructor-contracts", methods=["GET"])
def list_contracts():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    session_id = request.args.get("session_id")
    instructor_id = request.args.get("instructor_id")
    records = list(store.contracts.values())
    if session_id is not None:
        records = [r for r in records if r["session_id"] == session_id]
    if instructor_id is not None:
        records = [r for r in records if r["instructor_id"] == instructor_id]
    return list_response(records, contract_out)


@bp.route("/instructor-contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.contracts, contract_id, "InstructorContract")
    return success_object(contract_out(rec), 200)


@bp.route("/instructor-contracts/<contract_id>/accept", methods=["POST"])
def accept_contract(contract_id):
    uid, role = authenticate()
    authorize(role, ["Instructor"])
    rec = get_or_404(store.contracts, contract_id, "InstructorContract")
    # Entity-backed identity: only the named instructor may accept (PRD 2.1).
    if rec["instructor_id"] != uid:
        raise_err("ERR_UNAUTHORIZED_ROLE", "Only the contract's named instructor may accept it")
    if rec["status"] != "OFFERED":
        raise_err("ERR_INVALID_STATE", "Only an OFFERED contract can be accepted")
    session = store.sessions.get(rec["session_id"])
    if session is None or session["status"] not in ("DRAFT", "PUBLISHED"):
        raise_err("ERR_INVALID_STATE", "The session must be DRAFT or PUBLISHED to accept")
    rec["status"] = "ACCEPTED"
    bump(rec)
    return success_object(contract_out(rec), 200)


@bp.route("/instructor-contracts/<contract_id>/decline", methods=["POST"])
def decline_contract(contract_id):
    uid, role = authenticate()
    authorize(role, ["Instructor"])
    rec = get_or_404(store.contracts, contract_id, "InstructorContract")
    if rec["instructor_id"] != uid:
        raise_err("ERR_UNAUTHORIZED_ROLE", "Only the contract's named instructor may decline it")
    if rec["status"] != "OFFERED":
        raise_err("ERR_INVALID_STATE", "Only an OFFERED contract can be declined")
    rec["status"] = "DECLINED"
    rec["payout_cents"] = 0
    bump(rec)
    return success_object(contract_out(rec), 200)
