"""Hazard events, the inventory-loss waterfall and salvage settlement (PRD 3.8)."""

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

bp = Blueprint("hazard", __name__)

ZERO = Decimal("0.00")
EVENT_TYPES = ("WILDFIRE", "INSECT", "WIND_STORM", "ICE_STORM")


@bp.post("/hazard-events")
def create_event():
    middleware.require("ForestManager")
    body = validate.json_body()

    raw_stand_id = validate.opt_str_id(body, "stand_id")
    stand = None
    if raw_stand_id is not None:
        stand = services.find(store.stands, raw_stand_id, "ERR_STAND_NOT_FOUND")

    stand_id = validate.string(body, "stand_id")
    event_type = validate.enum(body, "event_type", EVENT_TYPES)
    occurred_raw, occurred_at = validate.datetime_field(body, "occurred_at")
    damaged_tons = validate.number(body, "damaged_tons", minimum=0,
                                   exclusive_min=True, dp=2)
    if stand is None:
        stand = services.find(store.stands, stand_id, "ERR_STAND_NOT_FOUND")

    if stand["status"] != "INVENTORIED":
        raise ApiError("ERR_STAND_NOT_INVENTORIED")
    if damaged_tons > calc.D(stand["net_merch_tons"]):
        raise validate.bad("damaged_tons may not exceed the stand's net_merch_tons.")

    rec = db.base_fields()
    rec.update({
        "stand_id": stand["id"],
        "event_type": event_type,
        "occurred_at": occurred_raw,
        "_occurred_dt": occurred_at,
        "damaged_tons": damaged_tons,
        "salvageable_tons": calc.salvageable_tons(event_type, damaged_tons),
        "insurance_claim_usd": calc.insurance_claim_usd(damaged_tons),
        "settled_claim_usd": None,
        "salvage_sold_tons": None,
        "inventory_shortfall_tons": ZERO,
        "reallocation_log": [],
        "status": "REPORTED",
    })
    store.hazard_events[rec["id"]] = rec

    stand["net_merch_tons"] = calc.rhu(
        calc.D(stand["net_merch_tons"]) - damaged_tons, 2)
    stand["status"] = "SALVAGE_PENDING"
    services.mark(stand)

    shortfall = calc.rhu(
        services.allocated_tons(stand) - calc.D(stand["net_merch_tons"]), 2)
    if shortfall > 0:
        rec["inventory_shortfall_tons"] = shortfall
        rec["reallocation_log"] = services.run_waterfall(stand, shortfall, "HAZARD_LOSS")

    prop = services.property_of_stand(stand)
    fund = services.fund_of_property(prop) if prop else None
    if fund is not None:
        services.recompute_fund(fund)
    return response.created(serializers.hazard_event(rec))


@bp.get("/hazard-events/<event_id>")
def get_event(event_id):
    middleware.require(*middleware.ANY_ROLE)
    event = services.find(store.hazard_events, event_id, "ERR_HAZARD_EVENT_NOT_FOUND")
    return response.ok(serializers.hazard_event(event))


@bp.post("/hazard-events/<event_id>/salvage-settle")
def settle_event(event_id):
    middleware.require("FundAdmin")
    event = services.find(store.hazard_events, event_id, "ERR_HAZARD_EVENT_NOT_FOUND")
    body = validate.json_body()
    settled_claim = validate.number(body, "settled_claim_usd", minimum=0, dp=2)
    salvage_sold = validate.number(body, "salvage_sold_tons", minimum=0, dp=2)

    if event["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if settled_claim > calc.D(event["insurance_claim_usd"]):
        raise ApiError("ERR_CLAIM_EXCEEDS_INDEMNITY")
    if salvage_sold > calc.D(event["salvageable_tons"]):
        raise ApiError("ERR_SALVAGE_EXCEEDS_RECOVERABLE")

    event["settled_claim_usd"] = settled_claim
    event["salvage_sold_tons"] = salvage_sold
    event["status"] = "SETTLED"
    services.mark(event)

    stand = store.stands.get(event["stand_id"])
    if stand is not None and stand["status"] == "SALVAGE_PENDING":
        stand["status"] = "INVENTORIED"
        services.mark(stand)
    prop = services.property_of_stand(stand) if stand else None
    fund = services.fund_of_property(prop) if prop else None
    if fund is not None:
        services.credit_fund(fund, settled_claim, operating=True)
    return response.ok(serializers.hazard_event(event))
