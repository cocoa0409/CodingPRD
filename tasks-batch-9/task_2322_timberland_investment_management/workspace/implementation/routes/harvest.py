"""Harvest reservation, commitment and closure (PRD 3.4)."""

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

bp = Blueprint("harvest", __name__)


@bp.post("/harvest-blocks")
def create_block():
    middleware.require("ForestManager")
    body = validate.json_body()

    raw_stand_id = validate.opt_str_id(body, "stand_id")
    stand = None
    if raw_stand_id is not None:
        stand = services.find(store.stands, raw_stand_id, "ERR_STAND_NOT_FOUND")

    stand_id = validate.string(body, "stand_id")
    start_raw, start_date = validate.date_field(body, "planned_start_date")
    end_raw, end_date = validate.date_field(body, "planned_end_date")
    planned_tons = validate.number(body, "planned_tons", minimum=0,
                                   exclusive_min=True, dp=2)
    product_mix = validate.enum(body, "product_mix",
                                ("SAWTIMBER", "MIXED", "PULPWOOD"))
    stumpage = validate.number(body, "expected_stumpage_price_usd_per_ton",
                               minimum=0, exclusive_min=True, dp=2)
    price_index = validate.number(body, "price_index_factor",
                                  minimum="0.10", maximum="3.00", dp=2)
    haul_miles = validate.integer(body, "expected_haul_distance_miles", 0, 600)
    growth_variant = validate.enum(body, "growth_variant", calc.GROWTH_VARIANTS)
    expected_stand_version = validate.integer(body, "expected_stand_version")
    if stand is None:
        stand = services.find(store.stands, stand_id, "ERR_STAND_NOT_FOUND")

    if expected_stand_version != stand["version"]:
        raise ApiError("ERR_STALE_STAND_VERSION")
    if stand["status"] != "INVENTORIED":
        raise ApiError("ERR_STAND_NOT_INVENTORIED")
    if end_date < start_date:
        raise ApiError("ERR_HARVEST_WINDOW_INVALID")

    # The re-entry buffer: two full growing years past the prior window's close,
    # with a start landing exactly on the boundary itself a conflict.
    for prior in services.rows(store.harvest_blocks, stand_id=stand["id"]):
        if prior["status"] not in ("RESERVED", "COMMITTED", "COMPLETED"):
            continue
        boundary = db.add_months(prior["_planned_end"], calc.REENTRY_BUFFER_MONTHS)
        if start_date <= boundary:
            raise ApiError("ERR_REENTRY_BUFFER_CONFLICT")

    buckets = services.stand_buckets(stand)
    if planned_tons > buckets["available_tons"]:
        raise ApiError("ERR_INSUFFICIENT_AVAILABLE_TONS")

    years = calc.years_to_start(db.logical_date(), start_date)
    projected_volume = calc.growth_projection_volume(
        stand["net_merch_tons"], stand["acres"], stand["species_code"],
        years, growth_variant)
    projected_available = calc.rhu(
        calc.D(projected_volume) - buckets["reserved_tons"] - buckets["committed_tons"]
        - buckets["dedicated_tons"] - buckets["hbu_withdrawn_tons"], 2)

    revenue = calc.net_revenue(planned_tons, stumpage, price_index,
                               product_mix, haul_miles)

    rec = db.base_fields()
    rec.update({
        "stand_id": stand["id"],
        "planned_start_date": start_raw,
        "planned_end_date": end_raw,
        "_planned_start": start_date,
        "_planned_end": end_date,
        "planned_tons": planned_tons,
        "actual_tons": None,
        "product_mix": product_mix,
        "expected_stumpage_price_usd_per_ton": stumpage,
        "price_index_factor": price_index,
        "realized_price_index_factor": None,
        "expected_haul_distance_miles": haul_miles,
        "growth_variant": growth_variant,
        "years_to_start": years,
        "projected_available_tons": projected_available,
        "status": "RESERVED",
        "provisional_net_revenue_usd": revenue["net_revenue_usd"],
        "final_net_revenue_usd": None,
        "severance_tax_usd": revenue["severance_tax_usd"],
        "voided_reason": None,
    })
    store.harvest_blocks[rec["id"]] = rec
    services.mark(stand)
    # Filing a fresh block is how a planner signals the plan is repaired.
    prop = services.property_of_stand(stand)
    if prop is not None:
        services.set_harvest_plan_status(prop, "ALIGNED")
        fund = services.fund_of_property(prop)
        if fund is not None:
            services.recompute_fund(fund)
    return response.created(serializers.harvest_block(rec))


