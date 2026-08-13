"""GrowerAccount routes: CRUD, credit state machine, payments, ledger, exposure."""

from flask import Blueprint, g

import db
from errors import not_found, invalid_transition, validation, business, ERR_CREDIT_LIMIT_EXCEEDED
from middleware import require_roles, check_grower_ownership, ALL_ROLES
from response import success_object, success_list
from services.core import (
    scaffold_entity, touch, public, booked_exposure_cents, exposure_balance_cents,
)
from services.orders import apply_payment
from util import get_body, require, reject_unknown, as_string, as_int, parse_pagination, paginate

bp = Blueprint("growers", __name__)


def _get_grower(gid):
    grower = db.growers.get(gid)
    if grower is None:
        raise not_found("Grower not found")
    return grower


@bp.post("/agronomy/growers")
def create_grower():
    require_roles("CreditManager", "BranchAdmin")
    body = get_body()
    reject_unknown(body, {"legal_name", "credit_limit_cents"})
    legal_name = as_string(require(body, "legal_name"), "legal_name")
    credit_limit = as_int(require(body, "credit_limit_cents"), "credit_limit_cents", minimum=0)
    grower = scaffold_entity(db.growers, {
        "legal_name": legal_name,
        "credit_limit_cents": credit_limit,
        "credit_used_cents": 0,
        "prepay_balance_cents": 0,
        "season_closed_tons": 0,
        "credit_status": "ACTIVE",
    })
    return success_object(public(grower), 201)


@bp.get("/agronomy/growers")
def list_growers():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    status_filter = None
    from flask import request
    if "credit_status" in request.args:
        status_filter = request.args["credit_status"]
    items = list(db.growers.values())
    if status_filter is not None:
        items = [x for x in items if x["credit_status"] == status_filter]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/growers/<growerId>")
def get_grower(growerId):
    require_roles(*ALL_ROLES)
    grower = _get_grower(growerId)
    check_grower_ownership(grower["id"])
    return success_object(public(grower))


@bp.patch("/agronomy/growers/<growerId>/credit-terms")
def update_credit_terms(growerId):
    require_roles("CreditManager")
    grower = _get_grower(growerId)
    body = get_body()
    reject_unknown(body, {"credit_limit_cents"})
    grower["credit_limit_cents"] = as_int(require(body, "credit_limit_cents"), "credit_limit_cents", minimum=0)
    touch(grower)
    return success_object(public(grower))


@bp.post("/agronomy/growers/<growerId>/credit-hold")
def credit_hold(growerId):
    require_roles("CreditManager")
    grower = _get_grower(growerId)
    if grower["credit_status"] != "ACTIVE":
        raise invalid_transition("Grower not ACTIVE")
    grower["credit_status"] = "CREDIT_HOLD"
    touch(grower)
    return success_object(public(grower))


@bp.post("/agronomy/growers/<growerId>/suspend")
def suspend(growerId):
    require_roles("CreditManager")
    grower = _get_grower(growerId)
    if grower["credit_status"] not in ("ACTIVE", "CREDIT_HOLD"):
        raise invalid_transition("Grower not in ACTIVE or CREDIT_HOLD")
    grower["credit_status"] = "SUSPENDED"
    touch(grower)
    return success_object(public(grower))


@bp.post("/agronomy/growers/<growerId>/credit-release")
def credit_release(growerId):
    require_roles("CreditManager")
    grower = _get_grower(growerId)
    if grower["credit_status"] not in ("CREDIT_HOLD", "SUSPENDED"):
        raise invalid_transition("Grower not in CREDIT_HOLD or SUSPENDED")
    if grower["credit_used_cents"] > grower["credit_limit_cents"]:
        raise business(ERR_CREDIT_LIMIT_EXCEEDED, 402, "Grower credit used exceeds limit")
    grower["credit_status"] = "ACTIVE"
    touch(grower)
    return success_object(public(grower))


@bp.post("/agronomy/growers/<growerId>/payments")
def post_payment(growerId):
    require_roles("CreditManager")
    grower = _get_grower(growerId)
    body = get_body()
    reject_unknown(body, {"amount_cents"})
    amount = as_int(require(body, "amount_cents"), "amount_cents", minimum=1)
    entry = apply_payment(grower, amount)
    return success_object(public(entry), 201)


@bp.get("/agronomy/growers/<growerId>/credit-ledger")
def credit_ledger(growerId):
    require_roles("Grower", "CreditManager", "BranchAdmin")
    grower = _get_grower(growerId)
    check_grower_ownership(grower["id"])
    limit, offset = parse_pagination()
    items = [e for e in db.ledger_entries.values() if e["grower_id"] == grower["id"]]
    items.sort(key=lambda e: e["_seq"])
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/growers/<growerId>/exposure")
def exposure(growerId):
    require_roles("Grower", "CreditManager", "BranchAdmin")
    grower = _get_grower(growerId)
    check_grower_ownership(grower["id"])
    billed = grower["credit_used_cents"]
    booked = booked_exposure_cents(grower["id"])
    exposure_balance = billed + booked
    return success_object({
        "billed_balance_cents": billed,
        "booked_exposure_cents": booked,
        "exposure_balance_cents": exposure_balance,
        "credit_limit_cents": grower["credit_limit_cents"],
        "available_credit_cents": grower["credit_limit_cents"] - exposure_balance,
    })
