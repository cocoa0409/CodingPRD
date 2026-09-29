"""Logical clock and foreign buyers."""
from decimal import Decimal

import ledgers
import valid
from authz import authenticate
from core import ok
from db import insert, require, serialize, store, touch
from sweep import run_sweep

from flask import Blueprint

bp = Blueprint("buyers", __name__)

D = Decimal
CREDIT_RATINGS = ("AAA", "AA", "A", "BBB", "BB", "B", "CCC")
SANCTIONS_TIERS = ("NONE", "WATCHLIST", "EMBARGOED")
STAFF_READ = ("TradeComplianceOfficer", "ExportOpsCoordinator",
              "DocumentaryCreditReviewer", "FinanceCollectionsOfficer", "PlatformAdmin")


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("PlatformAdmin",))
    body = valid.body()
    _raw, instant = valid.instant(body, "current_utc")
    store.clock = instant
    run_sweep(instant)
    return ok({})


@bp.post("/foreign-buyers")
def create_buyer():
    authenticate(("TradeComplianceOfficer", "PlatformAdmin"))
    body = valid.body()
    legal_name = valid.string(body, "legal_name", min_len=1, max_len=200)
    country_code = valid.string(body, "country_code", pattern=r"^[A-Z]{2}$",
                                min_len=2, max_len=2)
    credit_rating = valid.enum(body, "credit_rating", CREDIT_RATINGS)
    sanctions_tier = valid.enum(body, "sanctions_tier", SANCTIONS_TIERS,
                                required=False, default="NONE")
    flag = valid.boolean(body, "restricted_party_flag", default=False)
    reason = valid.string(body, "restricted_party_reason", required=False,
                          max_len=1000, default=None)
    if not flag:
        reason = None

    row = insert(store.buyers, {
        "legal_name": legal_name,
        "country_code": country_code,
        "credit_rating": credit_rating,
        "sanctions_tier": sanctions_tier,
        "restricted_party_flag": flag,
        "restricted_party_reason": reason,
        "aggregate_exposure_usd": D("0.00"),
        "open_order_count": 0,
    })
    return ok(serialize(row), 201)


@bp.get("/foreign-buyers/<buyer_id>")
def read_buyer(buyer_id):
    authenticate(STAFF_READ)
    row = require(store.buyers, buyer_id, "ERR_BUYER_NOT_FOUND")
    return ok(serialize(row))


@bp.patch("/foreign-buyers/<buyer_id>/restricted-party-flag")
def set_restricted_party_flag(buyer_id):
    authenticate(("TradeComplianceOfficer",))
    buyer = require(store.buyers, buyer_id, "ERR_BUYER_NOT_FOUND")
    body = valid.body()
    flag = valid.boolean(body, "restricted_party_flag", required=True)
    reason = valid.string(body, "restricted_party_reason", required=False,
                          max_len=1000, default=None)

    buyer["restricted_party_flag"] = flag
    buyer["restricted_party_reason"] = reason if flag else None
    touch(buyer)
    if flag:
        ledgers.restricted_party_cascade(buyer)
    return ok(serialize(buyer))
