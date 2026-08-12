"""Client endpoints."""

from flask import Blueprint, request

import errors
import validation as v
from db import store, new_entity
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list

bp = Blueprint("clients", __name__)


@bp.post("/api/clients")
def create_client():
    require_roles(["IntakeCoordinator"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {"full_name", "date_of_birth", "copay_tier"})
    full_name = v.req_string(body, "full_name")
    date_of_birth = v.req_string(body, "date_of_birth")
    copay_tier = v.opt_enum(body, "copay_tier", {"STANDARD", "LOW_INCOME"}, default="STANDARD")

    client = new_entity()
    client.update({
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "copay_tier": copay_tier,
        "status": "INTAKE",
    })
    store.clients[client["id"]] = client
    return success_object(client, status=201)


@bp.get("/api/clients/<cid>")
def get_client(cid):
    require_roles(ALL_ROLES)
    client = store.clients.get(cid)
    if client is None:
        raise errors.not_found("Client not found")
    return success_object(client)


@bp.get("/api/clients/<cid>/referrals")
def list_client_referrals(cid):
    require_roles(ALL_ROLES)
    client = store.clients.get(cid)
    if client is None:
        raise errors.not_found("Client not found")
    limit, offset = v.parse_pagination(request.args)
    items = v.sort_by_created([r for r in store.referrals.values() if r["client_id"] == cid])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/api/clients/<cid>/outcome-assessments")
def list_client_outcome_assessments(cid):
    require_roles(ALL_ROLES)
    client = store.clients.get(cid)
    if client is None:
        raise errors.not_found("Client not found")
    limit, offset = v.parse_pagination(request.args)
    items = v.sort_by_created([a for a in store.outcome_assessments.values() if a["client_id"] == cid])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)
