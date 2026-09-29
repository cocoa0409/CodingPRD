"""Higher-and-better-use disposition (PRD 3.9)."""

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

bp = Blueprint("hbu", __name__)

ZERO = Decimal("0.00")
MARKETING_STATES = ("LISTED", "UNDER_CONTRACT")


def _property_parcels(property_id):
    stand_ids = {s["id"] for s in services.stands_of_property(property_id)}
    return [p for p in store.hbu_parcels.values() if p["stand_id"] in stand_ids]


def _return_property_to_owned(prop, exclude_parcel_id):
    """HBU_MARKETED -> OWNED once the disposition pipeline is empty."""
    if prop is None or prop["status"] != "HBU_MARKETED":
        return
    for parcel in _property_parcels(prop["id"]):
        if parcel["id"] == exclude_parcel_id:
            continue
        if parcel["status"] in MARKETING_STATES:
            return
    prop["status"] = "OWNED"
    services.mark(prop)


@bp.post("/hbu-parcels")
def create_parcel():
    middleware.require("FundAdmin")
    body = validate.json_body()

    raw_stand_id = validate.opt_str_id(body, "stand_id")
    stand = None
    if raw_stand_id is not None:
        stand = services.find(store.stands, raw_stand_id, "ERR_STAND_NOT_FOUND")

    stand_id = validate.string(body, "stand_id")
    parcel_code = validate.string(body, "parcel_code", 1, 40)
    acres = validate.number(body, "acres", minimum=0, exclusive_min=True, dp=2)
    ask_price = validate.number(body, "ask_price_usd", minimum=0,
                                exclusive_min=True, dp=2)
    if stand is None:
        stand = services.find(store.stands, stand_id, "ERR_STAND_NOT_FOUND")

    if stand["status"] != "INVENTORIED":
        raise ApiError("ERR_STAND_NOT_INVENTORIED")
    if acres > calc.D(stand["acres"]) - calc.MIN_RETAINED_ACRES:
        raise ApiError("ERR_HBU_ACRES_EXCEED_STAND")

    rec = db.base_fields()
    rec.update({
        "stand_id": stand["id"],
        "parcel_code": parcel_code,
        "acres": acres,
        "ask_price_usd": ask_price,
        "contract_price_usd": None,
        "closing_costs_usd": None,
        "status": "IDENTIFIED",
        "withdrawn_tons": ZERO,
        "commission_usd": None,
        "net_proceeds_usd": None,
        "derived_stand_id": None,
    })
    store.hbu_parcels[rec["id"]] = rec
    return response.created(serializers.hbu_parcel(rec))


@bp.get("/hbu-parcels/<parcel_id>")
def get_parcel(parcel_id):
    middleware.require(*middleware.ANY_ROLE)
    parcel = services.find(store.hbu_parcels, parcel_id, "ERR_HBU_PARCEL_NOT_FOUND")
    return response.ok(serializers.hbu_parcel(parcel))


@bp.post("/hbu-parcels/<parcel_id>/advance")
def advance_parcel(parcel_id):
    middleware.require("FundAdmin")
    parcel = services.find(store.hbu_parcels, parcel_id, "ERR_HBU_PARCEL_NOT_FOUND")
    body = validate.json_body()
    action = validate.enum(body, "action",
                           ("LIST", "CONTRACT", "RELIST", "CLOSE", "WITHDRAW"))

    contract_price = None
    closing_costs = None
    if action == "CONTRACT":
        contract_price = validate.number(body, "contract_price_usd", minimum=0,
                                         exclusive_min=True, dp=2)
    if action == "CLOSE":
        closing_costs = validate.number(body, "closing_costs_usd", minimum=0, dp=2)

    stand = store.stands.get(parcel["stand_id"])
    prop = services.property_of_stand(stand) if stand else None
    status = parcel["status"]

    if action == "LIST":
        if status != "IDENTIFIED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if prop["status"] not in ("OWNED", "HBU_MARKETED"):
            raise ApiError("ERR_PROPERTY_NOT_OWNED")
        if prop["appraisal_status"] != "SIGNED":
            raise ApiError("ERR_APPRAISAL_NOT_SIGNED")
        parcel["status"] = "LISTED"
        if prop["status"] == "OWNED":
            prop["status"] = "HBU_MARKETED"
            services.mark(prop)

    elif action == "CONTRACT":
        if status != "LISTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        parcel["contract_price_usd"] = contract_price
        parcel["commission_usd"] = calc.hbu_commission(contract_price)
        parcel["status"] = "UNDER_CONTRACT"

    elif action == "RELIST":
        if status != "UNDER_CONTRACT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        parcel["contract_price_usd"] = None
        parcel["commission_usd"] = None
        parcel["status"] = "LISTED"

    elif action == "WITHDRAW":
        if status not in ("IDENTIFIED", "LISTED", "UNDER_CONTRACT"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        parcel["status"] = "WITHDRAWN"
        if status in MARKETING_STATES:
            _return_property_to_owned(prop, parcel["id"])

    else:  # CLOSE
        if status != "UNDER_CONTRACT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if stand["status"] != "INVENTORIED":
            raise ApiError("ERR_STAND_NOT_INVENTORIED")
        if calc.D(stand["acres"]) - calc.D(parcel["acres"]) < calc.MIN_RETAINED_ACRES:
            raise ApiError("ERR_HBU_ACRES_EXCEED_STAND")

        net_proceeds = calc.rhu(
            calc.D(parcel["contract_price_usd"]) - calc.D(parcel["commission_usd"])
            - closing_costs, 2)
        # The pro-rata share is measured against the PRE-split acreage.
        withdrawn = calc.hbu_withdrawn_tons(
            stand["net_merch_tons"], parcel["acres"], stand["acres"])

        parcel["closing_costs_usd"] = closing_costs
        parcel["net_proceeds_usd"] = net_proceeds
        parcel["withdrawn_tons"] = withdrawn
        parcel["status"] = "CLOSED"

        fund = services.fund_of_property(prop) if prop else None
        if fund is not None:
            services.credit_fund(fund, net_proceeds, operating=True)

        derived = db.base_fields()
        derived.update({
            "property_id": stand["property_id"],
            "split_from_stand_id": stand["id"],
            "stand_code": stand["stand_code"],
            "acres": parcel["acres"],
            "species_code": stand["species_code"],
            "age_years": stand["age_years"],
            "site_index": stand["site_index"],
            # Created with a completed cruise inherited from the parent and moved
            # straight to the terminal DISPOSED in the same chain of effects.
            "status": "DISPOSED",
            "plot_count": 0,
            "mean_net_tons_per_acre": stand["mean_net_tons_per_acre"],
            "cruise_confidence": stand["cruise_confidence"],
            "gross_merch_tons": withdrawn,
            "net_merch_tons": withdrawn,
        })
        store.stands[derived["id"]] = derived
        parcel["derived_stand_id"] = derived["id"]

        # Acreage is conserved exactly: parent plus derived equals the original.
        stand["acres"] = calc.rhu(calc.D(stand["acres"]) - calc.D(parcel["acres"]), 2)
        services.mark(stand)

        shortfall = calc.rhu(
            services.allocated_tons(stand) - calc.D(stand["net_merch_tons"]), 2)
        if shortfall > 0:
            services.run_waterfall(stand, shortfall, "HBU_WITHDRAWAL")
        if fund is not None:
            services.recompute_fund(fund)
        _return_property_to_owned(prop, parcel["id"])

    services.mark(parcel)
    return response.ok(serializers.hbu_parcel(parcel))
