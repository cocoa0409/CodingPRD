"""340B chargeback claims (PRD §3.7).

computed_amount_cents is computed at submission and recomputed at validation;
claimed must equal computed exactly at validation.
"""
from flask import Blueprint

import db
import errors
from db import store
from errors import ApiError
from middleware import endpoint, ALL_ROLES
from response import ok, created, Paginator
from services import pricing as pricing_service
from validation import get_body, req_int, body_fk, path_entity

bp = Blueprint("chargebacks", __name__)


def _claim(claim_id):
    return path_entity(store.chargeback_claims, claim_id, "ChargebackClaim")


@bp.route("/wholesale/chargeback-claims", methods=["POST"])
@endpoint(["ContractAdministrator"])
def create_claim():
    body = get_body()
    order = body_fk(body, "order_id", store.purchase_orders, "PurchaseOrder")
    claimed = req_int(body, "claimed_amount_cents")
    if claimed <= 0:
        raise ApiError(errors.ERR_INVALID_REQUEST[0], errors.ERR_INVALID_REQUEST[1],
                       "claimed_amount_cents must be strictly positive")
    if not order.get("is_340b_order"):
        raise ApiError(errors.ERR_NOT_340B_ORDER[0], errors.ERR_NOT_340B_ORDER[1],
                       "Chargeback claim references an order with is_340b_order == false")
    claim = {
        "id": db.new_id(),
        "order_id": order["id"],
        "claimed_amount_cents": claimed,
        "computed_amount_cents": pricing_service.compute_chargeback_amount(order),
        "claim_status": "SUBMITTED",
    }
    db.new_common(claim)
    store.chargeback_claims[claim["id"]] = claim
    return created(claim)


@bp.route("/wholesale/chargeback-claims", methods=["GET"])
@endpoint(ALL_ROLES)
def list_claims():
    pg = Paginator()
    rows = list(store.chargeback_claims.values())
    rows = pg.filter(rows, "order_id")
    rows = pg.filter(rows, "claim_status")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.route("/wholesale/chargeback-claims/<claimId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_claim(claimId):
    return ok(_claim(claimId))


@bp.route("/wholesale/chargeback-claims/<claimId>/validate", methods=["POST"])
@endpoint(["ContractAdministrator"])
def validate_claim(claimId):
    claim = _claim(claimId)
    get_body(required=False)
    if claim["claim_status"] != "SUBMITTED":
        raise ApiError(errors.ERR_CLAIM_NOT_SUBMITTED[0], errors.ERR_CLAIM_NOT_SUBMITTED[1],
                       "Claim must be SUBMITTED to validate")
    order = store.purchase_orders[claim["order_id"]]
    if not order.get("is_340b_order"):
        raise ApiError(errors.ERR_NOT_340B_ORDER[0], errors.ERR_NOT_340B_ORDER[1],
                       "Chargeback claim references an order with is_340b_order == false")
    computed = pricing_service.compute_chargeback_amount(order)
    claim["computed_amount_cents"] = computed
    if claim["claimed_amount_cents"] != computed:
        raise ApiError(errors.ERR_CHARGEBACK_AMOUNT_MISMATCH[0],
                       errors.ERR_CHARGEBACK_AMOUNT_MISMATCH[1],
                       "claimed_amount_cents differs from computed_amount_cents at validation")
    claim["claim_status"] = "VALIDATED"
    db.touch(claim)
    return ok(claim)


@bp.route("/wholesale/chargeback-claims/<claimId>/settle", methods=["POST"])
@endpoint(["ContractAdministrator"])
def settle_claim(claimId):
    claim = _claim(claimId)
    get_body(required=False)
    if claim["claim_status"] != "VALIDATED":
        raise ApiError(errors.ERR_CLAIM_NOT_VALIDATED[0], errors.ERR_CLAIM_NOT_VALIDATED[1],
                       "Claim must be VALIDATED to settle")
    claim["claim_status"] = "SETTLED"
    db.touch(claim)
    return ok(claim)


@bp.route("/wholesale/chargeback-claims/<claimId>/deny", methods=["POST"])
@endpoint(["ContractAdministrator"])
def deny_claim(claimId):
    claim = _claim(claimId)
    get_body(required=False)
    if claim["claim_status"] not in ("SUBMITTED", "VALIDATED"):
        raise ApiError(errors.ERR_CLAIM_NOT_DENIABLE[0], errors.ERR_CLAIM_NOT_DENIABLE[1],
                       "Claim must be SUBMITTED or VALIDATED to deny")
    claim["claim_status"] = "DENIED"
    db.touch(claim)
    return ok(claim)
