"""Receipt vault: vault, get, list (PRD §3.7)."""
from flask import Blueprint

import serializers
from db import db, stamp_create
from helpers import (get_json_body, paginate, qarg, require_bool,
                     require_positive_int, require_string)
from lookups import get_account, get_receipt
from middleware import caller, require_role
from response import success

bp = Blueprint("receipts", __name__)


@bp.route("/hsa/receipts", methods=["POST"])
def vault_receipt():
    _, role = caller()
    require_role(role, {"Accountholder", "AccountAdmin"})
    body = get_json_body()
    account_id = require_string(body, "account_id")
    merchant = require_string(body, "merchant")
    service_date = require_string(body, "service_date")
    amount = require_positive_int(body, "amount_cents")
    is_qualified = require_bool(body, "is_qualified_medical", required=True)

    # Referential existence of the named account FK.
    get_account(account_id)

    o = {
        "account_id": account_id,
        "distribution_id": None,
        "merchant": merchant,
        "service_date": service_date,
        "amount_cents": amount,
        "is_qualified_medical": is_qualified,
        "status": "VAULTED",
    }
    stamp_create(o)
    db.receipts[o["id"]] = o
    return success(serializers.receipt(o), status=201)


@bp.route("/hsa/receipts/<receipt_id>", methods=["GET"])
def get_receipt_route(receipt_id):
    _, role = caller()
    require_role(role, {"Accountholder", "AccountAdmin"})
    o = get_receipt(receipt_id)
    return success(serializers.receipt(o), status=200)


@bp.route("/hsa/receipts", methods=["GET"])
def list_receipts():
    _, role = caller()
    require_role(role, {"Accountholder", "AccountAdmin"})
    account_id = qarg("account_id")
    distribution_id = qarg("distribution_id")
    status_filter = qarg("status")
    items = [
        r for r in db.receipts.values()
        if (account_id is None or r["account_id"] == account_id)
        and (distribution_id is None or r["distribution_id"] == distribution_id)
        and (status_filter is None or r["status"] == status_filter)
    ]
    page, meta = paginate(items)
    return success([serializers.receipt(r) for r in page], status=200, pagination=meta)
