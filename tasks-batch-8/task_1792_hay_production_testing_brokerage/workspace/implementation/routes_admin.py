"""Admin-only surfaces: logical clock, weather reports, storage sites,
market indices, freight lanes."""

from flask import Blueprint

from auth import authorize
from db import store, new_id, stamp_new, stamp_new_light, set_clock, get_clock, iso_ms
from domain import (
    FORAGE_TYPES, reevaluate_cuttings_for_report, classify_drought_regime,
    site_occupancy, sweep_all_quotes,
)
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_SITE_NOT_FOUND,
    ERR_DUPLICATE_WEATHER_REPORT, ERR_DUPLICATE_MARKET_INDEX,
    ERR_DUPLICATE_FREIGHT_LANE,
)
from response import success
from serializers import weather_report_out, storage_site_out, market_index_out, freight_lane_out
from util import (
    D, req, as_str, as_int, as_bool, as_enum, as_number, as_date,
    parse_datetime, get_body, paginate, sorted_by_created, invalid, num_out, round2,
)

bp = Blueprint("admin", __name__)


# --- logical clock ---------------------------------------------------------

@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    authorize(["PlatformAdmin"])
    body = get_body()
    target = parse_datetime(req(body, "to_iso8601"))
    if target is None:
        invalid("to_iso8601 must be a valid ISO 8601 instant")
    set_clock(target)
    # Advancing the clock sweeps ISSUED quotes whose deadline has passed.
    sweep_all_quotes()
    return success({"current_utc": iso_ms(get_clock())}, "object", 200)


# --- WeatherReport ----------------------------------------------------------

@bp.post("/api/weather-reports")
def create_weather_report():
    authorize(["PlatformAdmin"])
    body = get_body()
    region_code = as_str(req(body, "region_code"), "region_code")
    report_date = as_date(req(body, "report_date"), "report_date")
    precipitation_mm = as_number(req(body, "precipitation_mm"), "precipitation_mm")
    drying_index = as_int(req(body, "drying_index"), "drying_index")
    if drying_index < 0 or drying_index > 100:
        invalid("drying_index must be between 0 and 100")
    for rep in store["weather_reports"].values():
        if rep["region_code"] == region_code and rep["report_date"] == report_date:
            raise ApiError(ERR_DUPLICATE_WEATHER_REPORT, 409,
                           "a weather report already exists for this region and date")
    rep = stamp_new_light({
        "id": new_id(),
        "region_code": region_code,
        "report_date": report_date,
        "precipitation_mm": precipitation_mm,
        "drying_index": drying_index,
    })
    store["weather_reports"][rep["id"]] = rep
    reevaluate_cuttings_for_report(region_code, report_date)
    return success(weather_report_out(rep), "object", 201)


# --- StorageSite ------------------------------------------------------------

@bp.post("/api/storage-sites")
def create_storage_site():
    authorize(["PlatformAdmin"])
    body = get_body()
    name = as_str(req(body, "name"), "name")
    region_code = as_str(req(body, "region_code"), "region_code")
    capacity_tons = as_number(req(body, "capacity_tons"), "capacity_tons")
    if capacity_tons <= 0:
        invalid("capacity_tons must be greater than zero")
    moisture_controlled = False
    if "moisture_controlled" in body and body["moisture_controlled"] is not None:
        moisture_controlled = as_bool(body["moisture_controlled"], "moisture_controlled")
    site = stamp_new({
        "id": new_id(),
        "name": name,
        "region_code": region_code,
        "capacity_tons": capacity_tons,
        "moisture_controlled": moisture_controlled,
    })
    store["storage_sites"][site["id"]] = site
    return success(storage_site_out(site), "object", 201)


@bp.get("/api/storage-sites")
def list_storage_sites():
    authorize(["PlatformAdmin", "BrokerOps"])
    items = sorted_by_created(store["storage_sites"].values())
    page, meta = paginate(items)
    return success([storage_site_out(s) for s in page], "array", 200, meta)


