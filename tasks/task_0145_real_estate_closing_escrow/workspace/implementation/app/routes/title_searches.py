"""TitleSearch endpoints."""
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
from app.serializers import serialize_title_search
from app.util import (
    new_uuid,
    now_ts,
    optional_number,
    require_bool,
    require_int,
    require_str,
    round_half_up_money,
)

bp = Blueprint("title_searches", __name__)


@bp.post("/title-searches")
def create_search():
    user_id, role = require_role(["EscrowOfficer", "TitleOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    file_id = require_str(body, "escrow_file_id")
    if file_id not in store.escrow_files:
        raise ApiError("ERR_NOT_FOUND", "Escrow file not found.")
    sid = new_uuid()
    ts = now_ts()
    search = {
        "id": sid,
        "escrow_file_id": file_id,
        "chain_of_title_clean": None,
        "open_liens_total": Decimal("0.00"),
        "encumbrance_count": 0,
        "status": "ORDERED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.title_searches[sid] = search
    append_audit(
        escrow_file_id=file_id,
        subject_kind="TITLE_SEARCH",
        subject_id=sid,
        actor_user_id=user_id,
        actor_role=role,
        action="TITLE_SEARCH_ORDERED",
        payload_body=body,
    )
    response = success_envelope(serialize_title_search(search))
    idem_remember(idem_key, body, 201, response)
    return jsonify(response), 201


@bp.get("/title-searches/<sid>")
def read_search(sid: str):
    require_role(["EscrowOfficer", "TitleOfficer", "Buyer", "Seller"])
    s = store.title_searches.get(sid)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", "Title search not found.")
    return jsonify(success_envelope(serialize_title_search(s))), 200


@bp.patch("/title-searches/<sid>")
def submit_findings(sid: str):
    user_id, _role = require_role(["TitleOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        s = store.title_searches.get(sid)
        if s is None:
            raise ApiError("ERR_NOT_FOUND", "Title search not found.")
        if s["status"] != "ORDERED":
            raise ApiError("ERR_INVALID_STATE", "Title search must be ORDERED to submit findings.")
        check_version(s, body)
        s["chain_of_title_clean"] = require_bool(body, "chain_of_title_clean")
        s["open_liens_total"] = round_half_up_money(optional_number(body, "open_liens_total", 0))
        s["encumbrance_count"] = require_int(body, "encumbrance_count")
        if s["open_liens_total"] < 0:
            raise ApiError("ERR_BAD_REQUEST", "open_liens_total must be non-negative.")
        if s["encumbrance_count"] < 0:
            raise ApiError("ERR_BAD_REQUEST", "encumbrance_count must be non-negative.")
        s["status"] = "COMPLETED"
        s["updated_at"] = now_ts()
        s["version"] = int(s.get("version", 1)) + 1
    append_audit(
        escrow_file_id=s["escrow_file_id"],
        subject_kind="TITLE_SEARCH",
        subject_id=sid,
        actor_user_id=user_id,
        actor_role="TitleOfficer",
        action="TITLE_SEARCH_COMPLETED",
        payload_body=body,
    )
    response = success_envelope(serialize_title_search(s))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


@bp.post("/title-searches/<sid>/clear")
def clear_search(sid: str):
    user_id, _role = require_role(["TitleOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        s = store.title_searches.get(sid)
        if s is None:
            raise ApiError("ERR_NOT_FOUND", "Title search not found.")
        if s["status"] != "COMPLETED":
            raise ApiError("ERR_INVALID_STATE", "Title search must be COMPLETED to clear.")
        check_version(s, body)
        if not s.get("chain_of_title_clean"):
            raise ApiError("ERR_INVALID_STATE", "Cannot clear: chain_of_title_clean is false.")
        if Decimal(str(s.get("open_liens_total", 0))) != 0:
            raise ApiError("ERR_INVALID_STATE", "Cannot clear: open liens remain.")
        s["status"] = "CLEARED"
        s["updated_at"] = now_ts()
        s["version"] = int(s.get("version", 1)) + 1
    append_audit(
        escrow_file_id=s["escrow_file_id"],
        subject_kind="TITLE_SEARCH",
        subject_id=sid,
        actor_user_id=user_id,
        actor_role="TitleOfficer",
        action="TITLE_SEARCH_CLEARED",
        payload_body=body,
    )
    response = success_envelope(serialize_title_search(s))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200


@bp.post("/title-searches/<sid>/mark-defective")
def mark_defective(sid: str):
    user_id, _role = require_role(["TitleOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status
    with store.mutation_lock:
        s = store.title_searches.get(sid)
        if s is None:
            raise ApiError("ERR_NOT_FOUND", "Title search not found.")
        if s["status"] != "COMPLETED":
            raise ApiError("ERR_INVALID_STATE", "Title search must be COMPLETED to mark defective.")
        check_version(s, body)
        s["status"] = "DEFECTIVE"
        s["updated_at"] = now_ts()
        s["version"] = int(s.get("version", 1)) + 1
        # Cascade: any QUOTED policies on same escrow_file_id -> VOIDED
        for p in list(store.title_policies.values()):
            if p["escrow_file_id"] == s["escrow_file_id"] and p["status"] == "QUOTED":
                p["status"] = "VOIDED"
                p["updated_at"] = now_ts()
                p["version"] = int(p.get("version", 1)) + 1
                append_audit(
                    escrow_file_id=p["escrow_file_id"],
                    subject_kind="TITLE_POLICY",
                    subject_id=p["id"],
                    actor_user_id=user_id,
                    actor_role="TitleOfficer",
                    action="TITLE_POLICY_VOIDED_CASCADE",
                    payload_body={},
                )
    append_audit(
        escrow_file_id=s["escrow_file_id"],
        subject_kind="TITLE_SEARCH",
        subject_id=sid,
        actor_user_id=user_id,
        actor_role="TitleOfficer",
        action="TITLE_SEARCH_DEFECTIVE",
        payload_body=body,
    )
    response = success_envelope(serialize_title_search(s))
    idem_remember(idem_key, body, 200, response)
    return jsonify(response), 200
