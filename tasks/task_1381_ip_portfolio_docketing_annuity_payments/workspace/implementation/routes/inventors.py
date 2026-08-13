"""Inventor routes (PRD §3.8)."""

from flask import Blueprint

import db as dbmod
import serialize
from middleware import require_roles, get_json_body, parse_pagination, ALL_ROLES
from response import success_object, success_list
from services.common import (
    new_id, stamp_new, get_client, get_inventor, check_allowed_fields, req_str,
)

bp = Blueprint("inventors", __name__)


@bp.post("/clients/<client_id>/inventors")
def create_inventor(client_id):
    require_roles(["RecordsSpecialist"])
    client = get_client(client_id)
    body = get_json_body()
    check_allowed_fields(body, {"full_name", "email"})
    rec = stamp_new({
        "id": new_id(),
        "client_id": client["id"],
        "full_name": req_str(body, "full_name"),
        "email": req_str(body, "email"),
    })
    dbmod.DB["inventors"][rec["id"]] = rec
    return success_object(serialize.inventor(rec), 201)


@bp.get("/clients/<client_id>/inventors")
def list_client_inventors(client_id):
    require_roles(ALL_ROLES)
    client = get_client(client_id)
    limit, offset = parse_pagination()
    items = [
        inv for inv in dbmod.DB["inventors"].values() if inv["client_id"] == client["id"]
    ]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize.inventor(r) for r in page], total, limit, offset)


@bp.get("/inventors/<inventor_id>")
def get_inventor_route(inventor_id):
    require_roles(ALL_ROLES)
    return success_object(serialize.inventor(get_inventor(inventor_id)))


@bp.get("/inventors/<inventor_id>/assignments")
def list_inventor_assignments(inventor_id):
    require_roles(ALL_ROLES)
    inventor = get_inventor(inventor_id)
    limit, offset = parse_pagination()
    items = [
        a for a in dbmod.DB["assignments"].values() if inventor["id"] in a["inventor_ids"]
    ]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize.assignment(r) for r in page], total, limit, offset)
