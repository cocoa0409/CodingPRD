"""Stands, the immutable cruise plot sample and cruise closure (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import calc
import db
import middleware
import response
import serializers
import services
import validate
from db import store
from errors import ApiError
from routes.helpers import paginated

bp = Blueprint("stands", __name__)

ZERO = Decimal("0.00")


@bp.post("/stands")
def create_stand():
    middleware.require("ForestManager")
    body = validate.json_body()

    raw_property_id = validate.opt_str_id(body, "property_id")
    prop = None
    if raw_property_id is not None:
        prop = services.find(store.properties, raw_property_id, "ERR_PROPERTY_NOT_FOUND")

    property_id = validate.string(body, "property_id")
    stand_code = validate.string(body, "stand_code", 1, 40)
    acres = validate.number(body, "acres", minimum=0, exclusive_min=True, dp=2)
    species_code = validate.enum(body, "species_code", calc.SPECIES)
    age_years = validate.integer(body, "age_years", 0, 200)
    site_index = validate.integer(body, "site_index", 20, 140)
    if prop is None:
        prop = services.find(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")

    rec = db.base_fields()
    rec.update({
        "property_id": prop["id"],
        "split_from_stand_id": None,
        "stand_code": stand_code,
        "acres": acres,
        "species_code": species_code,
        "age_years": age_years,
        "site_index": site_index,
        "status": "CRUISE_OPEN",
        "plot_count": 0,
        "mean_net_tons_per_acre": None,
        "cruise_confidence": "NONE",
        "gross_merch_tons": ZERO,
        "net_merch_tons": ZERO,
    })
    store.stands[rec["id"]] = rec
    services.mark(prop)
    return response.created(serializers.stand(rec))


@bp.get("/stands/<stand_id>")
def get_stand(stand_id):
    middleware.require(*middleware.ANY_ROLE)
    stand = services.find(store.stands, stand_id, "ERR_STAND_NOT_FOUND")
    return response.ok(serializers.stand(stand))


@bp.post("/stands/<stand_id>/cruise-close")
def cruise_close(stand_id):
    middleware.require("ForestManager")
    stand = services.find(store.stands, stand_id, "ERR_STAND_NOT_FOUND")

    if stand["status"] != "CRUISE_OPEN":
        raise ApiError("ERR_CRUISE_ALREADY_CLOSED")
    plots = services.rows(store.cruise_plots, stand_id=stand["id"])
    if not plots:
        raise ApiError("ERR_NO_CRUISE_PLOTS")

    mean, gross, confidence, net = calc.cruise_volume(
        [p["net_tons_per_acre"] for p in plots], stand["acres"])
    stand["mean_net_tons_per_acre"] = mean
    stand["gross_merch_tons"] = gross
    stand["cruise_confidence"] = confidence
    stand["net_merch_tons"] = net
    stand["status"] = "INVENTORIED"
    services.mark(stand)
    return response.ok(serializers.stand(stand))


@bp.get("/stands/<stand_id>/cruise-plots")
def list_cruise_plots(stand_id):
    middleware.require(*middleware.ANY_ROLE)
    stand = services.find(store.stands, stand_id, "ERR_STAND_NOT_FOUND")
    return paginated(services.rows(store.cruise_plots, stand_id=stand["id"]),
                     serializers.cruise_plot)


@bp.get("/stands/<stand_id>/harvest-blocks")
def list_harvest_blocks(stand_id):
    middleware.require(*middleware.ANY_ROLE)
    stand = services.find(store.stands, stand_id, "ERR_STAND_NOT_FOUND")
    return paginated(services.rows(store.harvest_blocks, stand_id=stand["id"]),
                     serializers.harvest_block)


@bp.get("/stands/<stand_id>/carbon-dedications")
def list_stand_dedications(stand_id):
    middleware.require(*middleware.ANY_ROLE)
    stand = services.find(store.stands, stand_id, "ERR_STAND_NOT_FOUND")
    return paginated(services.rows(store.carbon_dedications, stand_id=stand["id"]),
                     serializers.carbon_dedication)


@bp.get("/stands/<stand_id>/hbu-parcels")
def list_stand_parcels(stand_id):
    middleware.require(*middleware.ANY_ROLE)
    stand = services.find(store.stands, stand_id, "ERR_STAND_NOT_FOUND")
    # Reverse-reachable on both parcel references: the stand a parcel was carved
    # from, and the derived stand a closing minted for it.
    parcels = [p for p in store.hbu_parcels.values()
               if p["stand_id"] == stand["id"] or p["derived_stand_id"] == stand["id"]]
    return paginated(db.sorted_records(parcels), serializers.hbu_parcel)


@bp.get("/stands/<stand_id>/hazard-events")
def list_stand_hazards(stand_id):
    middleware.require(*middleware.ANY_ROLE)
    stand = services.find(store.stands, stand_id, "ERR_STAND_NOT_FOUND")
    return paginated(services.rows(store.hazard_events, stand_id=stand["id"]),
                     serializers.hazard_event)


@bp.get("/stands/<stand_id>/derived-stands")
def list_derived_stands(stand_id):
    middleware.require(*middleware.ANY_ROLE)
    stand = services.find(store.stands, stand_id, "ERR_STAND_NOT_FOUND")
    return paginated(services.rows(store.stands, split_from_stand_id=stand["id"]),
                     serializers.stand)


@bp.post("/cruise-plots")
def create_cruise_plot():
    user_id = middleware.require("ForestManager")
    body = validate.json_body()

    raw_stand_id = validate.opt_str_id(body, "stand_id")
    stand = None
    if raw_stand_id is not None:
        stand = services.find(store.stands, raw_stand_id, "ERR_STAND_NOT_FOUND")

    stand_id = validate.string(body, "stand_id")
    plot_number = validate.integer(body, "plot_number", 1)
    tons_per_acre = validate.number(body, "tons_per_acre", minimum=0,
                                    exclusive_min=True, dp=2)
    defect_pct = validate.number(body, "defect_pct", minimum=0, maximum=100, dp=2)
    measured_at_raw, _measured_at = validate.datetime_field(body, "measured_at")
    if stand is None:
        stand = services.find(store.stands, stand_id, "ERR_STAND_NOT_FOUND")

    if stand["status"] != "CRUISE_OPEN":
        raise ApiError("ERR_CRUISE_ALREADY_CLOSED")
    for plot in store.cruise_plots.values():
        if plot["stand_id"] == stand["id"] and plot["plot_number"] == plot_number:
            raise ApiError("ERR_DUPLICATE_PLOT_NUMBER")

    rec = db.base_fields(with_version=False)
    rec.update({
        "stand_id": stand["id"],
        "plot_number": plot_number,
        "tons_per_acre": tons_per_acre,
        "defect_pct": defect_pct,
        "measured_at": measured_at_raw,
        "net_tons_per_acre": calc.plot_net_tons_per_acre(tons_per_acre, defect_pct),
        "measured_by_user_id": user_id,
    })
    store.cruise_plots[rec["id"]] = rec
    # plot_count is the stand's own bookkeeping; the scaffold pins no version
    # bump on it, and the cruise sample only becomes inventory at closure.
    stand["plot_count"] += 1
    return response.created(serializers.cruise_plot(rec))
