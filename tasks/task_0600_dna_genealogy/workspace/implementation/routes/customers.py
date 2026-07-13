"""Customer registration, reads and operator credit adjustments (PRD §3.1)."""
from flask import Blueprint

import db
import services as S
from auth import endpoint, require_owner
from errors import ApiError
from response import ok
from routes.common import body, require_int, require_string

bp = Blueprint("customers", __name__)


@bp.post("/dna/customers")
@endpoint(["PlatformAdmin"])
def create_customer():
    payload = body()
    S.require_fields(payload, ["email", "display_name"])
    email = require_string(payload["email"], "email")
    display_name = require_string(payload["display_name"], "display_name")

    for existing in db.db.customers.values():
        if existing["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", "email must be unique across customers.")

    customer = db.new_record(
        {
            "email": email,
            "display_name": display_name,
            "account_status": "ACTIVE",
            "dna_status": "NO_SAMPLE",
            "wallet_credit_cents": 0,
            "visible_match_count": 0,
        }
    )
    db.db.customers[customer["id"]] = customer
    return ok(S.customer_json(customer), 201)


@bp.get("/dna/customers/<customer_id>")
@endpoint(["Customer", "PlatformAdmin", "PrivacyOfficer"])
def read_customer(customer_id):
    customer = S.get("customers", customer_id)
    require_owner(customer["id"])
    return ok(S.customer_json(customer))


@bp.post("/dna/customers/<customer_id>/credits")
@endpoint(["PlatformAdmin"])
def top_up(customer_id):
    customer = S.get("customers", customer_id)
    payload = body()
    S.require_fields(payload, ["amount_cents"])
    amount = require_int(payload["amount_cents"], "amount_cents", exclusive_min=0)

    S.require_not_purged(customer)

    customer["wallet_credit_cents"] = customer["wallet_credit_cents"] + amount
    db.touch(customer)
    return ok(S.customer_json(customer))
