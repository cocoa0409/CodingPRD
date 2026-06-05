"""Address routes."""
from flask import Blueprint, request

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import (get_json_body, require_resource, require_fields,
                     parse_pagination, paginate, ownership_customer)
from response import success, list_success
from constants import HOME_SIZES

bp = Blueprint("addresses", __name__)


@bp.route("/cleaning/addresses", methods=["POST"])
def create_address():
    principal = authenticate()
    authorize(principal, {"Customer"})
    body = get_json_body()
    require_fields(body, ["customer_id", "line1", "postal_code", "home_size"])
    customer = require_resource(db.customers, body["customer_id"], "customer")
    ownership_customer(principal, customer["id"])
    home_size = body["home_size"]
    if home_size not in HOME_SIZES:
        raise err("ERR_INVALID_REQUEST", "invalid home_size")
    if not isinstance(body["line1"], str) or body["line1"] == "":
        raise err("ERR_INVALID_REQUEST", "line1 must be a non-empty string")
    if not isinstance(body["postal_code"], str) or body["postal_code"] == "":
        raise err("ERR_INVALID_REQUEST", "postal_code must be a non-empty string")
    rec = {
        "customer_id": customer["id"],
        "line1": body["line1"],
        "postal_code": body["postal_code"],
        "home_size": home_size,
        "archived": False,
    }
    db.insert(db.addresses, rec)
    return success(S.address(rec), status=201)


@bp.route("/cleaning/addresses/<aid>", methods=["GET"])
def get_address(aid):
    principal = authenticate()
    authorize(principal, {"Customer", "PlatformAdmin"})
    rec = require_resource(db.addresses, aid, "address")
    ownership_customer(principal, rec["customer_id"])
    return success(S.address(rec), status=200)


@bp.route("/cleaning/addresses", methods=["GET"])
def list_addresses():
    principal = authenticate()
    authorize(principal, {"Customer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    include_archived = request.args.get("include_archived", "false").lower() == "true"

    records = list(db.addresses.values())
    if customer_id is not None:
        records = [r for r in records if r["customer_id"] == customer_id]
    if principal.role == "Customer":
        records = [r for r in records if r["customer_id"] == principal.user_id]
    if not include_archived:
        records = [r for r in records if not r.get("archived")]

    page, total = paginate(records, limit, offset)
    return list_success([S.address(r) for r in page], limit, offset, total)


@bp.route("/cleaning/addresses/<aid>/archive", methods=["POST"])
def archive_address(aid):
    principal = authenticate()
    authorize(principal, {"Customer"})
    rec = require_resource(db.addresses, aid, "address")
    ownership_customer(principal, rec["customer_id"])
    rec["archived"] = True
    db.touch(rec)
    return success(S.address(rec), status=200)
