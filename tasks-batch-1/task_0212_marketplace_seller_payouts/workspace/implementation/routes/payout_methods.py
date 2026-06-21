"""Payout method endpoints (PRD §3.3)."""
import random

from flask import Blueprint, request

from common import (
    parse_pagination, paginate, sort_by_created, get_json_body,
    require_fields, require_enum, err,
)
from errors import (
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_BAD_MICRO_DEPOSIT_CODE,
)
from db import db
from middleware import (
    get_identity, require_roles, ROLE_SELLER, ROLE_REVIEWER, ROLE_FINANCE,
)
from response import success
from routes.helpers import fetch, ensure_seller_owns
from services.entity import stamp_create, touch
from services.seller import recompute_account_status, open_initial_reserve

bp = Blueprint("payout_methods", __name__)

METHOD_TYPES = {"ACH", "WIRE", "PAYPAL"}
CURRENCIES = {"USD", "CAD", "GBP", "EUR"}


def _issue_code():
    return "".join(random.choices("0123456789", k=6))


def recompute_is_default(seller_id):
    """is_default is true for exactly one VERIFIED method — the latest VERIFIED
    by created_at ascending, last wins (PRD §3.3)."""
    verified = [
        m for m in db.payout_methods.values()
        if m["seller_id"] == seller_id and m["verification_status"] == "VERIFIED"
    ]
    for m in db.payout_methods.values():
        if m["seller_id"] == seller_id:
            m["is_default"] = False
    if verified:
        latest = sorted(verified, key=lambda m: (m["created_at"], m["id"]))[-1]
        latest["is_default"] = True


@bp.post("/payout-methods")
def create_payout_method():
    user_id, role = get_identity()
    require_roles(role, [ROLE_SELLER])
    body = get_json_body()
    require_fields(body, ["seller_id", "method_type", "account_last4", "currency"])
    seller_id = body["seller_id"]
    method_type = body["method_type"]
    account_last4 = body["account_last4"]
    currency = body["currency"]
    require_enum(method_type, METHOD_TYPES, "method_type")
    require_enum(currency, CURRENCIES, "currency")
    if not (isinstance(account_last4, str) and account_last4.isdigit()
            and len(account_last4) == 4):
        raise err(ERR_INVALID_REQUEST, "account_last4 must be exactly 4 digits.")
    seller = fetch(db.sellers, seller_id)
    ensure_seller_owns(role, user_id, seller["id"])

    method = {
        "seller_id": seller_id,
        "method_type": method_type,
        "account_last4": account_last4,
        "currency": currency,
        "verification_status": "UNVERIFIED",
        "micro_deposit_code": _issue_code(),
        "is_default": False,
        # internal counter for failed verify attempts (not part of the schema)
        "_failed_attempts": 0,
    }
    stamp_create(method)
    db.payout_methods[method["id"]] = method
    return success(_serialize(method), status=201)


def _serialize(method):
    return {k: v for k, v in method.items() if not k.startswith("_")}


@bp.get("/payout-methods/<method_id>")
def get_payout_method(method_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_SELLER, ROLE_REVIEWER, ROLE_FINANCE])
    method = fetch(db.payout_methods, method_id)
    ensure_seller_owns(role, user_id, method["seller_id"])
    return success(_serialize(method))


@bp.get("/payout-methods")
def list_payout_methods():
    user_id, role = get_identity()
    require_roles(role, [ROLE_SELLER, ROLE_REVIEWER, ROLE_FINANCE])
    limit, offset = parse_pagination()
    seller_id = request.args.get("seller_id")
    verification_status = request.args.get("verification_status")
    items = list(db.payout_methods.values())
    if role == ROLE_SELLER:
        items = [m for m in items if m["seller_id"] == user_id]
    if seller_id is not None:
        items = [m for m in items if m["seller_id"] == seller_id]
    if verification_status is not None:
        items = [m for m in items if m["verification_status"] == verification_status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([_serialize(m) for m in page], pagination=meta)


@bp.post("/payout-methods/<method_id>/verify")
def verify_payout_method(method_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_SELLER])
    method = fetch(db.payout_methods, method_id)
    ensure_seller_owns(role, user_id, method["seller_id"])
    body = get_json_body()
    require_fields(body, ["micro_deposit_code"])
    submitted = body["micro_deposit_code"]

    # State guard: only an UNVERIFIED method can be verified (PRD §3.3).
    if method["verification_status"] != "UNVERIFIED":
        raise err(ERR_INVALID_STATE, "Only an UNVERIFIED method can be verified.")

    if submitted == method["micro_deposit_code"]:
        method["verification_status"] = "VERIFIED"
        touch(method)
        recompute_is_default(method["seller_id"])
        seller = db.sellers.get(method["seller_id"])
        if seller is not None:
            activated = recompute_account_status(seller)
            if activated:
                open_initial_reserve(seller)
            touch(seller)
        return success(_serialize(method))

    # Non-matching code: third failure (2 prior) moves to FAILED (PRD §3.3).
    if method["_failed_attempts"] >= 2:
        method["verification_status"] = "FAILED"
        method["_failed_attempts"] += 1
        touch(method)
    else:
        method["_failed_attempts"] += 1
    raise err(ERR_BAD_MICRO_DEPOSIT_CODE, "micro_deposit_code does not match.")
