"""Client endpoints."""
from flask import Blueprint

import errors
from db import db, base_fields, public
from middleware import get_identity, require_role
from response import success, list_success
from validation import (get_json_body, require_str, require_enum,
                        parse_pagination, paginate)

bp = Blueprint("clients", __name__)

ACCOUNT_TYPES = {"COMMERCIAL", "HOA", "EVENT"}


@bp.post("/clients")
def create_client():
    _, role = get_identity()
    require_role(role, ["AccountManager"])
    body = get_json_body()
    legal_name = require_str(body, "legal_name")
    account_type = require_enum(body, "account_type", ACCOUNT_TYPES)
    contact_email = require_str(body, "contact_email")
    site_address = require_str(body, "site_address")

    rec = base_fields()
    rec.update({
        "legal_name": legal_name,
        "account_type": account_type,
        "contact_email": contact_email,
        "site_address": site_address,
        "status": "ACTIVE",
    })
    db.clients[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/clients/<id>")
def get_client(id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "ClientContact", "PlatformAdmin"])
    rec = db.clients.get(id)
    if rec is None:
        raise errors.not_found()
    return success(public(rec))


@bp.get("/clients")
def list_clients():
    _, role = get_identity()
    require_role(role, ["AccountManager", "PlatformAdmin"])
    limit, offset = parse_pagination()
    account_type = None
    from flask import request
    account_type = request.args.get("account_type")
    records = list(db.clients.values())
    if account_type is not None:
        records = [r for r in records if r["account_type"] == account_type]
    page, total = paginate(records, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)
