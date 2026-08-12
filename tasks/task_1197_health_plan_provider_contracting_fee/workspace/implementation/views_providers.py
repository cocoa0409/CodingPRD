"""Providers and contract creation under a provider."""

from flask import request

from flask import Blueprint

import store
from bodycheck import BOOL, DATE, ENUM, INT, STR, validate_body
from envelope import ok, ok_list
from errors import ApiError
from helpers import get_network, get_provider, sorted_by_created
from security import (
    ALL_ROLES, ROLE_CONTRACT_MANAGER, ROLE_PLAN_ADMIN,
    auth, check_ownership, require_roles,
)

bp = Blueprint("providers", __name__)


@bp.post("/providers")
def create_provider():
    data = validate_body({
        "legal_name": (STR, True),
        "tin": (STR, True),
        "npi": (STR, True),
        "locality_code": (STR, True),
    })
    _, role = auth()
    require_roles(role, [ROLE_PLAN_ADMIN])
    for p in store.providers.values():
        if p["tin"] == data["tin"] or p["npi"] == data["npi"]:
            raise ApiError(
                "ERR_DUPLICATE_PROVIDER", 409,
                "A provider with this tin or npi already exists.",
            )
    provider = store.stamp_new({
        "legal_name": data["legal_name"],
        "tin": data["tin"],
        "npi": data["npi"],
        "locality_code": data["locality_code"],
        "provider_status": "ACTIVE",
    })
    store.providers[provider["id"]] = provider
    return ok(dict(provider), 201)


@bp.get("/providers")
def list_providers():
    _, role = auth()
    require_roles(role, ALL_ROLES)
    locality = request.args.get("locality_code")
    items = store.providers.values()
    if locality is not None:
        items = [p for p in items if p["locality_code"] == locality]
    return ok_list([dict(p) for p in sorted_by_created(items)])


@bp.get("/providers/<pid>")
def get_one_provider(pid):
    user_id, role = auth()
    require_roles(role, ALL_ROLES)
    provider = get_provider(pid)
    check_ownership(role, user_id, provider["id"])
    return ok(dict(provider))


@bp.post("/providers/<pid>/contracts")
def create_contract(pid):
    data = validate_body({
        "network_id": (STR, True),
        "base_effective_date": (DATE, True),
        "term_months": (INT, True),
        "escalator_bps": (INT, True),
        "escalator_mode": (ENUM("ANNIVERSARY", "CALENDAR"), True),
        "auto_renew": (BOOL, False),
    })
    user_id, role = auth()
    require_roles(role, [ROLE_CONTRACT_MANAGER])
    provider = get_provider(pid)
    network = get_network(data["network_id"])
    if network["network_status"] != "ACTIVE":
        raise ApiError(
            "ERR_NETWORK_INACTIVE", 422,
            "Referenced network is not ACTIVE.",
        )
    contract = store.stamp_new({
        "provider_id": provider["id"],
        "network_id": network["id"],
        "base_effective_date": data["base_effective_date"],
        "term_months": data["term_months"],
        "escalator_bps": data["escalator_bps"],
        "escalator_mode": data["escalator_mode"],
        "auto_renew": data["auto_renew"] if data["auto_renew"] is not None else False,
        "contract_status": "DRAFT",
        "negotiation_round": 0,
        "submitted_by_user_id": None,
        "signed_by_user_id": None,
    })
    store.contracts[contract["id"]] = contract
    store.add_audit(contract["id"], "CONTRACT_CREATED", role, user_id,
                    "Contract created in DRAFT.")
    return ok(dict(contract), 201)


@bp.get("/providers/<pid>/contracts")
def list_provider_contracts(pid):
    user_id, role = auth()
    require_roles(role, ALL_ROLES)
    provider = get_provider(pid)
    check_ownership(role, user_id, provider["id"])
    items = [c for c in store.contracts.values() if c["provider_id"] == pid]
    return ok_list([dict(c) for c in sorted_by_created(items)])
