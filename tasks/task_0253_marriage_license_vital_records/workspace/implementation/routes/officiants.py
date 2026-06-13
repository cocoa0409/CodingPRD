"""Officiant endpoints (PRD 3.1)."""
from flask import Blueprint

from db import store
from errors import ApiError
from middleware import require_roles
from response import success, success_list
from util import new_common, serialize, parse_dt, touch
from services.common import (
    get_body, require_fields, require_str, require_enum, lookup,
    parse_pagination, sort_by_created,
)
from services.derived import compute_returns_filed_count

bp = Blueprint("officiants", __name__)

CREDENTIAL_TYPES = {"CLERGY", "JUDGE", "NOTARY", "DEPUTY_COMMISSIONER"}


def _officiant_view(off):
    """Serialize officiant with returns_filed_count recomputed for the response."""
    out = serialize(off)
    out["returns_filed_count"] = compute_returns_filed_count(off["id"])
    return out


@bp.route("/officiants", methods=["POST"])
@require_roles("Clerk", "Registrar")
def create_officiant():
    body = get_body()
    require_fields(body, "full_name", "credential_type", "registration_expires_on")
    require_str(body["full_name"], "full_name")
    require_enum(body["credential_type"], CREDENTIAL_TYPES, "credential_type")
    reg_expires = parse_dt(body["registration_expires_on"], "registration_expires_on")

    ent = new_common("officiant")
    ent.update({
        "full_name": body["full_name"],
        "credential_type": body["credential_type"],
        "registration_expires_on": reg_expires,
        "status": "REGISTERED",
        "returns_filed_count": 0,
    })
    store.officiants[ent["id"]] = ent
    return success(_officiant_view(ent), status=201)


@bp.route("/officiants/<officiant_id>", methods=["GET"])
@require_roles("Clerk", "Registrar", "Officiant")
def get_officiant(officiant_id):
    ent = lookup("officiant", officiant_id)
    return success(_officiant_view(ent), status=200)


@bp.route("/officiants/<officiant_id>/suspend", methods=["POST"])
@require_roles("Registrar")
def suspend_officiant(officiant_id):
    ent = lookup("officiant", officiant_id)
    ent["status"] = "SUSPENDED"
    touch(ent)
    return success(_officiant_view(ent), status=200)


@bp.route("/officiants/<officiant_id>/returns", methods=["GET"])
@require_roles("Clerk", "Registrar", "Officiant")
def list_officiant_returns(officiant_id):
    lookup("officiant", officiant_id)
    limit, offset = parse_pagination()
    items = [r for r in store.returns.values() if r["officiant_id"] == officiant_id]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(r) for r in page], limit, offset, total)
