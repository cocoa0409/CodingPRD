"""Client endpoints (PRD 3.1)."""

from flask import Blueprint

import db
from errors import raise_error, ERR_NOT_FOUND
from middleware import require_roles, enforce_client_scope
from response import success
from services.domain import ser_client
from util import get_payload, reject_unknown_fields, require_string, require_int, stamp_new

bp = Blueprint("clients", __name__)


@bp.route("/brand/clients", methods=["POST"])
def create_client():
    user_id, role = require_roles("PlatformAdmin")
    body = get_payload()
    reject_unknown_fields(body, {"name", "industry", "enforcement_budget_cents"})
    name = require_string(body, "name")
    industry = require_string(body, "industry")
    budget = require_int(body, "enforcement_budget_cents", minimum=0)
    client = {
        "name": name,
        "industry": industry,
        "enforcement_budget_cents": budget,
    }
    stamp_new(client)
    db.clients[client["id"]] = client
    return success(ser_client(client), 201)


@bp.route("/brand/clients/<client_id>", methods=["GET"])
def get_client(client_id):
    user_id, role = require_roles(
        "PlatformAdmin", "Paralegal", "AssociateAttorney", "PartnerAttorney", "ClientContact")
    client = db.clients.get(client_id)
    if client is None:
        raise_error(ERR_NOT_FOUND, "Client not found")
    enforce_client_scope(user_id, role, client["id"])
    return success(ser_client(client), 200)
