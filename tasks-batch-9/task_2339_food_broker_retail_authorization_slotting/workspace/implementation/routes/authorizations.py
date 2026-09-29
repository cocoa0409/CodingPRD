"""Authorizations, the voids report and the discontinue action (PRD section 3.7)."""

from flask import Blueprint

import db
import response
import validators as v
from errors import ApiError
from middleware import ALL_ROLES, authorize, check_retailer_scope
from services import calc, domain

bp = Blueprint("authorizations", __name__)


def serialize(rec):
    return {
        "id": rec["id"],
        "review_id": rec["review_id"],
        "item_id": rec["item_id"],
        "retailer_id": rec["retailer_id"],
        "slotting_deal_id": rec["slotting_deal_id"],
        "authorized_store_count": rec["authorized_store_count"],
        "void_rate_basis": rec["void_rate_basis"],
        "periods_reported": rec["periods_reported"],
        "distributed_store_count": rec["distributed_store_count"],
        "void_store_count": rec["void_store_count"],
        "pending_store_count": rec["pending_store_count"],
        "void_rate_bps": rec["void_rate_bps"],
        "slotting_share_cents": rec["slotting_share_cents"],
        "promo_settled_funding_cents": rec["promo_settled_funding_cents"],
        "trade_spend_total_cents": rec["trade_spend_total_cents"],
        "authorization_state": rec["authorization_state"],
        "settlement_state": rec["settlement_state"],
        "discontinue_reason": rec["discontinue_reason"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


@bp.get("/authorizations/<authorization_id>")
def read_authorization(authorization_id):
    authorize(*ALL_ROLES)
    return response.ok(serialize(db.get("authorizations", authorization_id)))


@bp.get("/authorizations")
def list_authorizations():
    authorize(*ALL_ROLES)
    limit, offset = v.pagination()
    review_id = v.filter_value("review_id")
    item_id = v.filter_value("item_id")
    retailer_id = v.filter_value("retailer_id")
    slotting_deal_id = v.filter_value("slotting_deal_id")
    authorization_state = v.filter_value("authorization_state")
    settlement_state = v.filter_value("settlement_state")
    rows = []
    for rec in db.ordered("authorizations"):
        if review_id is not None and rec["review_id"] != review_id:
            continue
        if item_id is not None and rec["item_id"] != item_id:
            continue
        if retailer_id is not None and rec["retailer_id"] != retailer_id:
            continue
        if slotting_deal_id is not None and rec["slotting_deal_id"] != slotting_deal_id:
            continue
        if authorization_state is not None and rec["authorization_state"] != authorization_state:
            continue
        if settlement_state is not None and rec["settlement_state"] != settlement_state:
            continue
        rows.append(rec)
    return response.listing([serialize(r) for r in rows], limit, offset)


@bp.get("/authorizations/<authorization_id>/voids-report")
def voids_report(authorization_id):
    authorize(*ALL_ROLES)
    rec = db.get("authorizations", authorization_id)

    item = db.find("items", rec["item_id"])
    retailer = db.find("retailers", rec["retailer_id"])
    latest = domain.latest_live_posting(rec["id"])
    basis = rec["void_rate_basis"]
    other = "REPORTED_BASIS" if basis == "STORE_COUNT_BASIS" else "STORE_COUNT_BASIS"

    pinned = calc.void_metrics(basis, rec["authorized_store_count"], latest)
    counterfactual = calc.void_metrics(other, rec["authorized_store_count"], latest)

    return response.ok({
        "authorization_id": rec["id"],
        "item_id": rec["item_id"],
        "upc": item["upc"] if item else None,
        "retailer_id": rec["retailer_id"],
        "void_rate_basis": basis,
        "authorized_store_count": rec["authorized_store_count"],
        "latest_period_index": latest["period_index"] if latest else 0,
        "reported_store_count": latest["reported_store_count"] if latest else 0,
        "distributed_store_count": pinned["distributed_store_count"],
        "void_store_count": pinned["void_store_count"],
        "pending_store_count": pinned["pending_store_count"],
        "void_rate_bps": pinned["void_rate_bps"],
        "at_risk_void_rate_bps": retailer["at_risk_void_rate_bps"] if retailer else 0,
        "is_at_risk": rec["authorization_state"] == "AT_RISK",
        "counterfactual_basis": other,
        "counterfactual_void_rate_bps": counterfactual["void_rate_bps"],
    })


@bp.post("/authorizations/<authorization_id>/discontinue")
def discontinue_authorization(authorization_id):
    user_id, role = authorize("RetailerBuyer")
    data = v.body()
    reason = v.req_string(data, "discontinue_reason")

    rec = db.get("authorizations", authorization_id)
    check_retailer_scope(role, user_id, rec["retailer_id"])

    previous = rec["authorization_state"]
    if previous not in domain.LIVE_AUTHORIZATION_STATES:
        raise ApiError("ERR_INVALID_STATE")

    if previous in ("AUTHORIZED", "AT_RISK"):
        for event in domain.promotions_of_authorization(rec["id"]):
            if event["state"] in ("COMMITTED", "EXECUTED"):
                raise ApiError("ERR_AUTHORIZATION_HAS_LIVE_PROMOTION")

    rec["authorization_state"] = "DISCONTINUED"
    rec["discontinue_reason"] = reason
    db.touch(rec)

    deal = db.find("deals", rec["slotting_deal_id"])
    if previous == "AT_RISK":
        domain.release_recovery_hold(deal)
    domain.maybe_write_off(deal)
    domain.recompute_principal(domain.principal_of_authorization(rec))

    return response.ok(serialize(rec))
