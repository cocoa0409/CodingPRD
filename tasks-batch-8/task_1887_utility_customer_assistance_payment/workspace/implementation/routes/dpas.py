"""DeferredPaymentAgreement endpoints (PRD §3.4) + forgiveness-credit listing."""

from flask import Blueprint

import db
from errors import (not_found, ApiError, ERR_STALE_ACCOUNT_VERSION,
                    ERR_INVALID_STATE, ERR_OPEN_DPA_EXISTS,
                    ERR_ARREARAGE_BELOW_MINIMUM, ERR_DPA_NOT_REINSTATABLE,
                    ERR_CURE_WINDOW_EXPIRED)
from middleware import authenticate, check_ownership
from response import success_object, success_list
from serializers import dpa as ser_dpa, forgiveness_credit as ser_credit
from services.common import (touch_account, non_terminal_dpa,
                             due_installment_count, CURE_WINDOW_DAYS)
from services.dpa_ops import create_dpa, reverse_posted_credits, recompute_dpa_derived
from services.dpa_terms import MIN_ARREARAGE_CENTS
from validate import (get_body, validate_shape, parse_pagination, parse_filters,
                      paginate, sort_by_creation)

bp = Blueprint("dpas", __name__)

DPA_STATUSES = {"DRAFT", "ACTIVE", "DEFAULTED", "COMPLETED", "BROKEN", "CANCELLED"}
CREDIT_STATUSES = {"POSTED", "REVERSED"}
GET_ROLES = ["Customer", "CustomerServiceRep", "ProgramAdmin"]
LIST_ROLES = ["CustomerServiceRep", "ProgramAdmin"]


def get_dpa_or_404(dpa_id):
    d = db.dpas.get(dpa_id)
    if d is None:
        raise not_found("DPA not found")
    return d


@bp.route("/assistance/dpas", methods=["POST"])
def create():
    actor = authenticate(["Customer", "CustomerServiceRep"])
    raw = get_body(allow_empty=False)
    if actor.is_customer and isinstance(raw.get("account_id"), str):
        check_ownership(actor, raw.get("account_id"))
    body = validate_shape(raw, [
        ("account_id", "string", True, None),
        ("installment_count", "int", True, (2, 12)),
        ("expected_account_version", "int", True, None),
    ])
    if actor.is_customer:
        check_ownership(actor, body["account_id"])
    account = db.accounts.get(body["account_id"])
    if account is None:
        raise not_found("Account not found")
    # guards in PRD §3.4 order: stale version -> one-active -> fiscal floor
    if body["expected_account_version"] != account["version"]:
        raise ApiError(ERR_STALE_ACCOUNT_VERSION, 412,
                       "expected_account_version does not match current version")
    existing = non_terminal_dpa(account["id"])
    if existing is not None and existing["status"] in ("ACTIVE", "DEFAULTED"):
        raise ApiError(ERR_OPEN_DPA_EXISTS, 422,
                       "An ACTIVE or DEFAULTED DPA already occupies the account")
    if account["arrearage_balance_cents"] < MIN_ARREARAGE_CENTS:
        raise ApiError(ERR_ARREARAGE_BELOW_MINIMUM, 422,
                       "DPA creation requires arrearage_balance_cents >= 10000")
    dpa = create_dpa(account, body["installment_count"])
    touch_account(account)
    return success_object(ser_dpa(dpa), status=201)


@bp.route("/assistance/dpas/<dpa_id>", methods=["GET"])
def get_dpa(dpa_id):
    actor = authenticate(GET_ROLES)
    d = db.dpas.get(dpa_id)
    if d is not None:
        check_ownership(actor, d["account_id"])
    if d is None:
        raise not_found("DPA not found")
    return success_object(ser_dpa(d))


@bp.route("/assistance/dpas", methods=["GET"])
def list_dpas():
    authenticate(LIST_ROLES)
    limit, offset = parse_pagination()
    filters = parse_filters({"account_id": "str", "status": DPA_STATUSES})
    items = sort_by_creation(db.dpas.values())
    if "account_id" in filters:
        items = [x for x in items if x["account_id"] == filters["account_id"]]
    if "status" in filters:
        items = [x for x in items if x["status"] == filters["status"]]
    page, total = paginate(items, limit, offset)
    return success_list([ser_dpa(x) for x in page], limit, offset, total)


@bp.route("/assistance/dpas/<dpa_id>/cancel", methods=["POST"])
def cancel(dpa_id):
    authenticate(["CustomerServiceRep", "ProgramAdmin"])
    d = get_dpa_or_404(dpa_id)
    if d["status"] not in ("DRAFT", "ACTIVE", "DEFAULTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Cancel requires a non-terminal DPA")
    account = db.accounts.get(d["account_id"])
    if account is not None:
        reverse_posted_credits(d, account)
        touch_account(account)
    else:
        recompute_dpa_derived(d)
    d["status"] = "CANCELLED"
    db.touch(d)
    return success_object(ser_dpa(d))


@bp.route("/assistance/dpas/<dpa_id>/reinstate", methods=["POST"])
def reinstate(dpa_id):
    authenticate(["CustomerServiceRep"])
    d = get_dpa_or_404(dpa_id)
    if d["status"] != "DEFAULTED":
        raise ApiError(ERR_DPA_NOT_REINSTATABLE, 409,
                       "Reinstate requires DPA status DEFAULTED")
    if db.CLOCK.date() > db.add_days(d["defaulted_on"], CURE_WINDOW_DAYS):
        raise ApiError(ERR_CURE_WINDOW_EXPIRED, 422,
                       "Cure window (defaulted_on + 15 days) has expired")
    if d["installments_settled_count"] < due_installment_count(d):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "All due installments must be settled to reinstate")
    d["status"] = "ACTIVE"
    d["defaulted_on"] = None
    db.touch(d)
    return success_object(ser_dpa(d))


@bp.route("/assistance/dpas/<dpa_id>/forgiveness-credits", methods=["GET"])
def list_credits(dpa_id):
    actor = authenticate(GET_ROLES)
    d = db.dpas.get(dpa_id)
    if d is not None:
        check_ownership(actor, d["account_id"])
    if d is None:
        raise not_found("DPA not found")
    limit, offset = parse_pagination()
    filters = parse_filters({"status": CREDIT_STATUSES})
    items = [c for c in sort_by_creation(db.forgiveness_credits.values())
             if c["dpa_id"] == d["id"]]
    if "status" in filters:
        items = [c for c in items if c["status"] == filters["status"]]
    page, total = paginate(items, limit, offset)
    return success_list([ser_credit(c) for c in page], limit, offset, total)
