"""PricingPolicy endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import STORE, new_id, now_utc
from errors import (
    ApiError,
    ERR_STATION_NOT_FOUND,
    ERR_PRICING_POLICY_NOT_FOUND,
    ERR_STATION_NOT_ACTIVE,
    ERR_STALE_STATION_VERSION,
    ERR_INVALID_REQUEST,
    ERR_INVALID_TIME_RANGE,
)
from middleware import get_caller, require_role
from response import success_object, success_list
from serializers import pricing_policy_out
from services.core import touch
from validators import (
    body, require_fields, require_string, require_enum, require_positive_int,
    require_datetime, optional_number, parse_pagination, paginate,
)

bp = Blueprint("pricing", __name__)

_ALL_READ = ["NetworkOperator", "StationManager", "ComplianceOfficer",
             "FleetAccountManager", "FleetDriver"]


@bp.post("/cng/pricing-policies")
def create_pricing_policy():
    caller = get_caller()
    require_role(caller, ["NetworkOperator"])
    data = body()
    require_fields(data, ["station_id", "access_scope", "fuel_type",
                          "price_per_gge_cents", "effective_from", "effective_to",
                          "expected_station_version"])
    station_id = require_string(data, "station_id")
    access_scope = require_enum(data, "access_scope", {"PUBLIC", "PRIVATE"})
    fuel_type = require_enum(data, "fuel_type", {"CNG", "RNG"})
    price_per_gge_cents = require_positive_int(data, "price_per_gge_cents")
    effective_from = require_datetime(data, "effective_from")
    effective_to = require_datetime(data, "effective_to")

    # Tier fields: both-or-neither; only on PRIVATE; tier_price_cents > 0 when present
    tier_threshold = optional_number(data, "tier_threshold_gge")
    tier_price_raw = data.get("tier_price_cents")
    if access_scope == "PUBLIC":
        if tier_threshold is not None or tier_price_raw is not None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Tier fields are forbidden on PUBLIC policies")
        tier_price = None
    else:
        if (tier_threshold is None) != (tier_price_raw is None):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "tier_threshold_gge and tier_price_cents must be provided together")
        if tier_price_raw is None:
            tier_price = None
        else:
            if isinstance(tier_price_raw, bool) or not isinstance(tier_price_raw, int) or tier_price_raw <= 0:
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "tier_price_cents must be a positive integer")
            tier_price = tier_price_raw

    # expected_station_version required and integer
    esv = data.get("expected_station_version")
    if isinstance(esv, bool) or not isinstance(esv, int):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_station_version must be an integer")

    # Existence (stage 4)
    station = STORE.stations.get(station_id)
    if station is None:
        raise ApiError(ERR_STATION_NOT_FOUND, 404, "Station id does not exist")

    # State (stage 6): station must be ACTIVE; OCC
    if station["status"] != "ACTIVE":
        raise ApiError(ERR_STATION_NOT_ACTIVE, 409,
                       "Station must be ACTIVE to create a pricing policy")
    if esv != station["version"]:
        raise ApiError(ERR_STALE_STATION_VERSION, 412,
                       "expected_station_version does not match current Station.version")

    # Temporal (stage 9)
    if not effective_from < effective_to:
        raise ApiError(ERR_INVALID_TIME_RANGE, 422,
                       "effective_from must be strictly earlier than effective_to")

    now = now_utc()
    # Supersede same-key ACTIVE policy
    for p in STORE.pricing_policies.values():
        if (p["station_id"] == station_id
                and p["access_scope"] == access_scope
                and p["fuel_type"] == fuel_type
                and p["status"] == "ACTIVE"):
            p["status"] = "SUPERSEDED"
            touch(p)

    policy = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "station_id": station_id,
        "access_scope": access_scope,
        "fuel_type": fuel_type,
        "price_per_gge_cents": price_per_gge_cents,
        "tier_threshold_gge": tier_threshold,
        "tier_price_cents": tier_price,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "ACTIVE",
    }
    STORE.pricing_policies[policy["id"]] = policy
    # Policy creation increments Station.version by 1
    touch(station)
    return success_object(pricing_policy_out(policy), status=201)


@bp.get("/cng/pricing-policies")
def list_pricing_policies():
    caller = get_caller()
    require_role(caller, _ALL_READ)
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    access_scope = request.args.get("access_scope")
    status = request.args.get("status")
    items = sorted(STORE.pricing_policies.values(), key=lambda p: (p["created_at"], p["id"]))
    if station_id is not None:
        items = [p for p in items if p["station_id"] == station_id]
    if access_scope is not None:
        items = [p for p in items if p["access_scope"] == access_scope]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([pricing_policy_out(p) for p in page], limit, offset, total)


@bp.get("/cng/pricing-policies/<policyId>")
def get_pricing_policy(policyId: str):
    caller = get_caller()
    require_role(caller, _ALL_READ)
    p = STORE.pricing_policies.get(policyId)
    if p is None:
        raise ApiError(ERR_PRICING_POLICY_NOT_FOUND, 404, "Pricing policy id does not exist")
    return success_object(pricing_policy_out(p))
