"""Sales forecasts: variant gross models and the committee lock."""

from decimal import Decimal

from flask import Blueprint

from db import db
from errors import ApiError, not_found, invalid_state, already_terminal
from middleware import require_roles, ALL_API_ROLES
from response import ok_object
from services import (
    new_record, touch, compute_gross, compute_cannibalization,
    occupancy_ratio_bp, occupancy_band, ser_forecast,
)
from util import get_body, req_enum, fk_exists, list_response

bp = Blueprint("forecasts", __name__)

_VARIANTS = ("GRAVITY", "ANALOG")


def _get_forecast(fid):
    rec = db.forecasts.get(fid)
    if rec is None:
        raise not_found(f"SalesForecast not found: {fid}")
    return rec


@bp.post("/api/sales-forecasts")
def create_forecast():
    require_roles("RealEstateAnalyst")
    body = get_body(required=True)
    site = fk_exists(body, "site_id", db.sites)
    model = fk_exists(body, "trade_area_model_id", db.models)
    variant = req_enum(body, "model_variant", _VARIANTS)
    # Layer 5: site must be MODELED or SCORED.
    if site["site_status"] not in ("MODELED", "SCORED"):
        raise invalid_state(
            f"Site in {site['site_status']} does not accept forecasts")
    # Layer 9: pinned model must be LOCKED and belong to the site.
    if model["model_status"] != "LOCKED" or model["site_id"] != site["id"]:
        raise ApiError(
            "ERR_TRADE_AREA_NOT_LOCKED", 409,
            "Referenced trade-area model is not LOCKED for this site")
    rec = new_record()
    rec.update({
        "site_id": site["id"],
        "trade_area_model_id": model["id"],
        "model_variant": variant,
        "forecast_status": "DRAFT",
        "gross_annual_sales_cents": compute_gross(site, model, variant),
        "cannibalized_sales_cents": None,
        "net_annual_sales_cents": None,
        "occupancy_ratio_bp": None,
        "occupancy_band": None,
    })
    db.forecasts[rec["id"]] = rec
    return ok_object(ser_forecast(rec), status=201)


@bp.get("/api/sales-forecasts")
def list_forecasts():
    require_roles(*ALL_API_ROLES)
    return list_response(
        db.forecasts.values(), ser_forecast,
        filters=["site_id", "trade_area_model_id", "forecast_status"])


@bp.get("/api/sales-forecasts/<fid>")
def get_forecast(fid):
    require_roles(*ALL_API_ROLES)
    return ok_object(ser_forecast(_get_forecast(fid)))


@bp.post("/api/sales-forecasts/<fid>/lock")
def lock_forecast(fid):
    require_roles("RealEstateAnalyst")
    forecast = _get_forecast(fid)
    if forecast["forecast_status"] in ("SUPERSEDED", "ACTUALIZED"):
        raise already_terminal(
            f"SalesForecast is {forecast['forecast_status']}")
    if forecast["forecast_status"] != "DRAFT":
        raise invalid_state(
            f"Forecast in {forecast['forecast_status']} cannot be locked")
    site = db.sites[forecast["site_id"]]
    if site["site_status"] != "SCORED":
        raise invalid_state(
            f"Site in {site['site_status']} does not permit forecast lock")
    model = db.models[forecast["trade_area_model_id"]]
    if model["model_status"] != "LOCKED" or model["site_id"] != site["id"]:
        raise ApiError(
            "ERR_TRADE_AREA_NOT_LOCKED", 409,
            "Pinned trade-area model is not LOCKED for this site")
    # Authoritative cannibalization from the pinned model over live stores.
    cannibalized = compute_cannibalization(model)
    gross = forecast["gross_annual_sales_cents"]
    # Inclusive boundary: exactly 25% of gross passes the cap.
    if Decimal(cannibalized) > Decimal(gross) * Decimal(2500) / Decimal(10000):
        raise ApiError(
            "ERR_CANNIBALIZATION_EXCEEDS_CAP", 422,
            "Cannibalization exceeds 25% of gross annual sales")
    net = gross - cannibalized
    ratio = occupancy_ratio_bp(
        site["asking_rent_psf_cents"], site["cam_psf_cents"],
        site["tax_psf_cents"], site["square_footage"], net)
    forecast["cannibalized_sales_cents"] = cannibalized
    forecast["net_annual_sales_cents"] = net
    forecast["occupancy_ratio_bp"] = ratio
    forecast["occupancy_band"] = occupancy_band(ratio)
    forecast["forecast_status"] = "COMMITTEE_LOCKED"
    touch(forecast)
    # Supersede every sibling forecast in DRAFT or COMMITTEE_LOCKED.
    for f in db.forecasts.values():
        if (f["site_id"] == site["id"] and f["id"] != forecast["id"]
                and f["forecast_status"] in ("DRAFT", "COMMITTEE_LOCKED")):
            f["forecast_status"] = "SUPERSEDED"
            touch(f)
    site["site_status"] = "FORECAST_LOCKED"
    touch(site)
    return ok_object(ser_forecast(forecast))
