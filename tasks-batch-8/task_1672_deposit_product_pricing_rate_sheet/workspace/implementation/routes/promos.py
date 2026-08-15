"""PromotionalOffer endpoints."""

from datetime import date

from flask import Blueprint

from db import STORE
from errors import (
    ApiError,
    ERR_PRODUCT_NOT_FOUND,
    ERR_PROMO_INVALID_STATE,
    ERR_PROMO_WINDOW_OVERLAP,
    ERR_RATE_CAP_EXCEEDED,
    bad_request,
    not_found,
)
from middleware import get_body, paginate, query_enum, require_roles
from response import ok_object
from serialize import serialize, serialize_many
from utils import bump, opt_int, req_date, req_enum, req_int, req_str, stamp_new

bp = Blueprint("promos", __name__)

PROMO_STATUSES = ("DRAFT", "SCHEDULED", "ACTIVE", "CLOSED", "EXPIRED")
ROLLOVER_TREATMENTS = ("ROLL_TO_SHEET", "RENEW_THEN_SHEET")


@bp.post("/promotional-offers")
@require_roles("PricingAnalyst")
def create_offer():
    data = get_body()
    product_id = req_str(data, "product_id")
    market_code = req_str(data, "market_code")
    promo_rate_bp = req_int(data, "promo_rate_bp", minimum=0)
    promo_term_days = req_int(data, "promo_term_days", minimum=1)
    enrollment_start = req_date(data, "enrollment_start")
    enrollment_end = req_date(data, "enrollment_end")
    min_opening = opt_int(data, "min_opening_balance_cents", 0, minimum=0)
    rollover = req_enum(data, "rollover_treatment", ROLLOVER_TREATMENTS)
    product = STORE["products"].get(product_id)
    if product is None:
        raise ApiError(ERR_PRODUCT_NOT_FOUND, 422, "Referenced product_id does not exist")
    if promo_rate_bp > product["rate_cap_bp"]:
        raise ApiError(ERR_RATE_CAP_EXCEEDED, 422,
                       "promo_rate_bp exceeds product.rate_cap_bp")
    row = {
        "product_id": product_id,
        "market_code": market_code,
        "promo_rate_bp": promo_rate_bp,
        "promo_term_days": promo_term_days,
        "enrollment_start": enrollment_start,
        "enrollment_end": enrollment_end,
        "min_opening_balance_cents": min_opening,
        "rollover_treatment": rollover,
        "status": "DRAFT",
    }
    stamp_new(row)
    STORE["promos"][row["id"]] = row
    return ok_object(serialize("promos", row), 201)


@bp.get("/promotional-offers")
@require_roles("PricingAnalyst", "PricingCommittee", "BranchBanker")
def list_offers():
    from flask import request
    product_id = request.args.get("product_id")
    market_code = request.args.get("market_code")
    status = query_enum("status", PROMO_STATUSES)
    rows = list(STORE["promos"].values())
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if market_code is not None:
        rows = [r for r in rows if r["market_code"] == market_code]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(serialize_many("promos", rows))


@bp.get("/promotional-offers/<offer_id>")
@require_roles("PricingAnalyst", "PricingCommittee", "BranchBanker")
def get_offer(offer_id):
    row = STORE["promos"].get(offer_id)
    if row is None:
        raise not_found("Promotional offer not found")
    return ok_object(serialize("promos", row))


@bp.post("/promotional-offers/<offer_id>/publish")
@require_roles("PricingAnalyst")
def publish_offer(offer_id):
    get_body()
    row = STORE["promos"].get(offer_id)
    if row is None:
        raise not_found("Promotional offer not found")
    if row["status"] != "DRAFT":
        raise ApiError(ERR_PROMO_INVALID_STATE, 409,
                       f"Cannot publish an offer in {row['status']}")
    s1 = date.fromisoformat(row["enrollment_start"])
    e1 = date.fromisoformat(row["enrollment_end"])
    if s1 > e1:
        raise bad_request("enrollment_start must not fall after enrollment_end")
    # Closed-interval overlap: touching boundary dates conflict.
    for o in STORE["promos"].values():
        if o["id"] == row["id"] or o["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if (o["product_id"] != row["product_id"]
                or o["market_code"] != row["market_code"]):
            continue
        s2 = date.fromisoformat(o["enrollment_start"])
        e2 = date.fromisoformat(o["enrollment_end"])
        if s1 <= e2 and s2 <= e1:
            raise ApiError(ERR_PROMO_WINDOW_OVERLAP, 409,
                           "Enrollment window intersects another offer for the pair")
    row["status"] = "SCHEDULED"
    bump(row)
    return ok_object(serialize("promos", row))


@bp.post("/promotional-offers/<offer_id>/close")
@require_roles("PricingAnalyst")
def close_offer(offer_id):
    get_body()
    row = STORE["promos"].get(offer_id)
    if row is None:
        raise not_found("Promotional offer not found")
    if row["status"] != "ACTIVE":
        raise ApiError(ERR_PROMO_INVALID_STATE, 409,
                       f"Cannot close an offer in {row['status']}")
    row["status"] = "CLOSED"
    bump(row)
    return ok_object(serialize("promos", row))
