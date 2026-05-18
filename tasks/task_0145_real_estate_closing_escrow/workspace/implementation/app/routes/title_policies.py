"""TitleInsurancePolicy endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, jsonify

from app import store
from app.audit import append_audit
from app.auth import require_role
from app.calculations import title_insurance_premium
from app.envelope import success_envelope
from app.errors import ApiError
from app.idempotency import lookup as idem_lookup, remember as idem_remember, require_idempotency_key
from app.request_helpers import check_version, get_json_body
from app.serializers import serialize_title_policy
from app.util import (
    new_uuid,
    now_ts,
    optional_bool,
    require_enum,
    require_number,
    require_str,
    round_half_up_money,
)

bp = Blueprint("title_policies", __name__)

POLICY_KINDS = {"OWNERS", "LENDERS"}
BIND_ALLOWED_FILE_STATES = {"OPEN", "CONTINGENT_TITLE", "CONTINGENT_CD", "CONTINGENT_WIRE", "READY_TO_CLOSE"}
VOID_BOUND_FILE_STATES = {"OPEN", "CONTINGENT_TITLE", "CONTINGENT_CD"}


@bp.post("/title-policies")
def quote_policy():
    user_id, _role = require_role(["TitleOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    file_id = require_str(body, "escrow_file_id")
    if file_id not in store.escrow_files:
        raise ApiError("ERR_NOT_FOUND", "Escrow file not found.")
    policy_kind = require_enum(body, "policy_kind", POLICY_KINDS)
    insured_amount = round_half_up_money(require_number(body, "insured_amount"))
    simultaneous = optional_bool(body, "simultaneous_issue", False)
    if insured_amount <= 0:
        raise ApiError("ERR_BAD_REQUEST", "insured_amount must be positive.")

    # Determine whether a peer OWNERS policy is BOUND on this file at quote time.
    has_bound_owners = any(
        p["escrow_file_id"] == file_id and p["policy_kind"] == "OWNERS" and p["status"] == "BOUND"
        for p in store.title_policies.values()
    )

    premium = title_insurance_premium(
        policy_kind=policy_kind,
        insured_amount=insured_amount,
        simultaneous_issue=simultaneous,
        has_bound_owners_peer=has_bound_owners,
    )

    pid = new_uuid()
    ts = now_ts()
    pol = {
        "id": pid,
        "escrow_file_id": file_id,
        "policy_kind": policy_kind,
        "insured_amount": insured_amount,
        "simultaneous_issue": simultaneous,
        "premium": premium,
        "status": "QUOTED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.title_policies[pid] = pol
    append_audit(
        escrow_file_id=file_id,
        subject_kind="TITLE_POLICY",
        subject_id=pid,
        actor_user_id=user_id,
        actor_role="TitleOfficer",
        action="TITLE_POLICY_QUOTED",
        payload_body=body,
    )
    response = success_envelope(serialize_title_policy(pol))
    idem_remember(idem_key, body, 201, response)
    return jsonify(response), 201


@bp.get("/title-policies/<pid>")
def read_policy(pid: str):
    require_role(["EscrowOfficer", "TitleOfficer", "Buyer", "Seller"])
    p = store.title_policies.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "Title policy not found.")
    return jsonify(success_envelope(serialize_title_policy(p))), 200


@bp.post("/title-policies/<pid>/bind")
def bind_policy(pid: str):
    user_id, _role = require_role(["TitleOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    with store.mutation_lock:
        p = store.title_policies.get(pid)
        if p is None:
            raise ApiError("ERR_NOT_FOUND", "Title policy not found.")
        if p["status"] != "QUOTED":
            raise ApiError("ERR_INVALID_STATE", "Policy must be QUOTED to bind.")
        check_version(p, body)
        # Validation: cleared title search before bind
        cleared = any(
            s["escrow_file_id"] == p["escrow_file_id"] and s["status"] == "CLEARED"
            for s in store.title_searches.values()
        )
        if not cleared:
            raise ApiError("ERR_TITLE_NOT_CLEARED", "TitleSearch must be CLEARED before bind.")
        # Lenders requires bound owners.
        if p["policy_kind"] == "LENDERS":
            owners_bound = any(
                q["escrow_file_id"] == p["escrow_file_id"]
                and q["policy_kind"] == "OWNERS"
                and q["status"] == "BOUND"
                for q in store.title_policies.values()
            )
            if not owners_bound:
                raise ApiError(
                    "ERR_LENDERS_REQUIRES_OWNERS",
                    "An OWNERS policy must be BOUND before a LENDERS policy can bind.",
                )
        p["status"] = "BOUND"
        p["updated_at"] = now_ts()
        p["version"] = int(p.get("version", 1)) + 1
    append_audit(
        escrow_file_id=p["escrow_file_id"],
        subject_kind="TITLE_POLICY",
        subject_id=pid,
        actor_user_id=user_id,
        actor_role="TitleOfficer",
        action="TITLE_POLICY_BOUND",
        payload_body=body,
    )
    response = success_envelope(serialize_title_policy(p))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


@bp.post("/title-policies/<pid>/void")
def void_policy(pid: str):
    user_id, _role = require_role(["TitleOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        p = store.title_policies.get(pid)
        if p is None:
            raise ApiError("ERR_NOT_FOUND", "Title policy not found.")
        if p["status"] not in {"QUOTED", "BOUND"}:
            raise ApiError("ERR_INVALID_STATE", "Policy must be QUOTED or BOUND to void.")
        check_version(p, body)
        if p["status"] == "BOUND":
            file = store.escrow_files.get(p["escrow_file_id"])
            if not file or file["status"] not in VOID_BOUND_FILE_STATES:
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "A BOUND policy can only be voided while the escrow file is in OPEN/CONTINGENT_TITLE/CONTINGENT_CD.",
                )
        p["status"] = "VOIDED"
        p["updated_at"] = now_ts()
        p["version"] = int(p.get("version", 1)) + 1
    append_audit(
        escrow_file_id=p["escrow_file_id"],
        subject_kind="TITLE_POLICY",
        subject_id=pid,
        actor_user_id=user_id,
        actor_role="TitleOfficer",
        action="TITLE_POLICY_VOIDED",
        payload_body=body,
    )
    response = success_envelope(serialize_title_policy(p))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200
