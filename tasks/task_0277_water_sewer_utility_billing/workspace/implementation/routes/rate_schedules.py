"""RateSchedule routes (PRD §3.1)."""
from flask import Blueprint

import db
import errors
import middleware
from response import object_response
from services import lookup
from services.common import (
    get_json_body, require_str, require_int, optional_int,
)

bp = Blueprint("rate_schedules", __name__)


def _validate_water_tiers(body):
    """water_tiers: non-empty ascending array; exactly one null terminal
    (PRD §3.1)."""
    tiers = body.get("water_tiers")
    if not isinstance(tiers, list) or len(tiers) == 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "water_tiers must be a non-empty array.")
    cleaned = []
    null_count = 0
    prev_ceiling = 0
    for i, t in enumerate(tiers):
        if not isinstance(t, dict):
            raise errors.err(errors.ERR_INVALID_REQUEST, "Each water tier must be an object.")
        rate = t.get("rate_cents_per_kgal")
        if not isinstance(rate, int) or isinstance(rate, bool):
            raise errors.err(errors.ERR_INVALID_REQUEST, "tier rate_cents_per_kgal must be an integer.")
        ceiling = t.get("up_to_gallons", None)
        if ceiling is None:
            null_count += 1
        else:
            if not isinstance(ceiling, int) or isinstance(ceiling, bool):
                raise errors.err(errors.ERR_INVALID_REQUEST, "tier up_to_gallons must be an integer or null.")
            # Ceilings must strictly ascend up to the terminal entry (PRD §3.1).
            if ceiling <= prev_ceiling:
                raise errors.err(errors.ERR_INVALID_REQUEST, "water_tiers ceilings must strictly ascend.")
            prev_ceiling = ceiling
        cleaned.append({"up_to_gallons": ceiling, "rate_cents_per_kgal": rate})
    # Exactly one terminal null tier, and it must be last.
    if null_count != 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, "water_tiers must have exactly one null terminal tier.")
    if cleaned[-1]["up_to_gallons"] is not None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "the terminal water tier must have up_to_gallons null.")
    return cleaned


@bp.post("/rate-schedules")
def create_rate_schedule():
    middleware.require_role({"BillingClerk"})
    body = get_json_body()

    name = require_str(body, "name")
    fixed_water = require_int(body, "fixed_water_charge_cents", minimum=0)
    fixed_sewer = require_int(body, "fixed_sewer_charge_cents", minimum=0)
    water_tiers = _validate_water_tiers(body)
    sewer_rate = require_int(body, "sewer_rate_cents_per_kgal", minimum=0)
    sewer_ratio = optional_int(body, "sewer_ratio_pct", default=100, minimum=0, maximum=100)

    # sewer_cap_gallons: optional; null = uncapped; when present must be >= 0.
    sewer_cap = None
    if "sewer_cap_gallons" in body and body.get("sewer_cap_gallons") is not None:
        sewer_cap = require_int(body, "sewer_cap_gallons", minimum=0)

    leak_rate = optional_int(body, "leak_adjustment_rate_pct", default=50, minimum=0, maximum=100)
    assistance_discount = optional_int(body, "assistance_discount_pct", default=25, minimum=0, maximum=100)
    arrears_threshold = optional_int(body, "arrears_shutoff_threshold_cents", default=7500, minimum=0)
    reconnect_fee = optional_int(body, "reconnect_fee_cents", default=5000, minimum=0)
    late_fee = optional_int(body, "late_fee_pct", default=5, minimum=0, maximum=100)

    rec = db.make_record({
        "name": name,
        "fixed_water_charge_cents": fixed_water,
        "fixed_sewer_charge_cents": fixed_sewer,
        "water_tiers": water_tiers,
        "sewer_rate_cents_per_kgal": sewer_rate,
        "sewer_ratio_pct": sewer_ratio,
        "sewer_cap_gallons": sewer_cap,
        "leak_adjustment_rate_pct": leak_rate,
        "assistance_discount_pct": assistance_discount,
        "arrears_shutoff_threshold_cents": arrears_threshold,
        "reconnect_fee_cents": reconnect_fee,
        "late_fee_pct": late_fee,
    })
    db.rate_schedules[rec["id"]] = rec
    return object_response(_public(rec), 201)


@bp.get("/rate-schedules/<rid>")
def get_rate_schedule(rid):
    middleware.require_role({"BillingClerk", "FieldOps", "AssistanceCaseworker", "Customer"})
    rec = lookup.rate_schedule(rid)
    return object_response(_public(rec), 200)


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}
