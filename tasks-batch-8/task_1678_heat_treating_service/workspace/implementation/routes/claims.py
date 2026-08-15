"""LiabilityClaim endpoints."""
from flask import Blueprint

import validation as v
from db import store, touch
from errors import ApiError
from middleware import ANY_ROLES, check_ownership, get_context, require_roles
from response import Paginator, ok
from services import domain

bp = Blueprint("claims", __name__)


@bp.get("/liability-claims")
def list_claims():
    get_context()
    require_roles(ANY_ROLES)
    pg = Paginator()
    rows = list(store.liability_claims.values())
    rows = pg.filter(rows, "customer_id")
    rows = pg.filter(rows, "work_order_id")
    rows = pg.filter(rows, "status")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.get("/liability-claims/<claim_id>")
def get_claim(claim_id):
    get_context()
    require_roles(ANY_ROLES)
    claim = v.resolve_path(store.liability_claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    check_ownership(claim["customer_id"])
    return ok(claim)


@bp.post("/liability-claims/<claim_id>/accept")
def accept_claim(claim_id):
    get_context()
    require_roles(["Customer"])
    claim = v.resolve_path(store.liability_claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    # tier 3: only the owning customer may accept its claim
    check_ownership(claim["customer_id"])
    # tier 5: accept requires PENDING
    if claim["status"] != "PENDING":
        raise ApiError("ERR_CLAIM_NOT_PENDING", 409, "Accept requires claim status PENDING")
    claim["status"] = "ACCEPTED"
    touch(claim)
    return ok(claim)


@bp.post("/liability-claims/<claim_id>/reject")
def reject_claim(claim_id):
    get_context()
    require_roles(["CustomerServiceRep"])
    claim = v.resolve_path(store.liability_claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    # tier 5: reject requires PENDING
    if claim["status"] != "PENDING":
        raise ApiError("ERR_CLAIM_NOT_PENDING", 409, "Reject requires claim status PENDING")
    claim["status"] = "REJECTED"
    touch(claim)
    customer = store.customers.get(claim["customer_id"])
    if customer is not None:
        domain.recompute_exposure(customer)
    return ok(claim)


@bp.post("/liability-claims/<claim_id>/pay")
def pay_claim(claim_id):
    get_context()
    require_roles(["CustomerServiceRep"])
    claim = v.resolve_path(store.liability_claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    # tier 5: pay requires ACCEPTED
    if claim["status"] != "ACCEPTED":
        raise ApiError("ERR_CLAIM_NOT_ACCEPTED", 409, "Pay requires claim status ACCEPTED")
    claim["status"] = "PAID"
    touch(claim)
    customer = store.customers.get(claim["customer_id"])
    if customer is not None:
        domain.recompute_exposure(customer)
    return ok(claim)
