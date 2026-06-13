"""Lot receiving, lifecycle, expiration metric, and computed fields
(PRD §3.2, §3.5).

Computed fields (available_qty, hold_status, coa_status, effective_allergen_codes,
controlling_allergen_code, effective_expiration_date, cumulative_excursion_minutes)
are stored on the lot record and maintained through the explicit side effects the
PRD specifies. They are persisted (not lazily recomputed) so that snapshots like
held_lot_count and CONSUMED transitions are deterministic.
"""
from __future__ import annotations

from datetime import datetime

import db
from errors import err
from services.common import parse_dt, add_days, round_qty
from services.entities import base_fields, touch
from services.genealogy import controlling_allergen_code

TERMINAL_LOT_STATUSES = {"REJECTED", "CONSUMED", "EXPIRED", "DESTROYED"}


def provisional_expiration(production_date: datetime, input_expiration, ingredient: dict) -> datetime:
    """Provisional effective_expiration_date (PRD §3.2):
    COALESCE(input expiration_date, production_date + ingredient.shelf_life_days)."""
    if input_expiration is not None:
        return input_expiration
    return add_days(production_date, ingredient["shelf_life_days"])


def finalized_expiration(production_date: datetime, ingredient: dict, coa: dict) -> datetime:
    """Finalized effective_expiration_date (PRD §3.2, §3.3):
    production_date + min(ingredient.shelf_life_days, coa.declared_shelf_life_days)."""
    days = min(ingredient["shelf_life_days"], coa["declared_shelf_life_days"])
    return add_days(production_date, days)


def recompute_controlling_allergen(lot: dict) -> None:
    lot["controlling_allergen_code"] = controlling_allergen_code(
        lot["facility_id"], lot.get("effective_allergen_codes", [])
    )


def create_raw_lot(facility_id, ingredient: dict, supplier, lot_code, received_qty,
                   production_date_str, expiration_date_str, supplier_id) -> dict:
    """Create a RAW_MATERIAL lot (PRD §3.2)."""
    rec = base_fields(common=True)
    production_date = parse_dt(production_date_str, "production_date")
    input_expiration = None
    if expiration_date_str is not None:
        input_expiration = parse_dt(expiration_date_str, "expiration_date")

    # expiration_date := production_date + ingredient.shelf_life_days when omitted.
    if input_expiration is None:
        expiration_date = add_days(production_date, ingredient["shelf_life_days"])
    else:
        expiration_date = input_expiration

    eff_exp = provisional_expiration(production_date, input_expiration, ingredient)

    coa_required = bool(supplier["coa_required"]) if supplier is not None else False
    coa_status = "PENDING" if (coa_required and supplier is not None) else "NOT_REQUIRED"

    allergen_codes = list(ingredient.get("declared_allergen_codes", []))

    rec.update({
        "facility_id": facility_id,
        "supplier_id": supplier_id,
        "ingredient_id": ingredient["id"],
        "lot_code": lot_code,
        "lot_kind": "RAW_MATERIAL",
        "received_qty": round_qty(received_qty),
        "available_qty": round_qty(received_qty),
        "production_date": _store_dt(production_date),
        "expiration_date": _store_dt(expiration_date),
        "effective_expiration_date": _store_dt(eff_exp),
        "cumulative_excursion_minutes": 0,
        "effective_allergen_codes": allergen_codes,
        "controlling_allergen_code": None,
        "status": "RECEIVED",
        "hold_status": "FREE",
        "coa_status": coa_status,
    })
    recompute_controlling_allergen(rec)
    db.lots[rec["id"]] = rec
    return rec


def _store_dt(dt: datetime) -> str:
    from services.common import fmt_dt
    return fmt_dt(dt)


def lot_effective_expiration(lot: dict) -> datetime:
    return parse_dt(lot["effective_expiration_date"], "effective_expiration_date")
