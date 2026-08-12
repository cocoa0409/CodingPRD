"""RecyclingContract routes: create, get, list, record_shipment."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import derived

bp = Blueprint("recycling_contracts", __name__)


@bp.route("/deice-ops/recycling-contracts", methods=["POST"])
def create_contract():
    middleware.require_roles("StationAdmin")
    payload = request.get_json(silent=True) or {}
    util.require_fields(
        payload,
        ["station_id", "vendor_name", "min_concentration_pct", "price_per_liter_cents", "contracted_min_liters"],
    )
    station = db.stations.get(payload["station_id"])
    if station is None:
        raise errors.not_found("station not found")
    vendor_name = payload["vendor_name"]
    if not isinstance(vendor_name, str) or not vendor_name:
        raise errors.invalid_request("vendor_name must be a non-empty string")
    min_conc = float(util.to_decimal(payload["min_concentration_pct"], "min_concentration_pct"))
    price = util.to_int(payload["price_per_liter_cents"], "price_per_liter_cents")
    if price < 0:
        raise errors.invalid_request("price_per_liter_cents must be >= 0")
    contracted_min = util.to_int(payload["contracted_min_liters"], "contracted_min_liters")
    if contracted_min <= 0:
        raise errors.invalid_request("contracted_min_liters must be positive")
    now = util.iso_now()
    contract = {
        "id": util.new_id(),
        "station_id": station["id"],
        "vendor_name": vendor_name,
        "min_concentration_pct": min_conc,
        "price_per_liter_cents": price,
        "contracted_min_liters": contracted_min,
        "delivered_liters": 0,
        "total_revenue_cents": 0,
        "last_shipment_revenue_cents": None,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    contract["_created_dt"] = db.get_clock()
    db.recycling_contracts[contract["id"]] = contract
    return response.success_object(serializers.recycling_contract(contract), 201)


@bp.route("/deice-ops/recycling-contracts/<cid>", methods=["GET"])
def get_contract(cid):
    middleware.require_roles("StationAdmin", "EnvironmentalOfficer")
    contract = db.recycling_contracts.get(cid)
    if contract is None:
        raise errors.not_found("contract not found")
    return response.success_object(serializers.recycling_contract(contract), 200)


@bp.route("/deice-ops/recycling-contracts", methods=["GET"])
def list_contracts():
    middleware.require_roles("StationAdmin", "EnvironmentalOfficer")
    limit, offset = util.get_pagination()
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    items = list(db.recycling_contracts.values())
    if station_id is not None:
        items = [c for c in items if c["station_id"] == station_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: c["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.recycling_contract(c) for c in page], limit, offset, total)


@bp.route("/deice-ops/recycling-contracts/<cid>/record_shipment", methods=["POST"])
def record_shipment(cid):
    middleware.require_roles("StationAdmin")
    contract = db.recycling_contracts.get(cid)
    if contract is None:
        raise errors.not_found("contract not found")
    payload = request.get_json(silent=True) or {}
    util.require_fields(payload, ["volume_liters", "concentration_pct"])
    volume = util.to_decimal(payload["volume_liters"], "volume_liters")
    if volume <= 0:
        raise errors.invalid_request("volume_liters must be positive")
    concentration = util.to_decimal(payload["concentration_pct"], "concentration_pct")
    if contract["status"] != "ACTIVE":
        raise errors.invalid_state("contract must be ACTIVE to record a shipment")
    if concentration < Decimal(str(contract["min_concentration_pct"])):
        raise errors.recycle_quality()
    station = db.stations.get(contract["station_id"])
    derived.recompute_station_all(contract["station_id"])
    pool = Decimal(str(station["collected_pool_liters"]))
    if volume > pool:
        raise errors.insufficient_collected_glycol()
    revenue = int(
        (volume * Decimal(contract["price_per_liter_cents"])).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    contract["delivered_liters"] = float(Decimal(str(contract["delivered_liters"])) + volume)
    contract["total_revenue_cents"] = int(contract["total_revenue_cents"]) + revenue
    contract["last_shipment_revenue_cents"] = revenue
    if Decimal(str(contract["delivered_liters"])) >= Decimal(str(contract["contracted_min_liters"])):
        contract["status"] = "FULFILLED"
    contract["version"] += 1
    contract["updated_at"] = util.iso_now()
    derived.recompute_station_all(contract["station_id"])
    return response.success_object(serializers.recycling_contract(contract), 200)
