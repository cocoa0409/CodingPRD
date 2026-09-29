"""Carrier registry endpoints (PRD 3.1) and the reserve summary read."""
from decimal import Decimal

from flask import Blueprint, request

import validation as v
from auth import (ACCESS_BILLING_ANALYST, CARRIER_REPRESENTATIVE,
                  DISPUTE_RESOLUTION_OFFICER, INTERCONNECTION_MANAGER,
                  NETWORK_PLANNER, PLATFORM_ADMIN, REVENUE_ASSURANCE_CONTROLLER,
                  authenticate, scope_check)
from constants import (AGREEMENT_STATUSES, CARRIER_TYPES, FACTOR_STATUSES,
                       OCN_PATTERN)
from envelope import object_response, paginate
from errors import ApiError
from lookup import get_carrier
from services.reserve import compute_figures
from store import base_record, db, ordered

bp = Blueprint("carriers", __name__)

ZERO2 = Decimal("0.00")


@bp.post("/carriers")
def register_carrier():
    authenticate((PLATFORM_ADMIN,))
    payload = v.body()
    carrier_name = v.string(payload, "carrier_name", max_len=120)
    ocn = v.string(payload, "ocn", pattern=OCN_PATTERN)
    carrier_type = v.enum(payload, "carrier_type", CARRIER_TYPES)

    for existing in db.carriers.values():
        if existing["ocn"] == ocn:
            raise ApiError("ERR_DUPLICATE_OCN", "ocn %s is already registered" % ocn)

    carrier = base_record()
    carrier.update({
        "carrier_name": carrier_name,
        "ocn": ocn,
        "carrier_type": carrier_type,
        "uncollectible_reserve_balance_usd": ZERO2,
        "disputed_reserve_balance_usd": ZERO2,
        "open_receivable_usd": ZERO2,
        "disputed_receivable_usd": ZERO2,
        "net_receivable_usd": ZERO2,
    })
    db.carriers[carrier["id"]] = carrier
    return object_response(carrier, 201)


@bp.get("/carriers/<carrier_id>")
def read_carrier(carrier_id):
    actor = authenticate((PLATFORM_ADMIN, INTERCONNECTION_MANAGER,
                          ACCESS_BILLING_ANALYST, REVENUE_ASSURANCE_CONTROLLER,
                          DISPUTE_RESOLUTION_OFFICER, CARRIER_REPRESENTATIVE))
    carrier = get_carrier(carrier_id)
    scope_check(actor, carrier["id"])
    return object_response(carrier)


@bp.get("/carriers")
def list_carriers():
    authenticate((PLATFORM_ADMIN, INTERCONNECTION_MANAGER, ACCESS_BILLING_ANALYST,
                  REVENUE_ASSURANCE_CONTROLLER))
    rows = ordered(db.carriers)
    carrier_type = request.args.get("carrier_type")
    if carrier_type:
        rows = [r for r in rows if r["carrier_type"] == carrier_type]
    return paginate(rows, request.args, lambda r: r)


@bp.get("/carriers/<carrier_id>/reserve-summary")
def reserve_summary(carrier_id):
    authenticate((REVENUE_ASSURANCE_CONTROLLER, ACCESS_BILLING_ANALYST,
                  PLATFORM_ADMIN))
    carrier = get_carrier(carrier_id)
    figures = compute_figures(carrier)
    return object_response({
        "open_receivable_usd": figures["open_receivable_usd"],
        "disputed_receivable_usd": figures["disputed_receivable_usd"],
        "net_receivable_usd": figures["net_receivable_usd"],
        "tier_pct": figures["tier_pct"],
        "uncollectible_reserve_balance_usd": figures["uncollectible_reserve_balance_usd"],
        "regulatory_disputed_reserve_usd": figures["regulatory_disputed_reserve_usd"],
        "gaap_disputed_reserve_usd": figures["gaap_disputed_reserve_usd"],
        "disputed_reserve_basis_delta_usd": figures["disputed_reserve_basis_delta_usd"],
    })


@bp.get("/carriers/<carrier_id>/agreements")
def list_carrier_agreements(carrier_id):
    actor = authenticate((PLATFORM_ADMIN, INTERCONNECTION_MANAGER, NETWORK_PLANNER,
                          CARRIER_REPRESENTATIVE))
    carrier = get_carrier(carrier_id)
    scope_check(actor, carrier["id"])
    rows = [a for a in ordered(db.agreements) if a["carrier_id"] == carrier["id"]]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, request.args, lambda r: r)


@bp.get("/carriers/<carrier_id>/traffic-factor-filings")
def list_carrier_factor_filings(carrier_id):
    actor = authenticate((PLATFORM_ADMIN, ACCESS_BILLING_ANALYST,
                          REVENUE_ASSURANCE_CONTROLLER, CARRIER_REPRESENTATIVE))
    carrier = get_carrier(carrier_id)
    scope_check(actor, carrier["id"])
    rows = [f for f in ordered(db.factor_filings) if f["carrier_id"] == carrier["id"]]
    quarter = request.args.get("quarter")
    if quarter:
        rows = [r for r in rows if r["quarter"] == quarter]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, request.args, lambda r: r)
