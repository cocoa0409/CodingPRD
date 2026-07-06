"""Client endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import db
from middleware import authenticate
from errors import err, ERR_INVALID_STATE, ERR_NOT_FOUND
from helpers import (
    require_role, get_json_body, require_fields, as_string, get_studio,
    get_or_404, parse_pagination, paginate, require_client_owns_client,
)
from response import success, success_list
from serialize import view

bp = Blueprint("clients", __name__)


def _resolve_client(studio_id, client_id):
    rec = get_or_404(db.clients, client_id, "Client not found")
    if rec["studio_id"] != studio_id:
        raise err(ERR_NOT_FOUND, "Client not found in this studio")
    return rec


@bp.route("/studios/<studio_id>/clients", methods=["POST"])
def create_client(studio_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    get_studio(studio_id)
    body = get_json_body()
    require_fields(body, "company_name", "contact_email")
    company_name = as_string(body["company_name"], "company_name")
    contact_email = as_string(body["contact_email"], "contact_email")

    rec = db.create(db.clients, {
        "studio_id": studio_id,
        "company_name": company_name,
        "contact_email": contact_email,
        "status": "ACTIVE",
    })
    return success(view(rec), status=201)


@bp.route("/studios/<studio_id>/clients/<client_id>", methods=["GET"])
def get_client(studio_id, client_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps", "Client")
    get_studio(studio_id)
    rec = _resolve_client(studio_id, client_id)
    require_client_owns_client(caller, rec)
    return success(view(rec), status=200)


@bp.route("/studios/<studio_id>/clients", methods=["GET"])
def list_clients(studio_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps")
    get_studio(studio_id)
    limit, offset = parse_pagination()

    filter_studio = request.args.get("studio_id")
    records = [c for c in db.clients.values() if c["studio_id"] == studio_id]
    if filter_studio is not None:
        records = [c for c in records if c["studio_id"] == filter_studio]

    window, total = paginate(records, limit, offset)
    return success_list([view(r) for r in window], limit, offset, total)


@bp.route("/studios/<studio_id>/clients/<client_id>/archive", methods=["POST"])
def archive_client(studio_id, client_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    get_studio(studio_id)
    rec = _resolve_client(studio_id, client_id)
    # ACTIVE -> ARCHIVED (PRD §3.1). Any other current state has no defined
    # transition.
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Client is not ACTIVE")
    rec["status"] = "ARCHIVED"
    db.touch(rec)
    return success(view(rec), status=200)
