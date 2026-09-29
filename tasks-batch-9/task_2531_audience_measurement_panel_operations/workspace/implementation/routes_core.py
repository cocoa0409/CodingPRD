"""Logical clock, markets and quota cells."""
from flask import Blueprint

from auth import ALL_ROLES, PANEL_OPERATIONS_MANAGER, roles
from calculations import (AGE_BANDS, GEO_ZONES, INCOME_BANDS,
                          boost_reservation_cents)
from common import must
from errors import ApiError
from response import apply_filters, created, listing, ok
from services import compute_posture, recompute_market
from store import db
from util import (D, format_iso, get_body, require_fields, want_int, want_iso,
                  want_pattern, want_str, want_enum)

bp = Blueprint("core", __name__)


# ------------------------------------------------------------------- clock
@bp.post("/_clock/set_current_utc")
@roles(*ALL_ROLES)
def set_clock():
    body = get_body()
    require_fields(body, ["current_utc"])
    moment = want_iso(body, "current_utc")
    if moment < db.clock:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC",
                       "the logical clock never moves backwards")
    previous = db.set_clock(moment)
    return ok({"current_utc": format_iso(db.clock),
               "previous_utc": format_iso(previous)})


# ------------------------------------------------------------------ markets
@bp.post("/markets")
@roles(PANEL_OPERATIONS_MANAGER)
def register_market():
    body = get_body()
    require_fields(body, ["name", "market_code", "dma_rank",
                          "incentive_budget_cents"])
    name = want_str(body, "name", min_len=1, max_len=120)
    market_code = want_pattern(body, "market_code", r"^DMA-\d{3}$", max_len=7)
    dma_rank = want_int(body, "dma_rank", minimum=1)
    budget = want_int(body, "incentive_budget_cents", minimum=0)
    for existing in db.all("markets"):
        if existing["market_code"] == market_code:
            raise ApiError("ERR_INVALID_REQUEST",
                           "market_code already exists")
    market = db.insert("markets", {
        "name": name,
        "market_code": market_code,
        "dma_rank": dma_rank,
        "incentive_budget_cents": budget,
        "incentive_budget_committed_cents": 0,
        "incentive_budget_reserved_cents": 0,
        "quota_cell_count": 0,
        "filled_cell_count": 0,
        "under_target_cell_count": 0,
        "open_audit_count": 0,
        "recruitment_posture": compute_posture(0, 0, 0, 0),
        "accreditation_status": "UNAUDITED",
        "publication_blocked": False,
        "limitation_disclosures": [],
        "posture_changed_at": db.now_iso(),
    })
    return created(market)


@bp.get("/markets/<market_id>")
@roles(*ALL_ROLES)
def read_market(market_id):
    return ok(must("markets", market_id))


@bp.get("/markets")
@roles(*ALL_ROLES)
def list_markets():
    rows = apply_filters(db.all("markets"), {
        "recruitment_posture": ("recruitment_posture", "str"),
        "accreditation_status": ("accreditation_status", "str"),
    })
    return listing("markets", rows)


@bp.post("/markets/<market_id>/budget-adjustments")
@roles(PANEL_OPERATIONS_MANAGER)
def adjust_budget(market_id):
    market = must("markets", market_id)
    body = get_body()
    require_fields(body, ["delta_cents", "memo"])
    delta = want_int(body, "delta_cents")
    want_str(body, "memo", min_len=1, max_len=400)
    proposed = market["incentive_budget_cents"] + delta
    spoken_for = (market["incentive_budget_committed_cents"]
                  + market["incentive_budget_reserved_cents"])
    if proposed < spoken_for:
        raise ApiError("ERR_INCENTIVE_BUDGET_EXCEEDED",
                       "authorisation may not fall below committed plus reserved")
    market["incentive_budget_cents"] = proposed
    db.touch(market)
    return ok(market)


# --------------------------------------------------------------- quota cells
@bp.post("/markets/<market_id>/quota-cells")
@roles(PANEL_OPERATIONS_MANAGER)
def create_quota_cell(market_id):
    market = must("markets", market_id)
    body = get_body()
    require_fields(body, ["age_band", "income_band", "geo_zone",
                          "target_households", "base_incentive_cents"])
    age_band = want_enum(body, "age_band", AGE_BANDS)
    income_band = want_enum(body, "income_band", INCOME_BANDS)
    geo_zone = want_enum(body, "geo_zone", GEO_ZONES)
    target = want_int(body, "target_households", minimum=1)
    base_incentive = want_int(body, "base_incentive_cents", minimum=0)
    reservation = boost_reservation_cents(base_incentive, target)
    spoken_for = (market["incentive_budget_committed_cents"]
                  + market["incentive_budget_reserved_cents"] + reservation)
    if spoken_for > market["incentive_budget_cents"]:
        raise ApiError("ERR_INCENTIVE_BUDGET_EXCEEDED",
                       "the boost reservation exceeds the market budget")
    for cell in db.where("quota_cells", market_id=market["id"]):
        if (cell["age_band"] == age_band and cell["income_band"] == income_band
                and cell["geo_zone"] == geo_zone):
            raise ApiError("ERR_QUOTA_CELL_DUPLICATE",
                           "this stratum already exists in the market")
    cell = db.insert("quota_cells", {
        "market_id": market["id"],
        "age_band": age_band,
        "income_band": income_band,
        "geo_zone": geo_zone,
        "target_households": target,
        "base_incentive_cents": base_incentive,
        "intab_count": 0,
        "fill_rate": D("0.0000"),
        "quota_status": "UNDER_TARGET",
        "incentive_boost_active": True,
        "effective_incentive_multiplier": D("1.25"),
    })
    recompute_market(market)
    return created(cell)


@bp.get("/quota-cells/<quota_cell_id>")
@roles(*ALL_ROLES)
def read_quota_cell(quota_cell_id):
    return ok(must("quota_cells", quota_cell_id))


@bp.get("/quota-cells")
@roles(*ALL_ROLES)
def list_quota_cells():
    rows = apply_filters(db.all("quota_cells"), {
        "market_id": ("market_id", "str"),
        "quota_status": ("quota_status", "str"),
        "incentive_boost_active": ("incentive_boost_active", "bool"),
    })
    return listing("quota_cells", rows)
