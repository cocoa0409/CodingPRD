"""Trade-area models (with the model-lock supersession cascade) and
competitor/co-tenant listings."""

from flask import Blueprint, Response

from db import db
from errors import (
    not_found, invalid_state, already_terminal, invalid_request, stale_version,
)
from middleware import require_roles, ALL_API_ROLES
from response import ok_object
from services import (
    new_record, touch, compute_cannibalization, ser_model, ser_listing,
)
from util import (
    get_body, req_int, req_enum, req_str, fk_exists, list_response,
)

bp = Blueprint("models", __name__)

_VARIANTS = ("FLAT_BAND", "DISTANCE_DECAY")
_LISTING_TYPES = ("COMPETITOR", "COTENANT")
MODELABLE_SITE_STATUSES = {"SCREENED", "MODELED", "SCORED", "FORECAST_LOCKED",
                           "IN_COMMITTEE"}


def _get_model(mid):
    rec = db.models.get(mid)
    if rec is None:
        raise not_found(f"TradeAreaModel not found: {mid}")
    return rec


@bp.post("/api/trade-area-models")
def create_model():
    require_roles("RealEstateAnalyst")
    body = get_body(required=True)
    site = fk_exists(body, "site_id", db.sites)
    drive_time = req_int(body, "drive_time_minutes", min_v=1, max_v=30)
    population = req_int(body, "trade_area_population", min_v=0)
    spend = req_int(body, "per_capita_spend_cents", min_v=0)
    variant = req_enum(body, "cannibalization_variant", _VARIANTS)
    raw_pairs = body.get("store_drive_times", [])
    if raw_pairs is None:
        raw_pairs = []
    if not isinstance(raw_pairs, list):
        raise invalid_request("store_drive_times must be an array")
    # Layer 3: every referenced store id must exist before shape checks.
    for pair in raw_pairs:
        if not isinstance(pair, dict):
            raise invalid_request(
                "store_drive_times entries must be objects")
        sid = pair.get("store_id")
        if sid is None:
            raise invalid_request("store_drive_times entry missing store_id")
        if not isinstance(sid, str):
            raise invalid_request("store_drive_times store_id must be a string")
        if sid not in db.stores:
            raise not_found(f"Referenced store_id does not exist: {sid}")
    pairs = []
    for pair in raw_pairs:
        dm = pair.get("drive_minutes")
        if not isinstance(dm, int) or isinstance(dm, bool) or dm < 0:
            raise invalid_request(
                "store_drive_times drive_minutes must be an integer >= 0")
        pairs.append({"store_id": pair["store_id"], "drive_minutes": dm})
    # Layer 5: the site's pipeline stage must accept a new model.
    if site["site_status"] not in MODELABLE_SITE_STATUSES:
        raise invalid_state(
            f"Site in {site['site_status']} does not accept trade-area models")
    rec = new_record()
    rec.update({
        "site_id": site["id"],
        "drive_time_minutes": drive_time,
        "trade_area_population": population,
        "per_capita_spend_cents": spend,
        "cannibalization_variant": variant,
        "store_drive_times": pairs,
        "model_status": "DRAFT",
        "cannibalized_sales_cents": None,
    })
    db.models[rec["id"]] = rec
    return ok_object(ser_model(rec), status=201)


@bp.get("/api/trade-area-models")
def list_models():
    require_roles(*ALL_API_ROLES)
    return list_response(db.models.values(), ser_model,
                         filters=["site_id", "model_status"])


@bp.get("/api/trade-area-models/<mid>")
def get_model(mid):
    require_roles(*ALL_API_ROLES)
    return ok_object(ser_model(_get_model(mid)))


