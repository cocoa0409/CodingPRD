"""Seller routes (PRD §3.1).

Seller carries common fields (created_at/updated_at/version). email unique
among sellers. Seller is an entity-backed role: ownership on read is itself.
"""
from flask import Blueprint

import db
import errors
from errors import err
from middleware import require_role, get_json_body, get_identity
from response import object_response
from services.common import serialize, require_string

bp = Blueprint("sellers", __name__)


@bp.route("/sellers", methods=["POST"])
def create_seller():
    require_role({"SaleAdministrator"})
    body = get_json_body()
    legal_name = require_string(body, "legal_name")
    email = require_string(body, "email")
    country_code = require_string(body, "country_code")
    payout_iban = require_string(body, "payout_iban")

    with db.LOCK:
        # email unique among sellers
        for s in db.sellers.values():
            if s["email"] == email:
                raise err(errors.ERR_DUPLICATE, "email already registered for a seller")
        common = db.new_common()
        record = {
            "id": common["id"],
            "created_at": common["created_at"],
            "updated_at": common["updated_at"],
            "version": common["version"],
            "_seq": common["_seq"],
            "legal_name": legal_name,
            "email": email,
            "country_code": country_code,
            "payout_iban": payout_iban,
        }
        db.sellers[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/sellers/<id>", methods=["GET"])
def get_seller(id):
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Seller", "Viewer"})
    with db.LOCK:
        record = db.sellers.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Seller not found")
        # Entity-backed Seller may only read its own record.
        if role == "Seller" and user_id != record["id"]:
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning seller")
        return object_response(serialize(record), 200)
