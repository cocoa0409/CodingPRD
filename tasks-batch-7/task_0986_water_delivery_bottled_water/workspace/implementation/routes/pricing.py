"""PricingConfig endpoints."""
from flask import Blueprint

import errors
from db import db
from middleware import (body_json, f_date, f_int, require_roles)
from response import list_response, ok_object
from services import base_record, ser_pricing_config

bp = Blueprint("pricing", __name__)

READ_ROLES = ("OpsAdmin", "BillingAdmin", "Dispatcher")


@bp.post("/pricing-configs")
@require_roles("OpsAdmin")
def create_pricing_config():
    d = body_json()
    # Stage 5: presence / types.
    effective_from = f_date(d, "effective_from")  # malformed -> 422
    bottle_deposit_cents = f_int(d, "bottle_deposit_cents")
    bottle_shortage_fee_cents = f_int(d, "bottle_shortage_fee_cents")
    standard_per_bottle_cents = f_int(d, "standard_per_bottle_cents")
    silver_per_bottle_cents = f_int(d, "silver_per_bottle_cents")
    gold_per_bottle_cents = f_int(d, "gold_per_bottle_cents")
    silver_volume_threshold = f_int(d, "silver_volume_threshold")
    gold_volume_threshold = f_int(d, "gold_volume_threshold")
    late_fee_flat_cents = f_int(d, "late_fee_flat_cents")
    # Stage business: positive amounts (late fee may be zero), gold > silver.
    money = [bottle_deposit_cents, bottle_shortage_fee_cents,
             standard_per_bottle_cents, silver_per_bottle_cents,
             gold_per_bottle_cents, silver_volume_threshold,
             gold_volume_threshold]
    if any(v <= 0 for v in money) or late_fee_flat_cents < 0:
        raise errors.ApiError(errors.ERR_INVALID_PRICING_CONFIG, 422,
                              "pricing config amounts must be positive")
    if gold_volume_threshold <= silver_volume_threshold:
        raise errors.ApiError(errors.ERR_INVALID_PRICING_CONFIG, 422,
                              "gold_volume_threshold must be > silver_volume_threshold")
    rec = base_record()
    rec.update({
        "effective_from": d["effective_from"],
        "_ef": effective_from,
        "bottle_deposit_cents": bottle_deposit_cents,
        "bottle_shortage_fee_cents": bottle_shortage_fee_cents,
        "standard_per_bottle_cents": standard_per_bottle_cents,
        "silver_per_bottle_cents": silver_per_bottle_cents,
        "gold_per_bottle_cents": gold_per_bottle_cents,
        "silver_volume_threshold": silver_volume_threshold,
        "gold_volume_threshold": gold_volume_threshold,
        "late_fee_flat_cents": late_fee_flat_cents,
    })
    with db.lock:
        db.pricing_configs[rec["id"]] = rec
    return ok_object(ser_pricing_config(rec), 201)


@bp.get("/pricing-configs")
@require_roles(*READ_ROLES)
def list_pricing_configs():
    return list_response(list(db.pricing_configs.values()), ser_pricing_config)


@bp.get("/pricing-configs/<cfg_id>")
@require_roles(*READ_ROLES)
def get_pricing_config(cfg_id):
    rec = db.pricing_configs.get(cfg_id)
    if rec is None:
        raise errors.not_found("pricing config not found")
    return ok_object(ser_pricing_config(rec))