@bp.post("/api/trade-area-models/<mid>/lock")
def lock_model(mid):
    require_roles("RealEstateAnalyst")
    model = _get_model(mid)
    body = get_body(required=True)
    expected = req_int(body, "expected_site_version")
    site = db.sites[model["site_id"]]
    # Layer 4: OCC guard runs before state checks.
    if expected != site["version"]:
        raise stale_version(
            f"expected_site_version {expected} != site version "
            f"{site['version']}")
    # Layer 5: terminal lockdown, then state permission.
    if model["model_status"] == "SUPERSEDED":
        raise already_terminal("TradeAreaModel is SUPERSEDED")
    if model["model_status"] != "DRAFT":
        raise invalid_state(
            f"Model in {model['model_status']} cannot be locked")
    if site["site_status"] not in MODELABLE_SITE_STATUSES:
        raise invalid_state(
            f"Site in {site['site_status']} does not permit model lock")
    # --- effects, in pinned cascade order -------------------------------
    # Snapshot cannibalization from the live store roster at this instant.
    model["cannibalized_sales_cents"] = compute_cannibalization(model)
    model["model_status"] = "LOCKED"
    touch(model)
    touch(site)  # locking advances Site.version by exactly 1
    # Link 1: any other LOCKED model of the same site -> SUPERSEDED.
    superseded_models = [
        m for m in db.models.values()
        if m["site_id"] == site["id"] and m["id"] != model["id"]
        and m["model_status"] == "LOCKED"
    ]
    for m in superseded_models:
        m["model_status"] = "SUPERSEDED"
        touch(m)
    # Link 2: forecasts pinned to a just-superseded model -> SUPERSEDED.
    sup_ids = {m["id"] for m in superseded_models}
    superseded_forecasts = [
        f for f in db.forecasts.values()
        if f["trade_area_model_id"] in sup_ids
        and f["forecast_status"] in ("DRAFT", "COMMITTEE_LOCKED")
    ]
    locked_forecast_superseded = any(
        f["forecast_status"] == "COMMITTEE_LOCKED" and f["site_id"] == site["id"]
        for f in superseded_forecasts)
    for f in superseded_forecasts:
        f["forecast_status"] = "SUPERSEDED"
        touch(f)
    # Link 3: reviews pinning a just-superseded forecast -> EXPIRED.
    sup_fids = {f["id"] for f in superseded_forecasts}
    expired_reviews = [
        r for r in db.reviews.values()
        if r["sales_forecast_id"] in sup_fids
        and r["review_status"] in ("OPEN", "DECIDED")
    ]
    for r in expired_reviews:
        r["review_status"] = "EXPIRED"
        touch(r)
    # Link 4: site regressions; independently, the SCREENED bubble-up.
    if (site["site_status"] == "IN_COMMITTEE"
            and any(r["site_id"] == site["id"] for r in expired_reviews)):
        site["site_status"] = "MODELED"
    elif (site["site_status"] == "FORECAST_LOCKED"
          and locked_forecast_superseded):
        site["site_status"] = "MODELED"
    elif site["site_status"] == "SCREENED":
        site["site_status"] = "MODELED"
    return ok_object(ser_model(model))


# ---------------------------------------------------------------------------
# Competitor listings
# ---------------------------------------------------------------------------

@bp.post("/api/competitor-listings")
def create_listing():
    require_roles("RealEstateAnalyst")
    body = get_body(required=True)
    model = fk_exists(body, "trade_area_model_id", db.models)
    listing_type = req_enum(body, "listing_type", _LISTING_TYPES)
    brand = req_str(body, "brand_name")
    sqft = req_int(body, "estimated_sqft", min_v=1)
    distance = req_int(body, "distance_minutes", min_v=0)
    if model["model_status"] == "SUPERSEDED":
        raise already_terminal("TradeAreaModel is SUPERSEDED")
    if model["model_status"] != "DRAFT":
        raise invalid_state("Listings may only be added to a DRAFT model")
    rec = new_record()
    rec.update({
        "trade_area_model_id": model["id"],
        "listing_type": listing_type,
        "brand_name": brand,
        "estimated_sqft": sqft,
        "distance_minutes": distance,
    })
    db.listings[rec["id"]] = rec
    return ok_object(ser_listing(rec), status=201)


@bp.get("/api/competitor-listings")
def list_listings():
    require_roles(*ALL_API_ROLES)
    return list_response(db.listings.values(), ser_listing,
                         filters=["trade_area_model_id", "listing_type"])


@bp.get("/api/competitor-listings/<lid>")
def get_listing(lid):
    require_roles(*ALL_API_ROLES)
    rec = db.listings.get(lid)
    if rec is None:
        raise not_found(f"CompetitorListing not found: {lid}")
    return ok_object(ser_listing(rec))


@bp.delete("/api/competitor-listings/<lid>")
def delete_listing(lid):
    require_roles("RealEstateAnalyst")
    rec = db.listings.get(lid)
    if rec is None:
        raise not_found(f"CompetitorListing not found: {lid}")
    model = db.models[rec["trade_area_model_id"]]
    if model["model_status"] == "SUPERSEDED":
        raise already_terminal("TradeAreaModel is SUPERSEDED")
    if model["model_status"] != "DRAFT":
        raise invalid_state("Listings may only be removed from a DRAFT model")
    del db.listings[lid]
    return Response(status=204)
