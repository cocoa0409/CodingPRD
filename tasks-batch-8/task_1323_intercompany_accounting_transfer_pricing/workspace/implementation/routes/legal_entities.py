"""LegalEntity resource (PRD 3.1)."""
from flask import Blueprint

import errors
from db import store, new_resource, touch, public
from errors import ApiError
from middleware import require_auth, get_body, get_path, shape_str, ALL_ROLES
from response import ok_object

bp = Blueprint("legal_entities", __name__)

_ADMIN = ["GroupTaxAdmin"]


@bp.post("/tp/legal_entities")
def create_legal_entity():
    require_auth(_ADMIN)
    body = get_body()
    name = shape_str(body, "name")
    country = shape_str(body, "country_code")
    currency = shape_str(body, "functional_currency")
    le = new_resource()
    le.update({
        "name": name,
        "country_code": country,
        "functional_currency": currency,
        "status": "ACTIVE",
    })
    store.legal_entities[le["id"]] = le
    return ok_object(public(le), 201)


@bp.get("/tp/legal_entities/<legalEntityId>")
def get_legal_entity(legalEntityId):
    require_auth(ALL_ROLES)
    le = get_path(store.legal_entities, legalEntityId)
    return ok_object(public(le), 200)


@bp.post("/tp/legal_entities/<legalEntityId>/deactivate")
def deactivate_legal_entity(legalEntityId):
    require_auth(_ADMIN)
    le = get_path(store.legal_entities, legalEntityId)
    if le["status"] != "ACTIVE":
        raise ApiError(errors.INVALID_STATE, 409,
                       "deactivate requires the entity to be ACTIVE")
    # DRAFT agreements do not block; ACTIVE / UNDER_AMENDMENT do.
    for a in store.agreements.values():
        if a["status"] in ("ACTIVE", "UNDER_AMENDMENT") and (
                a["provider_entity_id"] == le["id"]
                or a["recipient_entity_id"] == le["id"]):
            raise ApiError(errors.ENTITY_HAS_ACTIVE_AGREEMENTS, 409,
                           "Entity is referenced by a live intercompany agreement")
    le["status"] = "INACTIVE"
    touch(le)
    return ok_object(public(le), 200)
