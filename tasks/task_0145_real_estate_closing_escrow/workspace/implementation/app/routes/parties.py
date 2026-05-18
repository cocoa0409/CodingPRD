"""Party endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify

from app import store
from app.auth import require_role
from app.errors import ApiError
from app.envelope import success_envelope
from app.idempotency import lookup as idem_lookup, remember as idem_remember, require_idempotency_key
from app.request_helpers import get_json_body
from app.serializers import serialize_party
from app.util import new_uuid, now_ts, require_enum, require_str

bp = Blueprint("parties", __name__)

PARTY_KINDS = {"BUYER", "SELLER", "LENDER", "QUALIFIED_INTERMEDIARY", "TAX_AUTHORITY"}
# Note: TAX_AUTHORITY is added beyond the explicit scaffold set so that tax-
# authority wires can reference a Party of matching kind.


@bp.post("/parties")
def create_party():
    require_role(["EscrowOfficer"])
    idem_key = require_idempotency_key()
    body = get_json_body()
    cached = idem_lookup(idem_key, body)
    if cached is not None:
        status, response = cached
        return jsonify(response), status

    full_name = require_str(body, "full_name")
    party_kind = require_enum(body, "party_kind", PARTY_KINDS)
    contact_email = require_str(body, "contact_email")

    party_id = new_uuid()
    ts = now_ts()
    party = {
        "id": party_id,
        "full_name": full_name,
        "party_kind": party_kind,
        "contact_email": contact_email,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.parties[party_id] = party
    response = success_envelope(serialize_party(party))
    idem_remember(idem_key, body, 201, response)
    return jsonify(response), 201


@bp.get("/parties/<party_id>")
def read_party(party_id: str):
    require_role(["EscrowOfficer", "TitleOfficer", "DisbursementApprover", "Buyer", "Seller"])
    party = store.parties.get(party_id)
    if party is None:
        raise ApiError("ERR_NOT_FOUND", "Party not found.")
    return jsonify(success_envelope(serialize_party(party))), 200
