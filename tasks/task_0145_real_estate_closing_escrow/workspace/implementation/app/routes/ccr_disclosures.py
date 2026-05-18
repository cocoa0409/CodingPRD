"""CCRDisclosure endpoints — immutable, append-only signed record."""
from __future__ import annotations

from flask import Blueprint, jsonify

from app import store
from app.audit import append_audit
from app.auth import require_role
from app.envelope import success_envelope
from app.errors import ApiError
from app.idempotency import lookup as idem_lookup, remember as idem_remember, require_idempotency_key
from app.request_helpers import get_json_body
from app.serializers import serialize_ccr
from app.util import new_uuid, now_ts, require_str

bp = Blueprint("ccr", __name__)


@bp.post("/ccr-disclosures")
def create_ccr():
    user_id, _role = require_role(["Buyer"])
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
    if f["buyer_party_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Buyer can only acknowledge their own escrow file.")
    doc_hash = require_str(body, "ccr_document_hash")
    material = body.get("material_restrictions", [])
    if not isinstance(material, list):
        raise ApiError("ERR_BAD_REQUEST", "material_restrictions must be an array.")

    cid = new_uuid()
    ts = now_ts()
    ccr = {
        "id": cid,
        "escrow_file_id": file_id,
        "ccr_document_hash": doc_hash,
        "buyer_acknowledged_at": ts,
        "material_restrictions": material,
        "created_at": ts,
    }
    store.ccr_disclosures[cid] = ccr
    append_audit(
        escrow_file_id=file_id,
        subject_kind="CCR",
        subject_id=cid,
        actor_user_id=user_id,
        actor_role="Buyer",
        action="CCR_ACKNOWLEDGED",
        payload_body=body,
    )
    response = success_envelope(serialize_ccr(ccr))
    idem_remember(idem_key, body, 201, response)
    return jsonify(response), 201


@bp.get("/ccr-disclosures/<cid>")
def read_ccr(cid: str):
    require_role(["EscrowOfficer", "Buyer", "Seller", "TitleOfficer"])
    c = store.ccr_disclosures.get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "CCR disclosure not found.")
    return jsonify(success_envelope(serialize_ccr(c))), 200
