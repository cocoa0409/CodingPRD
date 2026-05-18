"""EscrowFile endpoints."""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from flask import Blueprint, jsonify, request

from app import store
from app.audit import append_audit
from app.auth import require_role
from app.envelope import success_envelope
from app.errors import ApiError
from app.idempotency import lookup as idem_lookup, remember as idem_remember, require_idempotency_key
from app.request_helpers import check_version, get_json_body, get_pagination
from app.serializers import serialize_audit, serialize_escrow_file
from app.util import (
    new_uuid,
    now_ts,
    optional_bool,
    optional_number,
    parse_iso_dt,
    require_enum,
    require_number,
    require_str,
    round_half_up_money,
)

bp = Blueprint("escrow_files", __name__)


CANCEL_REASONS = {"BUYER_DEFAULT", "SELLER_DEFAULT", "TITLE_DEFECT", "MUTUAL_RELEASE"}
NON_TERMINAL_STATES = {"OPEN", "CONTINGENT_TITLE", "CONTINGENT_CD", "CONTINGENT_WIRE"}


# ---------------------------------------------------------------------------
# Create / Read / List
# ---------------------------------------------------------------------------
@bp.post("/escrow-files")
def open_file():
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    property_id = require_str(body, "property_id")
    buyer_party_id = require_str(body, "buyer_party_id")
    seller_party_id = require_str(body, "seller_party_id")
    lender_party_id = body.get("lender_party_id")
    qi_party_id = body.get("qi_party_id")
    purchase_price = round_half_up_money(require_number(body, "purchase_price"))
    loan_amount = round_half_up_money(optional_number(body, "loan_amount", 0))
    closing_date_planned = require_str(body, "closing_date_planned")
    is_1031 = optional_bool(body, "is_1031_exchange", False)

    # Existence checks (left-to-right per §2.8)
    if property_id not in store.properties:
        raise ApiError("ERR_NOT_FOUND", "Property not found.")
    if buyer_party_id not in store.parties:
        raise ApiError("ERR_NOT_FOUND", "Buyer party not found.")
    if seller_party_id not in store.parties:
        raise ApiError("ERR_NOT_FOUND", "Seller party not found.")
    if lender_party_id is not None and lender_party_id not in store.parties:
        raise ApiError("ERR_NOT_FOUND", "Lender party not found.")
    if qi_party_id is not None and qi_party_id not in store.parties:
        raise ApiError("ERR_NOT_FOUND", "QI party not found.")

    if purchase_price <= 0:
        raise ApiError("ERR_BAD_REQUEST", "purchase_price must be positive.")
    if loan_amount < 0:
        raise ApiError("ERR_BAD_REQUEST", "loan_amount must be non-negative.")

    # Closing-date-planned must parse as ISO.
    parse_iso_dt(closing_date_planned)

    fid = new_uuid()
    ts = now_ts()
    f = {
        "id": fid,
        "property_id": property_id,
        "buyer_party_id": buyer_party_id,
        "seller_party_id": seller_party_id,
        "lender_party_id": lender_party_id,
        "qi_party_id": qi_party_id,
        "purchase_price": purchase_price,
        "loan_amount": loan_amount,
        "closing_date_planned": closing_date_planned,
        "is_1031_exchange": is_1031,
        "status": "OPEN",
        "cancel_reason": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.escrow_files[fid] = f
    append_audit(
        escrow_file_id=fid,
        subject_kind="ESCROW_FILE",
        subject_id=fid,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="ESCROW_FILE_OPENED",
        payload_body=body,
    )
    response = success_envelope(serialize_escrow_file(f))
    idem_remember(idem_key, body, 201, response)
    return jsonify(response), 201


@bp.get("/escrow-files/<file_id>")
def read_file(file_id: str):
    require_role(["EscrowOfficer", "TitleOfficer", "DisbursementApprover", "Buyer", "Seller"])
    f = store.escrow_files.get(file_id)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", "Escrow file not found.")
    return jsonify(success_envelope(serialize_escrow_file(f))), 200


@bp.get("/escrow-files")
def list_files():
    require_role(["EscrowOfficer", "TitleOfficer", "DisbursementApprover"])
    limit, offset = get_pagination()
    status_filter = request.args.get("status")
    buyer = request.args.get("buyer_party_id")
    seller = request.args.get("seller_party_id")

    items = list(store.escrow_files.values())
    if status_filter:
        items = [f for f in items if f["status"] == status_filter]
    if buyer:
        items = [f for f in items if f["buyer_party_id"] == buyer]
    if seller:
        items = [f for f in items if f["seller_party_id"] == seller]

    items.sort(key=lambda f: f["created_at"])
    page = items[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": len(items),
        "has_more": offset + limit < len(items),
    }
    return jsonify(
        success_envelope(
            [serialize_escrow_file(f) for f in page],
            is_array=True,
            pagination=pagination,
        )
    ), 200


# ---------------------------------------------------------------------------
# Advance — auto-evaluated state machine
# ---------------------------------------------------------------------------
def _emds_for(file_id: str) -> list[dict]:
    return [e for e in store.earnest_money.values() if e["escrow_file_id"] == file_id]


def _searches_for(file_id: str) -> list[dict]:
    return [s for s in store.title_searches.values() if s["escrow_file_id"] == file_id]


def _policies_for(file_id: str) -> list[dict]:
    return [p for p in store.title_policies.values() if p["escrow_file_id"] == file_id]


def _ccrs_for(file_id: str) -> list[dict]:
    return [c for c in store.ccr_disclosures.values() if c["escrow_file_id"] == file_id]


def _cds_for(file_id: str) -> list[dict]:
    return [c for c in store.closing_disclosures.values() if c["escrow_file_id"] == file_id]


def _wires_for(file_id: str) -> list[dict]:
    return [w for w in store.wire_instructions.values() if w["escrow_file_id"] == file_id]


def _disbs_for(file_id: str) -> list[dict]:
    return [d for d in store.disbursements.values() if d["escrow_file_id"] == file_id]


def _can_advance(f: dict, from_state: str, to_state: str) -> tuple[bool, str | None]:
    """Return (can_advance, blocking_error_id_or_none) for a single hop."""
    fid = f["id"]
    if from_state == "OPEN" and to_state == "CONTINGENT_TITLE":
        if any(e["status"] == "HELD" for e in _emds_for(fid)):
            return True, None
        return False, "ERR_CROSS_ENTITY_STATE"

    if from_state == "CONTINGENT_TITLE" and to_state == "CONTINGENT_CD":
        if not _ccrs_for(fid):
            return False, "ERR_CCR_NOT_ACKNOWLEDGED"
        cleared = any(s["status"] == "CLEARED" for s in _searches_for(fid))
        owners_bound = any(
            p["status"] == "BOUND" and p["policy_kind"] == "OWNERS" for p in _policies_for(fid)
        )
        if cleared and owners_bound:
            return True, None
        return False, "ERR_CROSS_ENTITY_STATE"

    if from_state == "CONTINGENT_CD" and to_state == "CONTINGENT_WIRE":
        for c in _cds_for(fid):
            if c["status"] == "READY_TO_FUND":
                return True, None
        # If a CD exists but is only ACKNOWLEDGED and the waiting period has not lapsed:
        for c in _cds_for(fid):
            if c["status"] == "ACKNOWLEDGED":
                eligible = c.get("earliest_funding_at")
                if eligible and store.clock.now() < parse_iso_dt(eligible):
                    return False, "ERR_CD_WAITING_PERIOD"
        return False, "ERR_CROSS_ENTITY_STATE"

    if from_state == "CONTINGENT_WIRE" and to_state == "READY_TO_CLOSE":
        # Each required beneficiary_kind that has a non-zero disbursement must
        # be CONFIRMED.  In practice, every wire with an associated active
        # disbursement must be CONFIRMED.  We require at least one CONFIRMED
        # wire and that every wire referenced by an active disbursement is
        # CONFIRMED.
        wires = _wires_for(fid)
        active_disbs = [d for d in _disbs_for(fid) if d["status"] in {"PROPOSED", "APPROVED", "SENT", "SETTLED"}]
        wire_ids_used = {d["wire_instruction_id"] for d in active_disbs}
        for wid in wire_ids_used:
            w = store.wire_instructions.get(wid)
            if not w or w["status"] != "CONFIRMED":
                return False, "ERR_CROSS_ENTITY_STATE"
        if not wires or not any(w["status"] == "CONFIRMED" for w in wires):
            return False, "ERR_CROSS_ENTITY_STATE"
        return True, None

    return False, "ERR_INVALID_STATE"


@bp.post("/escrow-files/<file_id>/advance")
def advance_file(file_id: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    f = store.escrow_files.get(file_id)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", "Escrow file not found.")

    if f["status"] not in NON_TERMINAL_STATES:
        raise ApiError("ERR_INVALID_STATE", f"Escrow file in terminal state {f['status']}.")

    check_version(f, body)

    # Walk the diamond. Try to advance up to four hops in one call.
    chain = ["OPEN", "CONTINGENT_TITLE", "CONTINGENT_CD", "CONTINGENT_WIRE", "READY_TO_CLOSE"]
    advanced = False
    while True:
        try:
            current_index = chain.index(f["status"])
        except ValueError:
            break
        if current_index == len(chain) - 1:
            break
        next_state = chain[current_index + 1]
        ok, err = _can_advance(f, f["status"], next_state)
        if not ok:
            if not advanced:
                raise ApiError(err or "ERR_CROSS_ENTITY_STATE", f"Cannot advance from {f['status']}.")
            break
        f["status"] = next_state
        f["updated_at"] = now_ts()
        f["version"] = int(f.get("version", 1)) + 1
        append_audit(
            escrow_file_id=file_id,
            subject_kind="ESCROW_FILE",
            subject_id=file_id,
            actor_user_id=user_id,
            actor_role="EscrowOfficer",
            action=f"ESCROW_FILE_ADVANCED_TO_{next_state}",
            payload_body=body,
        )
        advanced = True

    if not advanced:
        # Nothing changed: re-raise the most relevant blocking error.
        try:
            current_index = chain.index(f["status"])
            next_state = chain[current_index + 1]
            ok, err = _can_advance(f, f["status"], next_state)
            if not ok:
                raise ApiError(err or "ERR_CROSS_ENTITY_STATE", f"Cannot advance from {f['status']}.")
        except (ValueError, IndexError):
            raise ApiError("ERR_INVALID_STATE", f"Cannot advance from {f['status']}.")

    response = success_envelope(serialize_escrow_file(f))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------
@bp.post("/escrow-files/<file_id>/close")
def close_file(file_id: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    f = store.escrow_files.get(file_id)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", "Escrow file not found.")
    if f["status"] != "READY_TO_CLOSE":
        raise ApiError("ERR_INVALID_STATE", "Escrow file must be READY_TO_CLOSE to close.")
    check_version(f, body)

    # All disbursements must be SETTLED
    disbs = _disbs_for(file_id)
    for d in disbs:
        if d["status"] not in {"SETTLED", "REVERSED"}:
            raise ApiError("ERR_CROSS_ENTITY_STATE", "All disbursements must be SETTLED to close.")
    # If 1031: linked exchange terminal
    if f.get("is_1031_exchange"):
        ex_list = [e for e in store.exchanges.values() if e["escrow_file_id"] == file_id]
        for ex in ex_list:
            if ex["status"] not in {"CLOSED_DEFERRED", "FAILED_TAXABLE"}:
                raise ApiError(
                    "ERR_CROSS_ENTITY_STATE",
                    "§1031 exchange must be in CLOSED_DEFERRED or FAILED_TAXABLE.",
                )

    # Apply terminal transition.
    f["status"] = "CLOSED"
    f["updated_at"] = now_ts()
    f["version"] = int(f.get("version", 1)) + 1
    append_audit(
        escrow_file_id=file_id,
        subject_kind="ESCROW_FILE",
        subject_id=file_id,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="ESCROW_FILE_CLOSED",
        payload_body=body,
    )

    # Cascade: any EMD still HELD -> RELEASED_TO_SELLER
    for e in _emds_for(file_id):
        if e["status"] == "HELD":
            e["status"] = "RELEASED_TO_SELLER"
            e["forfeited_amount"] = e["amount"]
            e["refunded_amount"] = 0
            e["updated_at"] = now_ts()
            e["version"] = int(e.get("version", 1)) + 1
            append_audit(
                escrow_file_id=file_id,
                subject_kind="EMD",
                subject_id=e["id"],
                actor_user_id=user_id,
                actor_role="EscrowOfficer",
                action="EMD_RELEASED_TO_SELLER_CASCADE",
                payload_body={},
            )

    response = success_envelope(serialize_escrow_file(f))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------
@bp.post("/escrow-files/<file_id>/cancel")
def cancel_file(file_id: str):
    user_id, _role = require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    f = store.escrow_files.get(file_id)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", "Escrow file not found.")
    if f["status"] not in NON_TERMINAL_STATES:
        raise ApiError("ERR_INVALID_STATE", f"Cannot cancel in state {f['status']}.")
    check_version(f, body)
    cancel_reason = require_enum(body, "cancel_reason", CANCEL_REASONS)
    # MUTUAL_RELEASE at the file level requires shares to be supplied if EMDs are HELD.
    split_buyer = round_half_up_money(optional_number(body, "split_buyer_share", 0))
    split_seller = round_half_up_money(optional_number(body, "split_seller_share", 0))

    f["status"] = "CANCELLED"
    f["cancel_reason"] = cancel_reason
    f["updated_at"] = now_ts()
    f["version"] = int(f.get("version", 1)) + 1
    append_audit(
        escrow_file_id=file_id,
        subject_kind="ESCROW_FILE",
        subject_id=file_id,
        actor_user_id=user_id,
        actor_role="EscrowOfficer",
        action="ESCROW_FILE_CANCELLED",
        payload_body=body,
    )

    # Cascade: EMD disposes by cancel_reason
    for e in _emds_for(file_id):
        if e["status"] != "HELD":
            # PENDING_FUNDS still pending — also handled per spec.
            if e["status"] == "PENDING_FUNDS":
                # A pending EMD never funded: simply leave as-is (no disposition).
                pass
            continue
        if cancel_reason == "BUYER_DEFAULT":
            e["status"] = "RELEASED_TO_SELLER"
            e["forfeited_amount"] = e["amount"]
            e["refunded_amount"] = 0
        elif cancel_reason in {"SELLER_DEFAULT", "TITLE_DEFECT"}:
            e["status"] = "RELEASED_TO_BUYER"
            e["forfeited_amount"] = 0
            e["refunded_amount"] = e["amount"]
        elif cancel_reason == "MUTUAL_RELEASE":
            if Decimal(str(split_buyer)) + Decimal(str(split_seller)) != Decimal(str(e["amount"])):
                raise ApiError(
                    "ERR_EMD_SPLIT_INVARIANT",
                    "split_buyer_share + split_seller_share must equal EMD.amount exactly.",
                )
            e["status"] = "SPLIT"
            e["refunded_amount"] = split_buyer
            e["forfeited_amount"] = split_seller
            e["split_buyer_share"] = split_buyer
            e["split_seller_share"] = split_seller
        e["updated_at"] = now_ts()
        e["version"] = int(e.get("version", 1)) + 1
        append_audit(
            escrow_file_id=file_id,
            subject_kind="EMD",
            subject_id=e["id"],
            actor_user_id=user_id,
            actor_role="EscrowOfficer",
            action=f"EMD_DISPOSITION_{cancel_reason}",
            payload_body={},
        )

    # Cascade: QUOTED title policies -> VOIDED ; ORDERED title searches archived (kept as ORDERED+marked archived).
    for p in _policies_for(file_id):
        if p["status"] == "QUOTED":
            p["status"] = "VOIDED"
            p["updated_at"] = now_ts()
            p["version"] = int(p.get("version", 1)) + 1
            append_audit(
                escrow_file_id=file_id,
                subject_kind="TITLE_POLICY",
                subject_id=p["id"],
                actor_user_id=user_id,
                actor_role="EscrowOfficer",
                action="TITLE_POLICY_VOIDED_CASCADE",
                payload_body={},
            )

    # Cascade: ISSUED CDs -> VOIDED ; DRAFT CDs -> VOIDED
    for c in _cds_for(file_id):
        if c["status"] in {"DRAFT", "ISSUED", "ACKNOWLEDGED", "REVISED", "READY_TO_FUND"}:
            c["status"] = "VOIDED"
            c["updated_at"] = now_ts()
            c["version"] = int(c.get("version", 1)) + 1
            append_audit(
                escrow_file_id=file_id,
                subject_kind="CD",
                subject_id=c["id"],
                actor_user_id=user_id,
                actor_role="EscrowOfficer",
                action="CD_VOIDED_CASCADE",
                payload_body={},
            )

    response = success_envelope(serialize_escrow_file(f))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


# ---------------------------------------------------------------------------
# Audit events listing
# ---------------------------------------------------------------------------
@bp.get("/escrow-files/<file_id>/audit-events")
def list_audit_events(file_id: str):
    require_role(["EscrowOfficer", "DisbursementApprover", "TitleOfficer"])
    if file_id not in store.escrow_files:
        raise ApiError("ERR_NOT_FOUND", "Escrow file not found.")
    limit, offset = get_pagination()
    items = [e for e in store.audit_events.values() if e["escrow_file_id"] == file_id]
    items.sort(key=lambda e: e["created_at"])
    page = items[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": len(items),
        "has_more": offset + limit < len(items),
    }
    return jsonify(
        success_envelope(
            [serialize_audit(e) for e in page],
            is_array=True,
            pagination=pagination,
        )
    ), 200
