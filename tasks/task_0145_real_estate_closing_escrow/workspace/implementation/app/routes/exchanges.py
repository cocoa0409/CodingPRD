"""Exchange1031 endpoints — gain calculation, 45-day and 180-day rules."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, jsonify

from app import store
from app.audit import append_audit
from app.auth import require_role
from app.calculations import section_1031_gain_initial
from app.envelope import success_envelope
from app.errors import ApiError
from app.idempotency import lookup as idem_lookup, remember as idem_remember, require_idempotency_key
from app.request_helpers import check_version, get_json_body
from app.serializers import serialize_exchange
from app.util import (
    new_uuid,
    now_ts,
    optional_number,
    parse_iso_dt,
    require_number,
    require_str,
    round_half_up_money,
)

bp = Blueprint("exchanges", __name__)


@bp.post("/exchanges")
def create_exchange():
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    file_id = require_str(body, "escrow_file_id")
    f = store.escrow_files.get(file_id)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", "Escrow file not found.")
    if not f.get("is_1031_exchange"):
        raise ApiError("ERR_CROSS_ENTITY_STATE", "Escrow file is not flagged as a §1031 exchange.")

    basis = round_half_up_money(require_number(body, "relinquished_basis"))
    sale_price = round_half_up_money(require_number(body, "relinquished_sale_price"))
    cash_boot = round_half_up_money(optional_number(body, "cash_boot_received", 0))
    mortgage_relief = round_half_up_money(optional_number(body, "mortgage_relief", 0))
    if basis < 0 or sale_price < 0 or cash_boot < 0 or mortgage_relief < 0:
        raise ApiError("ERR_BAD_REQUEST", "Numeric inputs must be non-negative.")

    gain = section_1031_gain_initial(
        relinquished_basis=basis,
        relinquished_sale_price=sale_price,
        cash_boot_received=cash_boot,
        mortgage_relief=mortgage_relief,
    )

    closing_dt = parse_iso_dt(f["closing_date_planned"])
    ident_at = closing_dt + timedelta(days=45)
    exch_at = closing_dt + timedelta(days=180)

    xid = new_uuid()
    ts = now_ts()
    ex = {
        "id": xid,
        "escrow_file_id": file_id,
        "relinquished_basis": basis,
        "relinquished_sale_price": sale_price,
        "cash_boot_received": cash_boot,
        "mortgage_relief": mortgage_relief,
        "realized_gain": gain["realized_gain"],
        "recognized_gain": gain["recognized_gain"],
        "deferred_gain": gain["deferred_gain"],
        "identification_deadline_at": now_ts(ident_at),
        "exchange_deadline_at": now_ts(exch_at),
        "status": "INITIATED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.exchanges[xid] = ex
    append_audit(
        escrow_file_id=file_id,
        subject_kind="EXCHANGE_1031",
        subject_id=xid,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="EXCHANGE_INITIATED",
        payload_body=body,
    )
    response = success_envelope(serialize_exchange(ex))
    idem_remember(idem_key, body, 201, response)
    return jsonify(response), 201


@bp.get("/exchanges/<xid>")
def read_exchange(xid: str):
    user_id, role = require_role(["EscrowOfficer", "Buyer", "Seller"])
    ex = store.exchanges.get(xid)
    if ex is None:
        raise ApiError("ERR_NOT_FOUND", "Exchange not found.")
    if role in {"Buyer", "Seller"}:
        f = store.escrow_files.get(ex["escrow_file_id"])
        if role == "Buyer" and (not f or f["buyer_party_id"] != user_id):
            raise ApiError("ERR_FORBIDDEN_ROLE", "Buyer cannot read this exchange.")
        if role == "Seller" and (not f or f["seller_party_id"] != user_id):
            raise ApiError("ERR_FORBIDDEN_ROLE", "Seller cannot read this exchange.")
    # Re-validate invariant on every read.
    rg = Decimal(str(ex["recognized_gain"]))
    dg = Decimal(str(ex["deferred_gain"]))
    realized = Decimal(str(ex["realized_gain"]))
    if rg + dg != realized:
        raise ApiError("ERR_1031_GAIN_INVARIANT", "Gain components do not sum to realized_gain.")
    return jsonify(success_envelope(serialize_exchange(ex))), 200


@bp.post("/exchanges/<xid>/identify")
def identify_exchange(xid: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        ex = store.exchanges.get(xid)
        if ex is None:
            raise ApiError("ERR_NOT_FOUND", "Exchange not found.")
        if ex["status"] != "INITIATED":
            raise ApiError("ERR_INVALID_STATE", "Exchange must be INITIATED to identify.")
        check_version(ex, body)
        if store.clock.now() > parse_iso_dt(ex["identification_deadline_at"]):
            raise ApiError("ERR_1031_45DAY_LAPSED", "§1031 45-day deadline has passed.")
        ex["status"] = "IDENTIFIED"
        ex["updated_at"] = now_ts()
        ex["version"] = int(ex.get("version", 1)) + 1
    append_audit(
        escrow_file_id=ex["escrow_file_id"],
        subject_kind="EXCHANGE_1031",
        subject_id=xid,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="EXCHANGE_IDENTIFIED",
        payload_body=body,
    )
    response = success_envelope(serialize_exchange(ex))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


@bp.post("/exchanges/<xid>/close-deferred")
def close_deferred(xid: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        ex = store.exchanges.get(xid)
        if ex is None:
            raise ApiError("ERR_NOT_FOUND", "Exchange not found.")
        if ex["status"] != "IDENTIFIED":
            raise ApiError("ERR_INVALID_STATE", "Exchange must be IDENTIFIED to close-deferred.")
        check_version(ex, body)
        if store.clock.now() > parse_iso_dt(ex["exchange_deadline_at"]):
            raise ApiError("ERR_1031_180DAY_LAPSED", "§1031 180-day deadline has passed.")
        # Cross-entity precondition: a SETTLED disbursement to QI exists
        qi_settled = False
        for d in store.disbursements.values():
            if d["escrow_file_id"] != ex["escrow_file_id"]:
                continue
            if d["status"] != "SETTLED":
                continue
            w = store.wire_instructions.get(d["wire_instruction_id"])
            if w and w["beneficiary_kind"] == "QUALIFIED_INTERMEDIARY":
                qi_settled = True
                break
        if not qi_settled:
            raise ApiError(
                "ERR_CROSS_ENTITY_STATE",
                "A SETTLED disbursement to a QUALIFIED_INTERMEDIARY beneficiary is required.",
            )
        # Invariant
        rg = Decimal(str(ex["recognized_gain"]))
        dg = Decimal(str(ex["deferred_gain"]))
        realized = Decimal(str(ex["realized_gain"]))
        if rg + dg != realized:
            raise ApiError("ERR_1031_GAIN_INVARIANT", "Gain components do not sum to realized_gain.")
        ex["status"] = "CLOSED_DEFERRED"
        ex["updated_at"] = now_ts()
        ex["version"] = int(ex.get("version", 1)) + 1
    append_audit(
        escrow_file_id=ex["escrow_file_id"],
        subject_kind="EXCHANGE_1031",
        subject_id=xid,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="EXCHANGE_CLOSED_DEFERRED",
        payload_body=body,
    )
    response = success_envelope(serialize_exchange(ex))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


@bp.post("/exchanges/<xid>/fail")
def fail_exchange(xid: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        ex = store.exchanges.get(xid)
        if ex is None:
            raise ApiError("ERR_NOT_FOUND", "Exchange not found.")
        if ex["status"] not in {"INITIATED", "IDENTIFIED"}:
            raise ApiError("ERR_INVALID_STATE", "Exchange must be INITIATED or IDENTIFIED to fail.")
        check_version(ex, body)
        ex["status"] = "FAILED_TAXABLE"
        ex["recognized_gain"] = ex["realized_gain"]
        ex["deferred_gain"] = Decimal("0.00")
        ex["updated_at"] = now_ts()
        ex["version"] = int(ex.get("version", 1)) + 1
    append_audit(
        escrow_file_id=ex["escrow_file_id"],
        subject_kind="EXCHANGE_1031",
        subject_id=xid,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="EXCHANGE_FAILED",
        payload_body=body,
    )
    response = success_envelope(serialize_exchange(ex))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200
