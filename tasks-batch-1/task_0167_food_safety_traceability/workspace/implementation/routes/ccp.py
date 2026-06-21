"""CCP reading endpoint: classify, accrue excursion, auto-hold (PRD §3.5)."""
from __future__ import annotations

import math

from flask import Blueprint

import db
from errors import err
from middleware import require_auth
from response import ok_object
from services.common import (
    get_json_body, require_fields, require_str, require_number, parse_dt,
)
from services.entities import base_fields, touch
from services.serialize import public
from services.holds import issue_hold

bp = Blueprint("ccp", __name__)

MAX_EXCURSION_MINUTES = 120


@bp.post("/traceability/ccp-readings")
def create_reading():
    require_auth(["ProductionOperator", "QualityManager"])
    body = get_json_body()
    require_fields(body, ["lot_id", "ccp_type", "measured_value_c", "measured_at"])
    lot_id = require_str(body, "lot_id")
    ccp_type = require_str(body, "ccp_type")
    measured_value_c = require_number(body, "measured_value_c")
    require_str(body, "measured_at")

    if ccp_type != "TEMPERATURE":
        raise err("ERR_INVALID_REQUEST", "ccp_type must be TEMPERATURE")

    # FK resolution.
    lot = db.lots.get(lot_id)
    if lot is None:
        raise err("ERR_LOT_NOT_FOUND", "Lot not found")

    measured_at = parse_dt(body["measured_at"], "measured_at")

    facility = db.facilities[lot["facility_id"]]
    ingredient = db.ingredients[lot["ingredient_id"]]
    current = parse_dt(facility["current_utc"], "current_utc")

    # priority 14: measured_at <= current_utc and strictly > latest prior reading.
    prior = _latest_prior_reading(lot_id)
    if measured_at > current:
        raise err("ERR_READING_OUT_OF_ORDER", "measured_at is in the future")
    if prior is not None:
        prior_at = parse_dt(prior["measured_at"], "measured_at")
        if not (measured_at > prior_at):
            raise err("ERR_READING_OUT_OF_ORDER",
                      "measured_at must be strictly after the latest prior reading")

    # Classification: DEVIATION when |measured - target| > tolerance (strict).
    target = ingredient["storage_target_c"]
    tol = ingredient["storage_tolerance_c"]
    deviation = abs(measured_value_c - target) > tol
    classification = "DEVIATION" if deviation else "IN_SPEC"

    # excursion_minutes: floor of whole minutes since prior reading, only when
    # DEVIATION and a prior reading exists.
    if deviation and prior is not None:
        prior_at = parse_dt(prior["measured_at"], "measured_at")
        elapsed_seconds = (measured_at - prior_at).total_seconds()
        excursion_minutes = int(math.floor(elapsed_seconds / 60.0))
    else:
        excursion_minutes = 0

    rec = base_fields(common=True)
    rec.update({
        "lot_id": lot_id,
        "ccp_type": ccp_type,
        "measured_value_c": measured_value_c,
        "measured_at": body["measured_at"],
        "classification": classification,
        "excursion_minutes": excursion_minutes,
    })
    db.ccp_readings[rec["id"]] = rec

    # Accrue to the lot.
    lot["cumulative_excursion_minutes"] = lot.get("cumulative_excursion_minutes", 0) + excursion_minutes
    touch(lot)

    # Auto-hold once cumulative strictly exceeds 120 (PRD §3.5).
    if lot["cumulative_excursion_minutes"] > MAX_EXCURSION_MINUTES:
        issue_hold(lot["facility_id"], lot_id, "TEMPERATURE_EXCURSION")

    return ok_object(public(rec), 201)


def _latest_prior_reading(lot_id: str):
    """The lot's most recent reading by measured_at ASC, tie-break created_at ASC."""
    readings = [r for r in db.ccp_readings.values() if r["lot_id"] == lot_id]
    if not readings:
        return None
    readings.sort(key=lambda r: (r["measured_at"], r.get("created_at", ""), r.get("_seq", 0)))
    return readings[-1]
