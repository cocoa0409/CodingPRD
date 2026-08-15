"""Debtor and secured-party routes (client-scoped creation/listing)."""
from flask import Blueprint

import errors
from db import store
from middleware import (
    as_str, auth, body, check_client_ownership, pagination_params, req_enum,
    req_str, require_role,
)
from response import ok, ok_list
from services import DEBTOR_TYPES, debtor_json, secured_party_json, stamp_new, touch
from util import new_id

bp = Blueprint("parties", __name__)


def _paginate(records, serializer):
    limit, offset = pagination_params()
    items = [serializer(r) for r in records]
    return ok_list(items[offset:offset + limit], len(items), limit, offset)


def _client_or_404(client_id):
    client = store.clients.get(client_id)
    if client is None:
        raise errors.err_not_found("client")
    return client


# ---------------------------------------------------------------------------
# Debtors
# ---------------------------------------------------------------------------

@bp.post("/client-accounts/<client_id>/debtors")
def create_debtor(client_id):
    auth()
    data = body()
    debtor_type = req_enum(data, "debtor_type", DEBTOR_TYPES)
    legal_name = req_str(data, "legal_name")
    jof = None
    if "jurisdiction_of_formation" in data and data["jurisdiction_of_formation"] is not None:
        jof = as_str(data["jurisdiction_of_formation"], "jurisdiction_of_formation")
    dl_name = None
    if "drivers_license_name" in data and data["drivers_license_name"] is not None:
        dl_name = as_str(data["drivers_license_name"], "drivers_license_name")
    if debtor_type == "ORGANIZATION" and not jof:
        raise errors.err_invalid_request(
            "jurisdiction_of_formation is required for ORGANIZATION debtors")
    user_id, role = auth()
    require_role(role, "ClientManager")
    check_client_ownership(role, user_id, client_id)
    _client_or_404(client_id)
    debtor = stamp_new({
        "id": new_id(),
        "client_id": client_id,
        "debtor_type": debtor_type,
        "legal_name": legal_name,
        "jurisdiction_of_formation": jof,
        "drivers_license_name": dl_name,
    })
    store.debtors[debtor["id"]] = debtor
    return ok(debtor_json(debtor), 201)


@bp.get("/client-accounts/<client_id>/debtors")
def list_debtors(client_id):
    user_id, role = auth()
    check_client_ownership(role, user_id, client_id)
    _client_or_404(client_id)
    records = [d for d in store.debtors.values() if d["client_id"] == client_id]
    return _paginate(records, debtor_json)


@bp.get("/debtors/<debtor_id>")
def get_debtor(debtor_id):
    auth()
    debtor = store.debtors.get(debtor_id)
    if debtor is None:
        raise errors.err_not_found("debtor")
    return ok(debtor_json(debtor))


@bp.patch("/debtors/<debtor_id>")
def update_debtor(debtor_id):
    auth()
    data = body()
    fields = {}
    if "legal_name" in data and data["legal_name"] is not None:
        fields["legal_name"] = as_str(data["legal_name"], "legal_name")
    if "drivers_license_name" in data:
        v = data["drivers_license_name"]
        fields["drivers_license_name"] = None if v is None else as_str(v, "drivers_license_name")
    if "jurisdiction_of_formation" in data:
        v = data["jurisdiction_of_formation"]
        fields["jurisdiction_of_formation"] = None if v is None else as_str(v, "jurisdiction_of_formation")
    user_id, role = auth()
    require_role(role, "ClientManager")
    debtor = store.debtors.get(debtor_id)
    if debtor is None:
        raise errors.err_not_found("debtor")
    if user_id != debtor["client_id"]:
        raise errors.err_ownership()
    for k, v in fields.items():
        debtor[k] = v
    touch(debtor)
    return ok(debtor_json(debtor))


# ---------------------------------------------------------------------------
# Secured parties
# ---------------------------------------------------------------------------

@bp.post("/client-accounts/<client_id>/secured-parties")
def create_secured_party(client_id):
    auth()
    data = body()
    name = req_str(data, "name")
    reference_code = None
    if "reference_code" in data and data["reference_code"] is not None:
        reference_code = as_str(data["reference_code"], "reference_code")
    user_id, role = auth()
    require_role(role, "ClientManager")
    check_client_ownership(role, user_id, client_id)
    _client_or_404(client_id)
    sp = stamp_new({
        "id": new_id(),
        "client_id": client_id,
        "name": name,
        "reference_code": reference_code,
    })
    store.secured_parties[sp["id"]] = sp
    return ok(secured_party_json(sp), 201)


@bp.get("/client-accounts/<client_id>/secured-parties")
def list_secured_parties(client_id):
    user_id, role = auth()
    check_client_ownership(role, user_id, client_id)
    _client_or_404(client_id)
    records = [s for s in store.secured_parties.values() if s["client_id"] == client_id]
    return _paginate(records, secured_party_json)


@bp.get("/secured-parties/<sp_id>")
def get_secured_party(sp_id):
    auth()
    sp = store.secured_parties.get(sp_id)
    if sp is None:
        raise errors.err_not_found("secured_party")
    return ok(secured_party_json(sp))
