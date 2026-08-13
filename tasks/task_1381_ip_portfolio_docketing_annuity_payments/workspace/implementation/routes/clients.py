"""Client, ClientContact routes and the computed client risk score (PRD §3.1, §3.9)."""

from flask import Blueprint

import db as dbmod
import serialize
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import require_roles, get_json_body, parse_pagination, query_param, ALL_ROLES
from response import success_object, success_list
from services.common import (
    new_id, stamp_new, bump, get_client, get_contact,
    check_allowed_fields, req_str, opt_str, ensure_transition,
)
from services import calc

bp = Blueprint("clients", __name__)


# --- Client ----------------------------------------------------------------------

@bp.post("/clients")
def create_client():
    require_roles(["PlatformAdmin"])
    body = get_json_body()
    check_allowed_fields(body, {"display_name", "default_currency"})
    rec = stamp_new({
        "id": new_id(),
        "display_name": req_str(body, "display_name"),
        "default_currency": opt_str(body, "default_currency", "USD"),
        "status": "ACTIVE",
    })
    dbmod.DB["clients"][rec["id"]] = rec
    return success_object(serialize.client(rec), 201)


@bp.get("/clients")
def list_clients():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    items = sorted(dbmod.DB["clients"].values(), key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize.client(r) for r in page], total, limit, offset)


@bp.get("/clients/<client_id>")
def get_client_route(client_id):
    require_roles(ALL_ROLES)
    return success_object(serialize.client(get_client(client_id)))


@bp.post("/clients/<client_id>/suspend")
def suspend_client(client_id):
    require_roles(["PlatformAdmin"])
    rec = get_client(client_id)
    ensure_transition(rec, {"ACTIVE"}, "clients", "Client")
    rec["status"] = "SUSPENDED"
    bump(rec)
    return success_object(serialize.client(rec))


@bp.post("/clients/<client_id>/reactivate")
def reactivate_client(client_id):
    require_roles(["PlatformAdmin"])
    rec = get_client(client_id)
    ensure_transition(rec, {"SUSPENDED"}, "clients", "Client")
    rec["status"] = "ACTIVE"
    bump(rec)
    return success_object(serialize.client(rec))


@bp.get("/clients/<client_id>/risk-score")
def client_risk_score(client_id):
    require_roles(ALL_ROLES)
    rec = get_client(client_id)
    variant = query_param("variant")
    if variant not in ("STATUTORY_ONLY", "ALL_DEADLINES"):
        raise_err(ERR_INVALID_REQUEST, "variant must be one of STATUTORY_ONLY, ALL_DEADLINES")
    total, tier, per_family = calc.client_risk_score(rec, variant, dbmod.current_date())
    return success_object({
        "variant": variant,
        "score": calc.present_score(total),
        "tier": tier,
        "per_family": per_family,
    })


# --- ClientContact -----------------------------------------------------------------

@bp.post("/clients/<client_id>/contacts")
def create_contact(client_id):
    require_roles(["PlatformAdmin"])
    client = get_client(client_id)
    body = get_json_body()
    check_allowed_fields(body, {"full_name", "email"})
    rec = stamp_new({
        "id": new_id(),
        "client_id": client["id"],
        "full_name": req_str(body, "full_name"),
        "email": req_str(body, "email"),
    })
    dbmod.DB["contacts"][rec["id"]] = rec
    return success_object(serialize.contact(rec), 201)


@bp.get("/clients/<client_id>/contacts")
def list_client_contacts(client_id):
    require_roles(ALL_ROLES)
    client = get_client(client_id)
    limit, offset = parse_pagination()
    items = [
        c for c in dbmod.DB["contacts"].values() if c["client_id"] == client["id"]
    ]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize.contact(r) for r in page], total, limit, offset)


@bp.get("/contacts/<contact_id>")
def get_contact_route(contact_id):
    require_roles(ALL_ROLES)
    return success_object(serialize.contact(get_contact(contact_id)))