@bp.get("/harvest-blocks/<block_id>")
def get_block(block_id):
    middleware.require(*middleware.ANY_ROLE)
    block = services.find(store.harvest_blocks, block_id, "ERR_HARVEST_BLOCK_NOT_FOUND")
    return response.ok(serializers.harvest_block(block))


@bp.post("/harvest-blocks/<block_id>/commit")
def commit_block(block_id):
    middleware.require("ForestManager")
    block = services.find(store.harvest_blocks, block_id, "ERR_HARVEST_BLOCK_NOT_FOUND")
    stand = store.stands.get(block["stand_id"])
    prop = services.property_of_stand(stand)

    if block["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if stand["status"] != "INVENTORIED":
        raise ApiError("ERR_STAND_NOT_INVENTORIED")
    if prop["certification_posture"] == "SUSPENDED":
        raise ApiError("ERR_CERTIFICATION_SUSPENDED")
    if services.blackout_conflict(prop, block["_planned_start"], block["_planned_end"]):
        raise ApiError("ERR_LEASE_BLACKOUT_CONFLICT")

    block["status"] = "COMMITTED"
    services.mark(block)
    services.mark(stand)
    return response.ok(serializers.harvest_block(block))


@bp.post("/harvest-blocks/<block_id>/close")
def close_block(block_id):
    middleware.require("ForestManager")
    block = services.find(store.harvest_blocks, block_id, "ERR_HARVEST_BLOCK_NOT_FOUND")
    body = validate.json_body()
    action = validate.enum(body, "action", ("COMPLETE", "CANCEL"))

    stand = store.stands.get(block["stand_id"])
    prop = services.property_of_stand(stand)
    fund = services.fund_of_property(prop) if prop else None

    if action == "COMPLETE":
        actual_tons = validate.number(body, "actual_tons", minimum=0, dp=2)
        realized_index = validate.number(body, "realized_price_index_factor",
                                         minimum=0, dp=2)
        if block["status"] != "COMMITTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if prop["certification_posture"] == "SUSPENDED":
            raise ApiError("ERR_CERTIFICATION_SUSPENDED")
        if actual_tons > calc.D(block["planned_tons"]):
            raise ApiError("ERR_ACTUAL_TONS_EXCEED_PLANNED")

        revenue = calc.net_revenue(actual_tons, block["expected_stumpage_price_usd_per_ton"],
                                   realized_index, block["product_mix"],
                                   block["expected_haul_distance_miles"])
        block["actual_tons"] = actual_tons
        block["realized_price_index_factor"] = realized_index
        block["final_net_revenue_usd"] = revenue["net_revenue_usd"]
        block["severance_tax_usd"] = revenue["severance_tax_usd"]
        block["status"] = "COMPLETED"
        services.mark(block)
        stand["net_merch_tons"] = calc.rhu(
            calc.D(stand["net_merch_tons"]) - actual_tons, 2)
        services.mark(stand)
        if fund is not None:
            services.credit_fund(fund, revenue["net_revenue_usd"], operating=True)
    else:
        if block["status"] not in ("RESERVED", "COMMITTED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if fund is not None:
            services.recompute_fund(fund)
            if fund["harvest_acceleration_required"]:
                raise ApiError("ERR_YIELD_SHORTFALL_LOCK")
        block["status"] = "CANCELLED"
        services.mark(block)
        services.mark(stand)

    return response.ok(serializers.harvest_block(block))