@bp.get("/api/storage-sites/<site_id>")
def get_storage_site(site_id):
    authorize(["PlatformAdmin", "BrokerOps"])
    site = store["storage_sites"].get(site_id)
    if site is None:
        raise ApiError(ERR_SITE_NOT_FOUND, 404, "storage site not found")
    return success(storage_site_out(site), "object", 200)


@bp.get("/api/storage-sites/<site_id>/occupancy")
def get_storage_site_occupancy(site_id):
    authorize(["PlatformAdmin", "BrokerOps"])
    site = store["storage_sites"].get(site_id)
    if site is None:
        raise ApiError(ERR_SITE_NOT_FOUND, 404, "storage site not found")
    occupied, lot_count = site_occupancy(site_id)
    capacity = round2(D(site["capacity_tons"]))
    available = round2(capacity - occupied)
    return success({
        "occupied_physical_tons": float(occupied),
        "capacity_tons": float(capacity),
        "available_tons": float(available),
        "lot_count": lot_count,
    }, "object", 200)


# --- MarketIndex ------------------------------------------------------------

@bp.post("/api/market-indices")
def create_market_index():
    authorize(["PlatformAdmin"])
    body = get_body()
    region_code = as_str(req(body, "region_code"), "region_code")
    forage_type = as_enum(req(body, "forage_type"), "forage_type", FORAGE_TYPES)
    effective_date = as_date(req(body, "effective_date"), "effective_date")
    price = as_int(req(body, "price_per_ton_cents"), "price_per_ton_cents")
    if price <= 0:
        invalid("price_per_ton_cents must be greater than zero")
    for idx in store["market_indices"].values():
        if (idx["region_code"] == region_code and idx["forage_type"] == forage_type
                and idx["effective_date"] == effective_date):
            raise ApiError(ERR_DUPLICATE_MARKET_INDEX, 409,
                           "a market index already exists for this region, forage type and effective date")
    regime = classify_drought_regime(region_code, forage_type, effective_date, price)
    idx = stamp_new_light({
        "id": new_id(),
        "region_code": region_code,
        "forage_type": forage_type,
        "effective_date": effective_date,
        "price_per_ton_cents": price,
        "drought_regime": regime,
    })
    store["market_indices"][idx["id"]] = idx
    return success(market_index_out(idx), "object", 201)


@bp.get("/api/market-indices")
def list_market_indices():
    from flask import request
    authorize(["PlatformAdmin", "BrokerOps", "Buyer"])
    items = list(store["market_indices"].values())
    region = request.args.get("region_code")
    forage = request.args.get("forage_type")
    if region is not None:
        items = [i for i in items if i["region_code"] == region]
    if forage is not None:
        items = [i for i in items if i["forage_type"] == forage]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([market_index_out(i) for i in page], "array", 200, meta)


# --- FreightLane ------------------------------------------------------------

@bp.post("/api/freight-lanes")
def create_freight_lane():
    authorize(["PlatformAdmin"])
    body = get_body()
    origin = as_str(req(body, "origin_region_code"), "origin_region_code")
    dest = as_str(req(body, "dest_region_code"), "dest_region_code")
    distance = as_int(req(body, "distance_miles"), "distance_miles")
    rate = as_int(req(body, "rate_per_mile_cents"), "rate_per_mile_cents")
    min_charge = as_int(req(body, "min_charge_cents"), "min_charge_cents")
    if distance <= 0:
        invalid("distance_miles must be greater than zero")
    if rate <= 0:
        invalid("rate_per_mile_cents must be greater than zero")
    if min_charge < 0:
        invalid("min_charge_cents must be zero or greater")
    for lane in store["freight_lanes"].values():
        if lane["origin_region_code"] == origin and lane["dest_region_code"] == dest:
            raise ApiError(ERR_DUPLICATE_FREIGHT_LANE, 409,
                           "a freight lane already exists for this origin/destination pair")
    lane = stamp_new({
        "id": new_id(),
        "origin_region_code": origin,
        "dest_region_code": dest,
        "distance_miles": distance,
        "rate_per_mile_cents": rate,
        "min_charge_cents": min_charge,
    })
    store["freight_lanes"][lane["id"]] = lane
    return success(freight_lane_out(lane), "object", 201)
