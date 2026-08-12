"""CoProductionShare routes (PRD 3.3)."""

from decimal import Decimal

from flask import Blueprint

from db import store
from errors import (ApiError, ERR_INVALID_STATE, ERR_PARTNER_KIND,
                    ERR_SHARE_OVERFLOW, conflict)
from middleware import require_roles
from response import ok_object
from routes.common import get_or_404, list_response
from services import compute_settlement
from util import (json_body, new_record, req_enum, req_number, req_str, rhu,
                  to_public, touch)

bp = Blueprint("co_production_shares", __name__)

SPLIT_METHODS = ("GROSS_COST", "NET_REVENUE_SHARE")
TARGET_STATES = ("RATIFIED", "DISPUTED", "SETTLED")


def _check_percentage_capacity(share):
    total = sum(
        s["share_percentage"]
        for s in store.co_production_shares.values()
        if s["production_id"] == share["production_id"]
        and s["id"] != share["id"]
        and s["status"] == "RATIFIED"
    )
    if total + share["share_percentage"] > Decimal(100):
        raise ApiError(ERR_SHARE_OVERFLOW, 422,
                       "Ratified share percentages would exceed 100")


def _compute_accrual(share, prod):
    return rhu(share["share_percentage"] / Decimal(100)
               * Decimal(prod["season_revenue_cents"]))


@bp.post("/opera/co-production-shares")
def create_share():
    require_roles("ProductionManager")
    body = json_body()
    production_id = req_str(body, "production_id")
    company_id = req_str(body, "company_id")
    pct = req_number(body, "share_percentage")
    if pct <= 0 or pct > 100:
        raise ApiError("ERR_VALIDATION", 400,
                       "share_percentage must be greater than 0 and at most 100")
    method = req_enum(body, "cost_split_method", SPLIT_METHODS)
    prod = get_or_404(store.productions, production_id, "Production")
    company = get_or_404(store.partner_companies, company_id, "PartnerCompany")
    if company["partner_kind"] != "CO_PRODUCER":
        raise ApiError(ERR_PARTNER_KIND, 422,
                       "Co-production share requires a CO_PRODUCER partner")
    rec = new_record(
        production_id=prod["id"],
        company_id=company["id"],
        share_percentage=pct,
        cost_split_method=method,
        accrued_revenue_share_cents=0,
        settlement_cents=None,
        status="PROPOSED",
    )
    store.co_production_shares[rec["id"]] = rec
    return ok_object(to_public(rec), 201)


@bp.get("/opera/co-production-shares")
def list_shares():
    require_roles("Any")
    return list_response(
        store.co_production_shares.values(),
        [("production_id", "production_id"), ("company_id", "company_id"),
         ("status", "status")],
    )


@bp.get("/opera/co-production-shares/<sid>")
def get_share(sid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.co_production_shares, sid,
                                          "CoProductionShare")))


@bp.post("/opera/co-production-shares/<sid>/transition")
def transition_share(sid):
    require_roles("ProductionManager")
    body = json_body()
    to_state = req_enum(body, "to_state", TARGET_STATES)
    share = get_or_404(store.co_production_shares, sid, "CoProductionShare")
    prod = store.productions[share["production_id"]]
    cur = share["status"]

    if cur in ("PROPOSED", "DISPUTED") and to_state == "RATIFIED":
        _check_percentage_capacity(share)
        share["status"] = "RATIFIED"
        if share["cost_split_method"] == "NET_REVENUE_SHARE":
            share["accrued_revenue_share_cents"] = _compute_accrual(share, prod)
        touch(share)
    elif cur == "RATIFIED" and to_state == "DISPUTED":
        share["status"] = "DISPUTED"
        touch(share)
    elif cur == "RATIFIED" and to_state == "SETTLED":
        share["settlement_cents"] = compute_settlement(share, prod)
        share["status"] = "SETTLED"
        touch(share)
    else:
        raise conflict(ERR_INVALID_STATE,
                       f"CoProductionShare cannot transition {cur} -> {to_state}")

    return ok_object(to_public(share))
