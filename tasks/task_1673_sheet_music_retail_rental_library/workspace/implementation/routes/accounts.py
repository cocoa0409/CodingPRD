"""Customer accounts, credit adjustment (OCC), and standing control (PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_ACCOUNT_STILL_DELINQUENT,
    ERR_FORBIDDEN_ACCOUNT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
)
from middleware import require_auth
from response import success_object
from serializers import ser_account
from services import (
    get_or_404,
    has_overdue_perusals,
    has_overdue_rentals,
    restore_pos_to_approved,
)
from util import is_bool, is_int, is_str, new_record, touch
from routes.helpers import body, coerce_version, paginate, require_fields

bp = Blueprint("accounts", __name__)

STAFF_ROLES = ("LibraryAdmin", "LibraryClerk", "ReturnsClerk", "BillingManager", "RightsAdvisor")
ACCOUNT_KINDS = ("INDIVIDUAL", "SCHOOL", "INSTITUTION")
CREDIT_TIERS = ("PREFERRED", "STANDARD", "PREPAY")


@bp.post("/library/customer-accounts")
def create_account():
    require_auth("LibraryAdmin", "BillingManager")
    data = body()
    require_fields(data, ["account_name", "account_kind"])
    if not is_str(data["account_name"]):
        raise ApiError(ERR_INVALID_REQUEST, 400, "account_name is required")
    if data["account_kind"] not in ACCOUNT_KINDS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid account_kind")
    credit_tier = data.get("credit_tier", "STANDARD")
    if credit_tier not in CREDIT_TIERS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid credit_tier")
    credit_limit = data.get("credit_limit_cents", 0)
    if not is_int(credit_limit) or credit_limit < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "credit_limit_cents must be an integer >= 0")
    requires_po = data.get("requires_purchase_order", False)
    if not is_bool(requires_po):
        raise ApiError(ERR_INVALID_REQUEST, 400, "requires_purchase_order must be a boolean")
    if credit_tier == "PREPAY":
        credit_limit = 0  # PREPAY accounts are forced to zero credit.
    rec = new_record()
    rec.update(
        {
            "account_name": data["account_name"],
            "account_kind": data["account_kind"],
            "credit_tier": credit_tier,
            "credit_limit_cents": credit_limit,
            "standing": "GOOD",
            "requires_purchase_order": requires_po,
        }
    )
    db["customer_accounts"][rec["id"]] = rec
    return success_object(ser_account(rec), status=201)


@bp.get("/library/customer-accounts")
def list_accounts():
    require_auth(*STAFF_ROLES)
    return paginate(list(db["customer_accounts"].values()), ser_account)


@bp.get("/library/customer-accounts/<aid>")
def get_account(aid):
    _, role = require_auth(*STAFF_ROLES, "Customer")
    rec = get_or_404("customer_accounts", aid, ERR_ACCOUNT_NOT_FOUND)
    uid = request.headers.get("X-User-ID")
    if role == "Customer" and uid != aid:
        raise ApiError(ERR_FORBIDDEN_ACCOUNT, 403, "Customer may read only its own account")
    return success_object(ser_account(rec))


@bp.post("/library/customer-accounts/<aid>/credit-adjustments")
def credit_adjustment(aid):
    require_auth("BillingManager")
    rec = get_or_404("customer_accounts", aid, ERR_ACCOUNT_NOT_FOUND)
    data = body()
    # Tier 19 (shape) then tier 20 (OCC).
    require_fields(data, ["new_credit_limit_cents", "expected_customer_account_version"])
    new_limit = data["new_credit_limit_cents"]
    if not is_int(new_limit) or new_limit < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "new_credit_limit_cents must be an integer >= 0")
    expected = coerce_version(data["expected_customer_account_version"], "expected_customer_account_version")
    if expected != rec["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Stale customer account version")
    rec["credit_limit_cents"] = new_limit
    touch(rec)
    return success_object(ser_account(rec))


@bp.post("/library/customer-accounts/<aid>/bar")
def bar_account(aid):
    require_auth("BillingManager")
    rec = get_or_404("customer_accounts", aid, ERR_ACCOUNT_NOT_FOUND)
    if rec["standing"] != "HOLD":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a HOLD account may be barred")
    rec["standing"] = "BARRED"
    touch(rec)
    return success_object(ser_account(rec))


@bp.post("/library/customer-accounts/<aid>/reinstate")
def reinstate_account(aid):
    require_auth("BillingManager")
    rec = get_or_404("customer_accounts", aid, ERR_ACCOUNT_NOT_FOUND)
    if rec["standing"] != "BARRED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a BARRED account may be reinstated")
    if has_overdue_rentals(aid) or has_overdue_perusals(aid):
        raise ApiError(ERR_ACCOUNT_STILL_DELINQUENT, 409, "Overdue rentals or perusals remain")
    rec["standing"] = "GOOD"
    touch(rec)
    restore_pos_to_approved(aid)
    return success_object(ser_account(rec))
