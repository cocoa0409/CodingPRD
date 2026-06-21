"""EstoppelCertificate endpoints (PRD §3.10)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_NOT_LEASE_OWNER, ERR_ESTOPPEL_BALANCE_MISMATCH, ERR_DISPUTE_NOTE_REQUIRED,
)
from middleware import (
    auth_required, ALL_ROLES, PROPERTY_MANAGER, ACCOUNTANT, TENANT, current_user_id,
)
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_fields, serialize, serialize_list, is_int, is_str,
    parse_pagination, paginate, order_by_created,
)
from services.common import new_common_fields, touch

bp = Blueprint("estoppels", __name__)

RESPONSES = {"CONFIRMED", "DISPUTED"}


@bp.post("/estoppels")
def create_estoppel():
    auth_required({PROPERTY_MANAGER, ACCOUNTANT})()
    body = get_body()
    require_fields(body, ["lease_id", "asserted_balance_cents", "asserted_base_rent_cents_annual"])

    lease_id = body["lease_id"]
    if db.leases.get(lease_id) is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "lease_id references a non-existent lease")

    asserted_balance = body["asserted_balance_cents"]
    if not is_int(asserted_balance):
        raise APIError(ERR_INVALID_REQUEST, 400, "asserted_balance_cents must be an integer")

    asserted_base_rent = body["asserted_base_rent_cents_annual"]
    if not is_int(asserted_base_rent):
        raise APIError(ERR_INVALID_REQUEST, 400, "asserted_base_rent_cents_annual must be an integer")

    cert = {
        **new_common_fields(),
        "lease_id": lease_id,
        "asserted_balance_cents": asserted_balance,
        "asserted_base_rent_cents_annual": asserted_base_rent,
        "tenant_response": None,
        "dispute_note": None,
        "status": "ISSUED",
    }
    db.estoppels[cert["id"]] = cert
    return ok_object(serialize(cert), http_status=201)


@bp.get("/estoppels/<eid>")
def get_estoppel(eid):
    auth_required(ALL_ROLES)()
    e = db.estoppels.get(eid)
    if e is None:
        raise APIError(ERR_NOT_FOUND, 404, "Estoppel certificate not found")
    return ok_object(serialize(e))


@bp.get("/estoppels")
def list_estoppels():
    auth_required(ALL_ROLES)()
    limit, offset = parse_pagination()
    items = list(db.estoppels.values())
    lease_id = request.args.get("lease_id")
    if lease_id is not None:
        items = [e for e in items if e["lease_id"] == lease_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.post("/estoppels/<eid>/respond")
def respond_estoppel(eid):
    auth_required({TENANT})()
    cert = db.estoppels.get(eid)
    if cert is None:
        raise APIError(ERR_NOT_FOUND, 404, "Estoppel certificate not found")

    lease = db.leases.get(cert["lease_id"])
    if lease is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "Referenced lease not found")
    # Priority 3: acting tenant must own the referenced lease.
    if lease["tenant_id"] != current_user_id():
        raise APIError(ERR_NOT_LEASE_OWNER, 403, "Acting tenant does not own the referenced lease")

    body = get_body()
    require_fields(body, ["tenant_response"])
    tenant_response = body["tenant_response"]
    if tenant_response not in RESPONSES:
        raise APIError(ERR_INVALID_REQUEST, 400, "tenant_response must be CONFIRMED or DISPUTED")

    # Priority 8: only an ISSUED certificate may be responded to.
    if cert["status"] != "ISSUED":
        raise APIError(ERR_INVALID_STATE, 409, "Estoppel certificate must be ISSUED to respond")

    if tenant_response == "CONFIRMED":
        # Asserted balance must match the lease's live outstanding balance.
        if cert["asserted_balance_cents"] != lease["outstanding_balance_cents"]:
            raise APIError(ERR_ESTOPPEL_BALANCE_MISMATCH, 422,
                           "asserted_balance_cents no longer matches the live ledger balance")
        cert["tenant_response"] = "CONFIRMED"
        cert["status"] = "CONFIRMED"
    else:  # DISPUTED
        dispute_note = body.get("dispute_note")
        if not is_str(dispute_note) or not dispute_note.strip():
            raise APIError(ERR_DISPUTE_NOTE_REQUIRED, 422,
                           "A non-empty dispute_note is required for a DISPUTED response")
        cert["tenant_response"] = "DISPUTED"
        cert["dispute_note"] = dispute_note
        cert["status"] = "DISPUTED"

    touch(cert)
    return ok_object(serialize(cert))
