"""Warehouse loading, freight quoting and settlement (PRD 3.8)."""

from flask import Blueprint

import calc
import validate as v
from db import base_entity, bump, db
from errors import fail
from middleware import ANY, guard
from response import entity_response
from routes.common import list_collection, require_load_order, require_ref
from services.plant import recompute_available_msf
from util import D, ZERO2, rhu

bp = Blueprint("freight", __name__)


def _run_of(load):
    return db.production_runs[load["run_id"]]


def _spec_of(run):
    return db.product_specs[run["product_spec_id"]]


def _market_of(load):
    return db.markets[load["market_id"]]


@bp.post("/plant-ops/load-orders")
@guard(("ProductionScheduler",))
def stage_load_order():
    body = v.body_of()
    run_id = v.text(body, "run_id", min_len=1)
    market_id = v.text(body, "market_id", min_len=1)
    bundles_count = v.integer(body, "bundles_count", ge=1)
    boards_per_bundle = v.integer(body, "boards_per_bundle", ge=1)

    if boards_per_bundle % 2 != 0:
        fail("ERR_INVALID_REQUEST", "boards_per_bundle must be even")

    run = require_ref(db.production_runs, run_id, "production run")
    market = require_ref(db.markets, market_id, "market")
    spec = _spec_of(run)

    if not calc.bundle_config_valid(spec, boards_per_bundle):
        fail(
            "ERR_BUNDLE_CONFIG_INVALID",
            "boards_per_bundle must be between 2 and the SKU's maximum of %s"
            % spec["max_boards_per_bundle"],
        )

    each, bundle_msf, bundle_weight_lb, total_msf, trailer_weight_lb = calc.bundle_metrics(
        spec, boards_per_bundle, bundles_count
    )

    if trailer_weight_lb > calc.TRAILER_MAX_LB:
        fail(
            "ERR_TRAILER_WEIGHT_EXCEEDED",
            "trailer weight %s exceeds the %s pound maximum"
            % (trailer_weight_lb, calc.TRAILER_MAX_LB),
        )
    if total_msf > D(run["available_msf"]):
        fail(
            "ERR_RUN_MSF_INSUFFICIENT",
            "total_msf %s exceeds the run's available %s"
            % (total_msf, run["available_msf"]),
        )

    quoted, _fee = calc.freight_charge(market, bundle_msf, bundles_count)

    load = base_entity()
    load.update(
        {
            "run_id": run["id"],
            "market_id": market["id"],
            "bundles_count": bundles_count,
            "boards_per_bundle": boards_per_bundle,
            "loaded_bundles_count": None,
            "backhaul": False,
            "board_msf_each": each,
            "bundle_msf": bundle_msf,
            "bundle_weight_lb": bundle_weight_lb,
            "total_msf": total_msf,
            "trailer_weight_lb": trailer_weight_lb,
            "quoted_freight_usd": quoted,
            "settled_freight_usd": None,
            "overweight_fee_usd": ZERO2,
            "freight_variance_usd": None,
            "hold_source": None,
            "cancel_reason": None,
            "status": "STAGED",
        }
    )
    db.load_orders[load["id"]] = load

    recompute_available_msf(run)
    return entity_response(load, 201)


@bp.get("/plant-ops/load-orders")
@guard(ANY)
def list_load_orders():
    return list_collection(db.load_orders, ("run_id", "market_id", "status"))


@bp.get("/plant-ops/load-orders/<load_order_id>")
@guard(ANY)
def read_load_order(load_order_id):
    return entity_response(require_load_order(load_order_id))


@bp.post("/plant-ops/load-orders/<load_order_id>/load")
@guard(("ProductionScheduler",))
def record_load(load_order_id):
    load = require_load_order(load_order_id)
    body = v.body_of()
    loaded_bundles_count = v.integer(body, "loaded_bundles_count", ge=1)

    if loaded_bundles_count > int(load["bundles_count"]):
        fail("ERR_INVALID_REQUEST", "loaded_bundles_count may not exceed bundles_count")

    if load["status"] != "STAGED":
        fail("ERR_INVALID_STATE", "a load order in %s may not be loaded" % load["status"])

    run = _run_of(load)
    spec = _spec_of(run)
    each, bundle_msf, bundle_weight_lb, total_msf, trailer_weight_lb = calc.bundle_metrics(
        spec, load["boards_per_bundle"], loaded_bundles_count
    )
    if trailer_weight_lb > calc.TRAILER_MAX_LB:
        fail(
            "ERR_TRAILER_WEIGHT_EXCEEDED",
            "trailer weight %s exceeds the %s pound maximum"
            % (trailer_weight_lb, calc.TRAILER_MAX_LB),
        )

    load["loaded_bundles_count"] = loaded_bundles_count
    load["board_msf_each"] = each
    load["bundle_msf"] = bundle_msf
    load["bundle_weight_lb"] = bundle_weight_lb
    load["total_msf"] = total_msf
    load["trailer_weight_lb"] = trailer_weight_lb
    load["status"] = "LOADED"
    bump(load)

    recompute_available_msf(run)
    return entity_response(load)


@bp.post("/plant-ops/load-orders/<load_order_id>/ship")
@guard(("PlantManager",))
def ship_load(load_order_id):
    load = require_load_order(load_order_id)
    body = v.body_of()
    backhaul = v.boolean(body, "backhaul", required=False, default=False)

    if load["status"] != "LOADED":
        fail("ERR_INVALID_STATE", "a load order in %s may not be shipped" % load["status"])

    run = _run_of(load)
    if run["quality_state"] not in ("RELEASED", "DOWNGRADED"):
        fail(
            "ERR_RUN_QUALITY_NOT_RELEASED",
            "the source run's quality_state is %s" % run["quality_state"],
        )

    market = _market_of(load)
    settled, overweight_fee = calc.freight_charge(
        market,
        load["bundle_msf"],
        load["loaded_bundles_count"],
        trailer_weight_lb=load["trailer_weight_lb"],
        backhaul=backhaul,
        settled=True,
    )

    load["backhaul"] = backhaul
    load["settled_freight_usd"] = settled
    load["overweight_fee_usd"] = overweight_fee
    load["freight_variance_usd"] = rhu(settled - D(load["quoted_freight_usd"]), 2)
    load["status"] = "SHIPPED"
    bump(load)
    return entity_response(load)


@bp.post("/plant-ops/load-orders/<load_order_id>/cancel")
@guard(("ProductionScheduler",))
def cancel_load_order(load_order_id):
    load = require_load_order(load_order_id)
    body = v.body_of()
    cancel_reason = v.text(body, "cancel_reason", required=False)

    if load["status"] not in ("STAGED", "HELD", "LOADED"):
        fail("ERR_INVALID_STATE", "a load order in %s may not be cancelled" % load["status"])

    load["cancel_reason"] = cancel_reason
    load["status"] = "CANCELLED"
    bump(load)

    recompute_available_msf(_run_of(load))
    return entity_response(load)
