from flask import Blueprint, request

from db import db
from middleware import require_role
from response import object_response, array_response
from errors import err, ERR_DUPLICATE_RESOURCE, ERR_INVALID_REQUEST
from services.common import (
    stamp_create, touch, get_json_body, require_fields, require_enum,
    require_string, parse_pagination, paginate,
)
from services.lookups import get_account, check_account_ownership
from services.reconcile import recompute_active_rental_count
from services.serialize import account_view, rental_view

accounts_bp = Blueprint("accounts", __name__)

ACCOUNT_TYPES = {"SUBSCRIBER", "FLEET"}


@accounts_bp.route("/accounts", methods=["POST"])
def create_account():
    # PRD §2.1: opening an account does NOT require auth headers.
    body = get_json_body()
    require_fields(body, ["account_type", "display_name", "email"])
    require_enum(body["account_type"], ACCOUNT_TYPES, "account_type")
    require_string(body["display_name"], "display_name")
    require_string(body["email"], "email")

    rental_cap = body.get("rental_cap", 1)
    if rental_cap is None:
        rental_cap = 1
    if not isinstance(rental_cap, int) or isinstance(rental_cap, bool) or rental_cap < 1:
        raise err(ERR_INVALID_REQUEST, "rental_cap must be an integer >= 1.")

    with db.lock:
        # Email globally unique, case-insensitive.
        new_email = body["email"].lower()
        for a in db.accounts.values():
            if a["email"].lower() == new_email:
                raise err(ERR_DUPLICATE_RESOURCE, "email already exists.")
        rec = {
            "account_type": body["account_type"],
            "display_name": body["display_name"],
            "email": body["email"],
            "rental_cap": rental_cap,
            "wallet_credit_cents": 0,
            "active_rental_count": 0,
            "status": "ACTIVE",
            "_overflow_billed_unpaid_cents": 0,
        }
        stamp_create(rec)
        db.accounts[rec["id"]] = rec
    return object_response(account_view(rec), 201)


@accounts_bp.route("/accounts/<account_id>", methods=["GET"])
def fetch_account(account_id):
    user_id, role = require_role({"OpsAdmin", "Subscriber", "FleetManager"})
    account = get_account(account_id)
    check_account_ownership(account, user_id, role)
    return object_response(account_view(account), 200)


@accounts_bp.route("/accounts/<account_id>/suspend", methods=["POST"])
def suspend_account(account_id):
    require_role({"OpsAdmin"})
    with db.lock:
        account = get_account(account_id)
        account["status"] = "SUSPENDED"
        touch(account)
    return object_response(account_view(account), 200)


@accounts_bp.route("/accounts/<account_id>/rentals", methods=["GET"])
def list_account_rentals(account_id):
    user_id, role = require_role({"OpsAdmin", "Subscriber", "FleetManager"})
    account = get_account(account_id)
    check_account_ownership(account, user_id, role)
    limit, offset = parse_pagination()
    records = [r for r in db.rentals.values() if r["account_id"] == account_id]
    lifecycle_status = request.args.get("lifecycle_status")
    if lifecycle_status:
        records = [r for r in records if r["lifecycle_status"] == lifecycle_status]
    page, total = paginate(records, limit, offset)
    return array_response([rental_view(r) for r in page], limit, offset, total)
