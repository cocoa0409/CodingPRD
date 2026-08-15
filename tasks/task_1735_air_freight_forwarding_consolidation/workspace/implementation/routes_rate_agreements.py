"""Rate agreement filing (PRD §3.1)."""
from flask import Blueprint

import services as svc
from db import store
from errors import ApiError, ERR_INVALID_REQUEST, ERR_RATE_AGREEMENT_OVERLAP
from middleware import (
    get_body,
    opt_num,
    req_datetime,
    req_nonempty_str,
    req_num,
    require_roles,
)
from money import dec
from response import ok

bp = Blueprint("rate_agreements", __name__)


def _parse_weight_breaks(body):
    if "weight_breaks" not in body or not isinstance(body["weight_breaks"], list):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'weight_breaks' is required and must be a list.", 400)
    raw = body["weight_breaks"]
    if len(raw) < 1:
        raise ApiError(ERR_INVALID_REQUEST, "Field 'weight_breaks' must contain at least one tier.", 400)
    tiers = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ApiError(ERR_INVALID_REQUEST, f"weight_breaks[{i}] must be an object.", 400)
        try:
            min_w = dec(item.get("min_weight_kg"))
            rate = dec(item.get("rate_per_kg"))
        except Exception:
            raise ApiError(
                ERR_INVALID_REQUEST,
                f"weight_breaks[{i}] requires numeric min_weight_kg and rate_per_kg.",
                400,
            )
        if min_w < 0 or rate < 0:
            raise ApiError(
                ERR_INVALID_REQUEST,
                f"weight_breaks[{i}] values must be >= 0.",
                400,
            )
        tiers.append({"min_weight_kg": min_w, "rate_per_kg": rate})
    mins = [t["min_weight_kg"] for t in tiers]
    if any(mins[i] >= mins[i + 1] for i in range(len(mins) - 1)):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "weight_breaks min_weight_kg values must be distinct and ascending.",
            400,
        )
    return tiers


@bp.post("/rate-agreements")
@require_roles("PricingManager")
def create_rate_agreement():
    body = get_body()
    # Existence (priority 3): body shipper reference resolves.
    if isinstance(body.get("shipper_id"), str):
        svc.get_shipper(body["shipper_id"])
    shipper_id = req_nonempty_str(body, "shipper_id")
    origin_code = req_nonempty_str(body, "origin_code")
    destination_code = req_nonempty_str(body, "destination_code")
    weight_breaks = _parse_weight_breaks(body)
    min_charge_amount = req_num(body, "min_charge_amount", minimum=0)
    fuel_surcharge_pct = req_num(body, "fuel_surcharge_pct", minimum=0)
    security_fee_amount = req_num(body, "security_fee_amount", minimum=0)
    spot_surcharge_pct = opt_num(body, "spot_surcharge_pct", default=dec(0), minimum=0)
    valid_from_utc = req_datetime(body, "valid_from_utc")
    valid_to_utc = req_datetime(body, "valid_to_utc")
    if not valid_to_utc > valid_from_utc:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "valid_to_utc must be strictly after valid_from_utc.",
            400,
        )
    # Half-open [valid_from, valid_to) non-overlap per (shipper, lane);
    # touching windows (existing.valid_to == new.valid_from) are allowed.
    for a in store.rate_agreements.values():
        if (a.shipper_id == shipper_id and a.origin_code == origin_code
                and a.destination_code == destination_code
                and valid_from_utc < a.valid_to_utc and valid_to_utc > a.valid_from_utc):
            raise ApiError(
                ERR_RATE_AGREEMENT_OVERLAP,
                "Validity window overlaps an existing rate agreement for this shipper and lane.",
                409,
            )
    a = svc.fresh_rec(
        shipper_id=shipper_id,
        origin_code=origin_code,
        destination_code=destination_code,
        weight_breaks=weight_breaks,
        min_charge_amount=min_charge_amount,
        fuel_surcharge_pct=fuel_surcharge_pct,
        security_fee_amount=security_fee_amount,
        spot_surcharge_pct=spot_surcharge_pct,
        valid_from_utc=valid_from_utc,
        valid_to_utc=valid_to_utc,
    )
    store.rate_agreements[a.id] = a
    return ok(svc.rate_agreement_json(a), 201)
