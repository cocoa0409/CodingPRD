from flask import Blueprint, request

import db
import validate
import serialize
from response import ok_object, ok_array
from middleware import require
from services import lookup

bp = Blueprint("trust_deposits", __name__)


@bp.get("/trust-deposits/<deposit_id>")
@require("Admin", "TrustOfficer")
def get_trust_deposit(deposit_id):
    dep = lookup.trust_deposit(deposit_id)
    return ok_object(serialize.trust_deposit(dep), 200)


@bp.get("/trust-deposits")
@require("Admin", "TrustOfficer")
def list_trust_deposits():
    limit, offset = validate.pagination()
    contract_id = request.args.get("contract_id")
    items = list(db.trust_deposits.values())
    if contract_id is not None:
        items = [d for d in items if d["contract_id"] == contract_id]
    window, total = validate.paginate(items, limit, offset)
    return ok_array([serialize.trust_deposit(d) for d in window], limit, offset, total)
