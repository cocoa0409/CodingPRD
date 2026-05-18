"""Disbursement endpoints — proposal, SoD-gated approval, send, settle, reverse."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, jsonify

from app import store
from app.audit import append_audit
from app.auth import require_role
from app.envelope import success_envelope
from app.errors import ApiError
from app.idempotency import lookup as idem_lookup, remember as idem_remember, require_idempotency_key
from app.request_helpers import check_version, get_json_body
from app.serializers import serialize_disbursement
from app.util import new_uuid, now_ts, require_number, require_str, round_half_up_money

bp = Blueprint("disbursements", __name__)

POOL_ACTIVE_STATES = {"APPROVED", "SENT", "SETTLED"}


def _escrow_pool(file_id: str) -> Decimal:
    f = store.escrow_files.get(file_id)
    if not f:
        return Decimal("0.00")
    held_total = sum(
        (Decimal(str(e["amount"])) for e in store.earnest_money.values()
         if e["escrow_file_id"] == file_id and e["status"] == "HELD"),
        Decimal("0.00"),
    )
    loan = Decimal(str(f.get("loan_amount", 0)))
    # Buyer cash-to-close from latest issued CD
    cds = [c for c in store.closing_disclosures.values() if c["escrow_file_id"] == file_id]
    issued = [c for c in cds if c.get("issued_at")]
    cash_to_close = Decimal("0.00")
    if issued:
        latest = max(issued, key=lambda c: c.get("version_number", 1))
        cash_to_close = Decimal(str(latest.get("cash_to_close", 0)))
    if cash_to_close < 0:
        # Negative cash-to-close means buyer is owed money, not contributing.
        cash_to_close = Decimal("0.00")
    return held_total + loan + cash_to_close


def _committed_total(file_id: str, exclude_disb_id: str | None = None) -> Decimal:
    total = Decimal("0.00")
    for d in store.disbursements.values():
        if d["escrow_file_id"] != file_id:
            continue
        if d["status"] not in POOL_ACTIVE_STATES:
            continue
        if exclude_disb_id is not None and d["id"] == exclude_disb_id:
            continue
        total += Decimal(str(d["amount"]))
    return total


@bp.post("/disbursements")
def propose_disbursement():
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    file_id = require_str(body, "escrow_file_id")
    if file_id not in store.escrow_files:
        raise ApiError("ERR_NOT_FOUND", "Escrow file not found.")
    wire_id = require_str(body, "wire_instruction_id")
    wire = store.wire_instructions.get(wire_id)
    if wire is None:
        raise ApiError("ERR_NOT_FOUND", "Wire instruction not found.")
    if wire["escrow_file_id"] != file_id:
        raise ApiError("ERR_NOT_FOUND", "Wire instruction does not belong to the given escrow file.")
    amount = round_half_up_money(require_number(body, "amount"))
    if amount <= 0:
        raise ApiError("ERR_BAD_REQUEST", "amount must be positive.")

    # At PROPOSED, do not yet check overdraw (per spec the check fires at propose
    # AND approve). We check on both.
    if _committed_total(file_id) + amount > _escrow_pool(file_id):
        raise ApiError(
            "ERR_DISBURSEMENT_OVERDRAW",
            "Proposed disbursement would exceed the escrow pool.",
        )

    did = new_uuid()
    ts = now_ts()
    disb = {
        "id": did,
        "escrow_file_id": file_id,
        "wire_instruction_id": wire_id,
        "amount": amount,
        "approved_by_user_id": None,
        "status": "PROPOSED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.disbursements[did] = disb
    append_audit(
        escrow_file_id=file_id,
        subject_kind="DISBURSEMENT",
        subject_id=did,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="DISBURSEMENT_PROPOSED",
        payload_body=body,
    )
    response = success_envelope(serialize_disbursement(disb))
    idem_remember(idem_key, body, 201, response)
    return jsonify(response), 201


@bp.get("/disbursements/<did>")
def read_disbursement(did: str):
    require_role(["EscrowOfficer", "DisbursementApprover"])
    d = store.disbursements.get(did)
    if d is None:
        raise ApiError("ERR_NOT_FOUND", "Disbursement not found.")
    return jsonify(success_envelope(serialize_disbursement(d))), 200


@bp.post("/disbursements/<did>/approve")
def approve_disbursement(did: str):
    user_id, _role = require_role(["DisbursementApprover"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        d = store.disbursements.get(did)
        if d is None:
            raise ApiError("ERR_NOT_FOUND", "Disbursement not found.")
        if d["status"] != "PROPOSED":
            raise ApiError("ERR_INVALID_STATE", "Disbursement must be PROPOSED to approve.")
        check_version(d, body)
        # Cross-entity precondition: wire CONFIRMED and file in READY_TO_CLOSE
        # (or CONTINGENT_WIRE if this approval will advance it).
        wire = store.wire_instructions.get(d["wire_instruction_id"])
        if not wire or wire["status"] != "CONFIRMED":
            raise ApiError("ERR_CROSS_ENTITY_STATE", "Wire must be CONFIRMED before approval.")
        f = store.escrow_files.get(d["escrow_file_id"])
        if not f or f["status"] not in {"READY_TO_CLOSE", "CONTINGENT_WIRE"}:
            raise ApiError(
                "ERR_CROSS_ENTITY_STATE",
                "Escrow file must be READY_TO_CLOSE (or CONTINGENT_WIRE) to approve.",
            )
        # SoD: actor must differ from the CD issuer on the same escrow file.
        cd_issuer = store.cd_issuer_by_escrow_file.get(d["escrow_file_id"])
        if cd_issuer and cd_issuer == user_id:
            raise ApiError(
                "ERR_SOD_VIOLATION",
                "Operator who issued the latest CD cannot approve a disbursement on the same file.",
            )
        # Overdraw at approval time
        if _committed_total(d["escrow_file_id"], exclude_disb_id=did) + Decimal(str(d["amount"])) > _escrow_pool(d["escrow_file_id"]):
            raise ApiError(
                "ERR_DISBURSEMENT_OVERDRAW",
                "Approval would exceed the escrow pool.",
            )
        d["status"] = "APPROVED"
        d["approved_by_user_id"] = user_id
        d["updated_at"] = now_ts()
        d["version"] = int(d.get("version", 1)) + 1
    append_audit(
        escrow_file_id=d["escrow_file_id"],
        subject_kind="DISBURSEMENT",
        subject_id=did,
        actor_user_id=user_id,
        actor_role="DisbursementApprover",
        action="DISBURSEMENT_APPROVED",
        payload_body=body,
    )
    response = success_envelope(serialize_disbursement(d))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


@bp.post("/disbursements/<did>/send")
def send_disbursement(did: str):
    user_id, _role = require_role(["DisbursementApprover"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        d = store.disbursements.get(did)
        if d is None:
            raise ApiError("ERR_NOT_FOUND", "Disbursement not found.")
        if d["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "Disbursement must be APPROVED to send.")
        check_version(d, body)
        d["status"] = "SENT"
        d["updated_at"] = now_ts()
        d["version"] = int(d.get("version", 1)) + 1
    append_audit(
        escrow_file_id=d["escrow_file_id"],
        subject_kind="DISBURSEMENT",
        subject_id=did,
        actor_user_id=user_id,
        actor_role="DisbursementApprover",
        action="DISBURSEMENT_SENT",
        payload_body=body,
    )
    response = success_envelope(serialize_disbursement(d))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


@bp.post("/disbursements/<did>/settle")
def settle_disbursement(did: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        d = store.disbursements.get(did)
        if d is None:
            raise ApiError("ERR_NOT_FOUND", "Disbursement not found.")
        if d["status"] != "SENT":
            raise ApiError("ERR_INVALID_STATE", "Disbursement must be SENT to settle.")
        check_version(d, body)
        d["status"] = "SETTLED"
        d["updated_at"] = now_ts()
        d["version"] = int(d.get("version", 1)) + 1
    append_audit(
        escrow_file_id=d["escrow_file_id"],
        subject_kind="DISBURSEMENT",
        subject_id=did,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="DISBURSEMENT_SETTLED",
        payload_body=body,
    )
    response = success_envelope(serialize_disbursement(d))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


@bp.post("/disbursements/<did>/reverse")
def reverse_disbursement(did: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        d = store.disbursements.get(did)
        if d is None:
            raise ApiError("ERR_NOT_FOUND", "Disbursement not found.")
        if d["status"] not in {"PROPOSED", "APPROVED", "SENT"}:
            raise ApiError("ERR_INVALID_STATE", "Disbursement must be PROPOSED/APPROVED/SENT to reverse.")
        check_version(d, body)
        d["status"] = "REVERSED"
        d["updated_at"] = now_ts()
        d["version"] = int(d.get("version", 1)) + 1
    append_audit(
        escrow_file_id=d["escrow_file_id"],
        subject_kind="DISBURSEMENT",
        subject_id=did,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="DISBURSEMENT_REVERSED",
        payload_body=body,
    )
    response = success_envelope(serialize_disbursement(d))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200
