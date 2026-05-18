"""EarnestMoneyDeposit endpoints."""
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
from app.serializers import serialize_emd
from app.util import (
    new_uuid,
    now_ts,
    optional_number,
    require_enum,
    require_number,
    require_str,
    round_half_up_money,
)

bp = Blueprint("earnest_money", __name__)

RELEASE_REASONS = {"BUYER_DEFAULT", "SELLER_DEFAULT", "TITLE_DEFECT", "MUTUAL_RELEASE"}


def _floor(file: dict) -> Decimal:
    pp = Decimal(str(file["purchase_price"]))
    floor = (pp * Decimal("0.01")).quantize(Decimal("0.01"))
    return floor


@bp.post("/earnest-money")
def create_emd():
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    file_id = require_str(body, "escrow_file_id")
    amount = round_half_up_money(require_number(body, "amount"))
    f = store.escrow_files.get(file_id)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", "Escrow file not found.")
    if amount <= 0:
        raise ApiError("ERR_BAD_REQUEST", "amount must be positive.")
    if amount < _floor(f):
        raise ApiError(
            "ERR_EMD_BELOW_FLOOR",
            "EMD amount is below the 1% purchase-price floor.",
        )

    emd_id = new_uuid()
    ts = now_ts()
    emd = {
        "id": emd_id,
        "escrow_file_id": file_id,
        "amount": amount,
        "forfeited_amount": Decimal("0.00"),
        "refunded_amount": Decimal("0.00"),
        "split_buyer_share": Decimal("0.00"),
        "split_seller_share": Decimal("0.00"),
        "status": "PENDING_FUNDS",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.earnest_money[emd_id] = emd
    append_audit(
        escrow_file_id=file_id,
        subject_kind="EMD",
        subject_id=emd_id,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="EMD_CREATED",
        payload_body=body,
    )
    response = success_envelope(serialize_emd(emd))
    idem_remember(idem_key, body, 201, response)
    return jsonify(response), 201


@bp.get("/earnest-money/<emd_id>")
def read_emd(emd_id: str):
    user_id, role = require_role(["EscrowOfficer", "Buyer", "Seller"])
    emd = store.earnest_money.get(emd_id)
    if emd is None:
        raise ApiError("ERR_NOT_FOUND", "EMD not found.")
    f = store.escrow_files.get(emd["escrow_file_id"])
    if role == "Buyer" and (not f or f["buyer_party_id"] != user_id):
        raise ApiError("ERR_FORBIDDEN_ROLE", "Buyer cannot read this EMD.")
    if role == "Seller" and (not f or f["seller_party_id"] != user_id):
        raise ApiError("ERR_FORBIDDEN_ROLE", "Seller cannot read this EMD.")
    return jsonify(success_envelope(serialize_emd(emd))), 200


@bp.post("/earnest-money/<emd_id>/fund")
def fund_emd(emd_id: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    with store.mutation_lock:
        emd = store.earnest_money.get(emd_id)
        if emd is None:
            raise ApiError("ERR_NOT_FOUND", "EMD not found.")
        if emd["status"] != "PENDING_FUNDS":
            raise ApiError("ERR_INVALID_STATE", "EMD already advanced.")
        check_version(emd, body)
        f = store.escrow_files.get(emd["escrow_file_id"])
        if f is None:
            raise ApiError("ERR_NOT_FOUND", "Escrow file not found.")
        if Decimal(str(emd["amount"])) < _floor(f):
            raise ApiError("ERR_EMD_BELOW_FLOOR", "EMD below floor on funding.")
        emd["status"] = "HELD"
        emd["updated_at"] = now_ts()
        emd["version"] = int(emd.get("version", 1)) + 1
    append_audit(
        escrow_file_id=emd["escrow_file_id"],
        subject_kind="EMD",
        subject_id=emd_id,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="EMD_FUNDED",
        payload_body=body,
    )
    response = success_envelope(serialize_emd(emd))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


@bp.post("/earnest-money/<emd_id>/release")
def release_emd(emd_id: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    with store.mutation_lock:
        emd = store.earnest_money.get(emd_id)
        if emd is None:
            raise ApiError("ERR_NOT_FOUND", "EMD not found.")
        if emd["status"] != "HELD":
            raise ApiError("ERR_INVALID_STATE", "EMD must be HELD to release.")
        check_version(emd, body)
        reason = require_enum(body, "reason", RELEASE_REASONS)

        if reason == "MUTUAL_RELEASE":
            buyer_share = round_half_up_money(optional_number(body, "split_buyer_share", 0))
            seller_share = round_half_up_money(optional_number(body, "split_seller_share", 0))
            if buyer_share < 0 or seller_share < 0:
                raise ApiError("ERR_EMD_SPLIT_INVARIANT", "Shares must be non-negative.")
            if Decimal(str(buyer_share)) + Decimal(str(seller_share)) != Decimal(str(emd["amount"])):
                raise ApiError(
                    "ERR_EMD_SPLIT_INVARIANT",
                    "split_buyer_share + split_seller_share must equal EMD.amount exactly.",
                )
            emd["status"] = "SPLIT"
            emd["refunded_amount"] = buyer_share
            emd["forfeited_amount"] = seller_share
            emd["split_buyer_share"] = buyer_share
            emd["split_seller_share"] = seller_share
        elif reason == "BUYER_DEFAULT":
            emd["status"] = "RELEASED_TO_SELLER"
            emd["forfeited_amount"] = emd["amount"]
            emd["refunded_amount"] = Decimal("0.00")
        else:  # SELLER_DEFAULT or TITLE_DEFECT
            emd["status"] = "RELEASED_TO_BUYER"
            emd["refunded_amount"] = emd["amount"]
            emd["forfeited_amount"] = Decimal("0.00")

        emd["updated_at"] = now_ts()
        emd["version"] = int(emd.get("version", 1)) + 1
    append_audit(
        escrow_file_id=emd["escrow_file_id"],
        subject_kind="EMD",
        subject_id=emd_id,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action=f"EMD_RELEASED_{reason}",
        payload_body=body,
    )
    response = success_envelope(serialize_emd(emd))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200
