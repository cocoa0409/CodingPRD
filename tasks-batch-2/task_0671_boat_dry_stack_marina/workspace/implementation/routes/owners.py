from flask import Blueprint, request

from db import db
from middleware import require_role
from response import object_response, array_response
from services.common import (
    stamp_create, get_json_body, require_fields, require_string,
    parse_pagination, paginate,
)
from services.lookups import get_marina, get_owner, check_owner_account
from services.serialize import owner_view

owners_bp = Blueprint("owners", __name__)


@owners_bp.route("/marina/owners", methods=["POST"])
def create_owner():
    require_role({"DockMaster", "BillingClerk"})
    body = get_json_body()
    require_fields(body, ["marina_id", "full_name", "email"])
    require_string(body["marina_id"], "marina_id")
    require_string(body["full_name"], "full_name")
    require_string(body["email"], "email")
    with db.lock:
        get_marina(body["marina_id"])
        rec = {
            "marina_id": body["marina_id"],
            "full_name": body["full_name"],
            "email": body["email"],
        }
        stamp_create(rec)
        db.owners[rec["id"]] = rec
    return object_response(owner_view(rec), 201)


@owners_bp.route("/marina/owners/<owner_id>", methods=["GET"])
def fetch_owner(owner_id):
    user_id, role = require_role({"DockMaster", "BillingClerk", "BoatOwner"})
    rec = get_owner(owner_id)
    check_owner_account(rec, user_id, role)
    return object_response(owner_view(rec), 200)


@owners_bp.route("/marina/owners", methods=["GET"])
def list_owners():
    require_role({"DockMaster", "BillingClerk"})
    limit, offset = parse_pagination()
    records = list(db.owners.values())
    marina_id = request.args.get("marina_id")
    if marina_id is not None:
        records = [r for r in records if r["marina_id"] == marina_id]
    page, total = paginate(records, limit, offset)
    return array_response([owner_view(r) for r in page], limit, offset, total)
