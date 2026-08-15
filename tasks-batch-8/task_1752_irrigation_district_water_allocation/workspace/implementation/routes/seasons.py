"""IrrigationSeason endpoints: create, list, get, announce, open, close,
run-delinquency-sweep."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
from db import store, new_id, new_common, touch, iso_out, D, round2
from errors import ApiError
from response import ok, created, list_ok, filter_eq
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity
from services import ledger, ordering, billing

bp = Blueprint("seasons", __name__)

READ_ROLES = ["DistrictAdmin", "WaterUser", "DitchRider"]
GRACE_DAYS = 10

_CREATE_SCHEMA = {
    "year": ("integer", True, None, None),
    "announced_af_per_acre": ("number", True, None, "gt0"),
    "carryover_cap_pct": ("number", True, None, "range0_100"),
    "billing_method": ("enum", True, ["PER_ACRE", "PER_AF_DELIVERED"], None),
    "assessment_rate_per_acre": ("number", True, None, "ge0"),
    "toll_tier1_cap_af": ("number", True, None, "ge0"),
    "toll_tier1_rate_per_af": ("number", True, None, "ge0"),
    "toll_tier2_rate_per_af": ("number", True, None, "ge0"),
    "overage_rate_per_af": ("number", True, None, "ge0"),
    "start_date": ("datetime", True, None, None),
    "end_date": ("datetime", True, None, None),
}


@bp.post("/district/seasons")
def create_season():
    uid, role = get_context()
    body = parse_body(_CREATE_SCHEMA, allow_empty=False)
    if not body["_end_date_dt"] > body["_start_date_dt"]:
        raise ApiError("ERR_INVALID_REQUEST", 400, "end_date must be strictly after start_date")
    require_roles(["DistrictAdmin"])
    if any(s["year"] == body["year"] for s in store.seasons.values()):
        raise ApiError("ERR_DUPLICATE_SEASON_YEAR", 409,
                       "A season with year %s already exists" % body["year"])
    season = new_common({
        "id": new_id(),
        "year": body["year"],
        "announced_af_per_acre": body["announced_af_per_acre"],
        "carryover_cap_pct": body["carryover_cap_pct"],
        "billing_method": body["billing_method"],
        "assessment_rate_per_acre": body["assessment_rate_per_acre"],
        "toll_tier1_cap_af": body["toll_tier1_cap_af"],
        "toll_tier1_rate_per_af": body["toll_tier1_rate_per_af"],
        "toll_tier2_rate_per_af": body["toll_tier2_rate_per_af"],
        "overage_rate_per_af": body["overage_rate_per_af"],
        "start_date": iso_out(body["_start_date_dt"]),
        "end_date": iso_out(body["_end_date_dt"]),
        "_start_dt": body["_start_date_dt"],
        "_end_dt": body["_end_date_dt"],
        "status": "DRAFT",
    })
    store.seasons[season["id"]] = season
    return created(season)


@bp.get("/district/seasons")
def list_seasons():
    uid, role = get_context()
    require_roles(READ_ROLES)
    rows = filter_eq(list(store.seasons.values()), "status")
    return list_ok(rows)


@bp.get("/district/seasons/<sid>")
def get_season(sid):
    uid, role = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.seasons, sid))


def _transition(season, from_state, to_state):
    if season["status"] != from_state:
        raise ApiError("ERR_INVALID_SEASON_STATE", 409,
                       "Season cannot move from %s to %s" % (season["status"], to_state))
    season["status"] = to_state
    touch(season)
    return season


@bp.post("/district/seasons/<sid>/announce")
def announce_season(sid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    season = require_path_entity(store.seasons, sid)
    return ok(_transition(season, "DRAFT", "ANNOUNCED"))


@bp.post("/district/seasons/<sid>/open")
def open_season(sid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    season = require_path_entity(store.seasons, sid)
    return ok(_transition(season, "ANNOUNCED", "OPEN"))


@bp.post("/district/seasons/<sid>/close")
def close_season(sid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    season = require_path_entity(store.seasons, sid)
    if season["status"] != "OPEN":
        raise ApiError("ERR_INVALID_SEASON_STATE", 409,
                       "Season must be OPEN to close")
    season_orders = ledger.orders_of_season(sid)
    if any(o["status"] == "FLOWING" for o in season_orders):
        raise ApiError("ERR_INVALID_SEASON_STATE", 409,
                       "Season has a FLOWING turnout order")
    # Cancel every REQUESTED/SCHEDULED order, releasing committed water and
    # cancelling each order's non-terminal rider work order.
    for o in sorted(season_orders, key=lambda r: (r["created_at"], r["_seq"])):
        if o["status"] in ("REQUESTED", "SCHEDULED"):
            ordering.cascade_cancel_order(o)
    # Close every allocation with its carryover settlement (delivered-only reading).
    for alloc in sorted(ledger.allocations_of_season(sid),
                        key=lambda r: (r["created_at"], r["_seq"])):
        ledger.recompute_allocation(alloc)
        pool = ledger.entitlement_pool(alloc)
        delivered = D(alloc["delivered_af"])
        settled_unused = max(Decimal("0"), pool - delivered)
        cap = round2(D(alloc["base_entitlement_af"]) * D(season["carryover_cap_pct"]) / Decimal("100"))
        if delivered > pool:
            alloc["carryover_out_af"] = Decimal("0")  # over-allocated: carryover forfeited
        else:
            alloc["carryover_out_af"] = min(settled_unused, cap)  # cap is inclusive
        alloc["status"] = "CLOSED"
        touch(alloc)
    season["status"] = "CLOSED"
    touch(season)
    return ok(season)


@bp.post("/district/seasons/<sid>/run-delinquency-sweep")
def run_delinquency_sweep(sid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    season = require_path_entity(store.seasons, sid)
    now = db.LOGICAL_CLOCK
    swept = []
    invoices = sorted(
        (i for i in store.invoices.values() if i["season_id"] == sid),
        key=lambda r: (r["created_at"], r["_seq"]))
    for inv in invoices:
        if inv["status"] != "ISSUED":
            continue
        # Strictly greater: grace expiry exactly at the clock stays ISSUED.
        if now > inv["_due_dt"] + timedelta(days=GRACE_DAYS):
            inv["status"] = "DELINQUENT"
            billing.apply_delinquency_penalty(inv)
            touch(inv)
            swept.append(inv["id"])
    return ok({"swept_count": len(swept), "delinquent_invoice_ids": swept})
