"""WireInstruction endpoints — out-of-band callback and SoD enforcement."""
from __future__ import annotations

from flask import Blueprint, jsonify

from app import store
from app.audit import append_audit
from app.auth import require_role
from app.envelope import success_envelope
from app.errors import ApiError
from app.idempotency import lookup as idem_lookup, remember as idem_remember, require_idempotency_key
from app.request_helpers import check_version, get_json_body
from app.serializers import serialize_wire
from app.util import new_uuid, now_ts, optional_bool, require_enum, require_str

bp = Blueprint("wires", __name__)

BENEFICIARY_KINDS = {"SELLER", "LENDER_PAYOFF", "QUALIFIED_INTERMEDIARY", "TAX_AUTHORITY"}
CALLBACK_CHANNELS = {"VOICE_VERIFIED", "IN_PERSON_VERIFIED"}

BENEFICIARY_PARTY_MAP = {
    "SELLER": "SELLER",
    "LENDER_PAYOFF": "LENDER",
    "QUALIFIED_INTERMEDIARY": "QUALIFIED_INTERMEDIARY",
    "TAX_AUTHORITY": "TAX_AUTHORITY",
}


@bp.post("/wire-instructions")
def create_wire():
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
    beneficiary_kind = require_enum(body, "beneficiary_kind", BENEFICIARY_KINDS)
    beneficiary_party_id = require_str(body, "beneficiary_party_id")
    party = store.parties.get(beneficiary_party_id)
    if party is None:
        raise ApiError("ERR_NOT_FOUND", "Beneficiary party not found.")
    # PRD §3.6: beneficiary_kind / party_kind agreement is verified on
    # submission, not on creation. The DRAFT wire may be created with
    # any combination; the kind check fires only when submit moves the
    # row to PENDING_CONFIRMATION.

    routing = require_str(body, "routing_number")
    if not routing.isdigit() or len(routing) != 9:
        raise ApiError("ERR_BAD_REQUEST", "routing_number must be 9 digits.")
    last4 = require_str(body, "account_number_last4")
    if not last4.isdigit() or len(last4) != 4:
        raise ApiError("ERR_BAD_REQUEST", "account_number_last4 must be 4 digits.")

    wid = new_uuid()
    ts = now_ts()
    wire = {
        "id": wid,
        "escrow_file_id": file_id,
        "beneficiary_kind": beneficiary_kind,
        "beneficiary_party_id": beneficiary_party_id,
        "routing_number": routing,
        "account_number_last4": last4,
        "confirmation_callback_at": None,
        "confirmed_by_user_id": None,
        "callback_channel": None,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.wire_instructions[wid] = wire
    append_audit(
        escrow_file_id=file_id,
        subject_kind="WIRE",
        subject_id=wid,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="WIRE_CREATED",
        payload_body=body,
    )
    response = success_envelope(serialize_wire(wire))
    idem_remember(idem_key, body, 201, response)
    return jsonify(response), 201


@bp.get("/wire-instructions/<wid>")
def read_wire(wid: str):
    require_role(["EscrowOfficer", "DisbursementApprover"])
    w = store.wire_instructions.get(wid)
    if w is None:
        raise ApiError("ERR_NOT_FOUND", "Wire instruction not found.")
    return jsonify(success_envelope(serialize_wire(w))), 200


@bp.post("/wire-instructions/<wid>/submit")
def submit_wire(wid: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        w = store.wire_instructions.get(wid)
        if w is None:
            raise ApiError("ERR_NOT_FOUND", "Wire instruction not found.")
        # PRD §3.6: beneficiary kind/party kind agreement is verified
        # at submit time. Per §2.8 the kind-agreement check (priority 4)
        # runs before the state-from check (priority 5).
        beneficiary_kind = w["beneficiary_kind"]
        party = store.parties.get(w["beneficiary_party_id"])
        if party is None:
            raise ApiError("ERR_NOT_FOUND", "Beneficiary party not found.")
        expected_kind = BENEFICIARY_PARTY_MAP[beneficiary_kind]
        if beneficiary_kind == "TAX_AUTHORITY":
            if party["party_kind"] != "TAX_AUTHORITY":
                raise ApiError(
                    "ERR_BENEFICIARY_KIND_MISMATCH",
                    "Tax-authority wires must reference a TAX_AUTHORITY party.",
                )
        else:
            if party["party_kind"] != expected_kind:
                raise ApiError(
                    "ERR_BENEFICIARY_KIND_MISMATCH",
                    f"beneficiary_party_id has party_kind {party['party_kind']}, expected {expected_kind}.",
                )
        if w["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Wire must be DRAFT to submit.")
        check_version(w, body)
        w["status"] = "PENDING_CONFIRMATION"
        w["updated_at"] = now_ts()
        w["version"] = int(w.get("version", 1)) + 1
    append_audit(
        escrow_file_id=w["escrow_file_id"],
        subject_kind="WIRE",
        subject_id=wid,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="WIRE_SUBMITTED",
        payload_body=body,
    )
    response = success_envelope(serialize_wire(w))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


@bp.post("/wire-instructions/<wid>/confirm-callback")
def confirm_callback(wid: str):
    user_id, role = require_role(["EscrowOfficer", "DisbursementApprover"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        w = store.wire_instructions.get(wid)
        if w is None:
            raise ApiError("ERR_NOT_FOUND", "Wire instruction not found.")
        # SoD precedes state and callback checks (priority 7 vs 5/8 — but spec says
        # state (priority 5) precedes SoD (priority 7) precedes callback (priority 8).
        if w["status"] != "PENDING_CONFIRMATION":
            raise ApiError("ERR_INVALID_STATE", "Wire must be PENDING_CONFIRMATION to confirm.")
        # SoD: actor must differ from the operator who issued the latest CD on the same escrow file.
        cd_issuer = store.cd_issuer_by_escrow_file.get(w["escrow_file_id"])
        if cd_issuer and cd_issuer == user_id:
            raise ApiError(
                "ERR_SOD_VIOLATION",
                "Operator who issued the latest CD cannot confirm a wire on the same escrow file.",
            )
        # Callback channel check
        callback_completed = optional_bool(body, "callback_completed", False)
        callback_channel = body.get("callback_channel")
        if not callback_completed or callback_channel not in CALLBACK_CHANNELS:
            raise ApiError(
                "ERR_WIRE_CALLBACK_MISSING",
                "callback_completed must be true and callback_channel must be VOICE_VERIFIED or IN_PERSON_VERIFIED.",
            )
        check_version(w, body)
        w["status"] = "CONFIRMED"
        w["confirmation_callback_at"] = now_ts(store.clock.now())
        w["confirmed_by_user_id"] = user_id
        w["callback_channel"] = callback_channel
        w["updated_at"] = now_ts()
        w["version"] = int(w.get("version", 1)) + 1
    append_audit(
        escrow_file_id=w["escrow_file_id"],
        subject_kind="WIRE",
        subject_id=wid,
        actor_user_id=user_id,
        actor_role=role,
        action="WIRE_CONFIRMED",
        payload_body=body,
    )
    response = success_envelope(serialize_wire(w))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


@bp.post("/wire-instructions/<wid>/flag-fraud")
def flag_fraud(wid: str):
    user_id, role = require_role(["EscrowOfficer", "DisbursementApprover"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        w = store.wire_instructions.get(wid)
        if w is None:
            raise ApiError("ERR_NOT_FOUND", "Wire instruction not found.")
        if w["status"] != "PENDING_CONFIRMATION":
            raise ApiError("ERR_INVALID_STATE", "Wire must be PENDING_CONFIRMATION to flag fraud.")
        check_version(w, body)
        w["status"] = "REJECTED_FRAUD_FLAG"
        w["updated_at"] = now_ts()
        w["version"] = int(w.get("version", 1)) + 1
        # Cascade: any Disbursement on this wire in PROPOSED/APPROVED -> REVERSED
        for d in list(store.disbursements.values()):
            if d["wire_instruction_id"] == wid and d["status"] in {"PROPOSED", "APPROVED"}:
                d["status"] = "REVERSED"
                d["updated_at"] = now_ts()
                d["version"] = int(d.get("version", 1)) + 1
                append_audit(
                    escrow_file_id=d["escrow_file_id"],
                    subject_kind="DISBURSEMENT",
                    subject_id=d["id"],
                    actor_user_id=user_id,
                    actor_role=role,
                    action="DISBURSEMENT_REVERSED_CASCADE",
                    payload_body={},
                )
    append_audit(
        escrow_file_id=w["escrow_file_id"],
        subject_kind="WIRE",
        subject_id=wid,
        actor_user_id=user_id,
        actor_role=role,
        action="WIRE_FLAGGED_FRAUD",
        payload_body=body,
    )
    response = success_envelope(serialize_wire(w))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


@bp.post("/wire-instructions/<wid>/void")
def void_wire(wid: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        w = store.wire_instructions.get(wid)
        if w is None:
            raise ApiError("ERR_NOT_FOUND", "Wire instruction not found.")
        if w["status"] not in {"DRAFT", "CONFIRMED"}:
            raise ApiError("ERR_INVALID_STATE", "Wire must be DRAFT or CONFIRMED to void.")
        check_version(w, body)
        if w["status"] == "CONFIRMED":
            for d in store.disbursements.values():
                if d["wire_instruction_id"] == wid and d["status"] in {"SENT", "SETTLED"}:
                    raise ApiError(
                        "ERR_WIRE_LOCKED_BY_DISBURSEMENT",
                        "Cannot void a CONFIRMED wire with active disbursements.",
                    )
        w["status"] = "VOIDED"
        w["updated_at"] = now_ts()
        w["version"] = int(w.get("version", 1)) + 1
    append_audit(
        escrow_file_id=w["escrow_file_id"],
        subject_kind="WIRE",
        subject_id=wid,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="WIRE_VOIDED",
        payload_body=body,
    )
    response = success_envelope(serialize_wire(w))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200
