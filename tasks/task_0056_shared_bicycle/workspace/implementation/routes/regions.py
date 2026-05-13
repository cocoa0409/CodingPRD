"""Region endpoints (PRD §3.1, §3.11)."""
from __future__ import annotations

from flask import Blueprint, g

from constants import ANOMALY_RATE_THRESHOLD
from db import LOCK, bike_region_history, bikes, loss_records, new_id, regions
from errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    raise_err,
)
from middleware import require_role
from response import success_object
from services.regions import recompute_region_counts, serialize_region
from services.validators import (
    bump_version,
    check_version,
    ensure_non_negative_int,
    ensure_positive_int,
    get_json_body,
)
from time_utils import now_iso


bp = Blueprint("regions", __name__)


@bp.post("/regions")
def create_region():
    require_role("Admin")
    body = get_json_body()
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise_err(ERR_VALIDATION, "name is required")
    if "deployment_quota" not in body:
        raise_err(ERR_VALIDATION, "deployment_quota is required")
    quota = ensure_positive_int(body["deployment_quota"], "deployment_quota")
    if "low_density_threshold" not in body:
        raise_err(ERR_VALIDATION, "low_density_threshold is required")
    low_thr = ensure_non_negative_int(body["low_density_threshold"], "low_density_threshold")
    if "high_density_threshold" not in body:
        raise_err(ERR_VALIDATION, "high_density_threshold is required")
    high_thr = body["high_density_threshold"]
    if not isinstance(high_thr, int) or isinstance(high_thr, bool):
        raise_err(ERR_VALIDATION, "high_density_threshold must be an integer")
    if high_thr <= low_thr:
        raise_err(
            ERR_VALIDATION,
            "high_density_threshold must be strictly greater than low_density_threshold",
        )
    reward = body.get("in_zone_return_reward_cents", 0)
    penalty = body.get("out_of_zone_penalty_cents", 0)
    reward = ensure_non_negative_int(reward, "in_zone_return_reward_cents")
    penalty = ensure_non_negative_int(penalty, "out_of_zone_penalty_cents")

    with LOCK:
        # Enforce unique name across regions.
        for r in regions.values():
            if r["name"] == name:
                raise_err(ERR_VALIDATION, "Region name must be unique")
        rid = new_id()
        ts = now_iso()
        region = {
            "id": rid,
            "name": name,
            "deployment_quota": quota,
            "low_density_threshold": low_thr,
            "high_density_threshold": high_thr,
            "in_zone_return_reward_cents": reward,
            "out_of_zone_penalty_cents": penalty,
            "deployed_count": 0,
            "available_count": 0,
            # Initial posture: available=0 <= low_thr (inclusive ⇒ LOW per PRD §2.7).
            "density_posture": "LOW",
            "clock_minutes": 0,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        regions[rid] = region
    return success_object(serialize_region(region), status=201)


@bp.get("/regions/<region_id>")
def get_region(region_id):
    require_role("Admin", "Operator", "FieldStaff", "Rider")
    region = regions.get(region_id)
    if region is None:
        raise_err(ERR_NOT_FOUND, "Region not found")
    return success_object(serialize_region(region))


@bp.patch("/regions/<region_id>")
def patch_region(region_id):
    require_role("Admin")
    region = regions.get(region_id)
    if region is None:
        raise_err(ERR_NOT_FOUND, "Region not found")
    body = get_json_body()

    with LOCK:
        check_version(body, region)

        if "deployment_quota" in body:
            region["deployment_quota"] = ensure_positive_int(
                body["deployment_quota"], "deployment_quota",
            )
        new_low = region["low_density_threshold"]
        new_high = region["high_density_threshold"]
        if "low_density_threshold" in body:
            new_low = ensure_non_negative_int(
                body["low_density_threshold"], "low_density_threshold",
            )
        if "high_density_threshold" in body:
            val = body["high_density_threshold"]
            if not isinstance(val, int) or isinstance(val, bool):
                raise_err(ERR_VALIDATION, "high_density_threshold must be an integer")
            new_high = val
        if new_high <= new_low:
            raise_err(
                ERR_VALIDATION,
                "high_density_threshold must be strictly greater than low_density_threshold",
            )
        region["low_density_threshold"] = new_low
        region["high_density_threshold"] = new_high

        if "in_zone_return_reward_cents" in body:
            region["in_zone_return_reward_cents"] = ensure_non_negative_int(
                body["in_zone_return_reward_cents"], "in_zone_return_reward_cents",
            )
        if "out_of_zone_penalty_cents" in body:
            region["out_of_zone_penalty_cents"] = ensure_non_negative_int(
                body["out_of_zone_penalty_cents"], "out_of_zone_penalty_cents",
            )

        bump_version(region)
        recompute_region_counts(region_id)

    return success_object(serialize_region(region))


@bp.get("/regions/<region_id>/loss-rate")
def region_loss_rate(region_id):
    require_role("Admin")
    region = regions.get(region_id)
    if region is None:
        raise_err(ERR_NOT_FOUND, "Region not found")

    loss_count = 0
    attributed = 0
    for lr in loss_records.values():
        if lr.get("region_id") == region_id:
            loss_count += 1
            if lr.get("responsibility") != "UNKNOWN":
                attributed += 1

    # deployed_lifetime: every Bike that ever had region_id == path region.
    bike_ids_in_region: set = set()
    for bike in bikes.values():
        if bike.get("region_id") == region_id:
            bike_ids_in_region.add(bike["id"])
    bike_ids_in_region.update(bike_region_history.get(region_id, set()))
    deployed_lifetime = len(bike_ids_in_region)

    if deployed_lifetime == 0:
        provisional = 0.0
        attributed_rate = 0.0
    else:
        provisional = loss_count / deployed_lifetime
        attributed_rate = attributed / deployed_lifetime

    provisional_rounded = _round_half_up_4dp(provisional)
    attributed_rounded = _round_half_up_4dp(attributed_rate)
    anomaly = provisional > ANOMALY_RATE_THRESHOLD

    payload = {
        "region_id": region_id,
        "provisional_loss_rate": provisional_rounded,
        "attributed_loss_rate": attributed_rounded,
        "loss_count": loss_count,
        "deployed_lifetime": deployed_lifetime,
        "anomaly": anomaly,
    }
    return success_object(payload)


def _round_half_up_4dp(value: float) -> float:
    from decimal import Decimal, ROUND_HALF_UP
    quant = Decimal("0.0001")
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))
