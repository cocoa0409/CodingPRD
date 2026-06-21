"""Production-run finalize: gates, inventory draw, and finished-lot minting
(PRD §3.4)."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import db
from errors import err
from services.common import parse_dt, add_days, round_qty, fmt_dt
from services.entities import base_fields, touch
from services.genealogy import controlling_allergen_code


def _consumed_lines_for_run(run_id: str) -> list:
    lines = [cl for cl in db.consumed_lots.values() if cl["production_run_id"] == run_id]
    # ordered by ConsumedLot.created_at ASC.
    lines.sort(key=lambda cl: (cl.get("created_at", ""), cl.get("_seq", 0)))
    return lines


def finalize_run(run: dict, facility: dict) -> dict:
    """Run all finalize gates in PRD §3.4 order, then execute the atomic draw and
    mint the finished lot. OCC is checked by the caller before this is invoked.
    """
    lines = _consumed_lines_for_run(run["id"])

    # ERR_NO_CONSUMED_LOTS.
    if len(lines) < 1:
        raise err("ERR_NO_CONSUMED_LOTS", "Run has no consumed-lot lines")

    source_lots = [db.lots[cl["source_lot_id"]] for cl in lines]
    current = parse_dt(facility["current_utc"], "current_utc")

    # ERR_SOURCE_LOT_NOT_RELEASED: every source lot in RELEASED.
    for sl in source_lots:
        if sl["status"] != "RELEASED":
            raise err("ERR_SOURCE_LOT_NOT_RELEASED", "Source lot is not RELEASED")

    # ERR_LOT_ON_HOLD: every source lot FREE.
    for sl in source_lots:
        if sl["hold_status"] != "FREE":
            raise err("ERR_LOT_ON_HOLD", "Source lot is on hold")

    # ERR_SOURCE_LOT_EXPIRED: effective_expiration_date strictly later than current.
    for sl in source_lots:
        eff = parse_dt(sl["effective_expiration_date"], "effective_expiration_date")
        if not (eff > current):
            raise err("ERR_SOURCE_LOT_EXPIRED", "Source lot is past expiration")

    # ERR_FEFO_VIOLATION: a source lot may be consumed only if no other
    # RELEASED, FREE, same-ingredient, same-facility lot has an earlier
    # effective_expiration_date. Ties broken by production_date ASC then
    # created_at ASC; never by id.
    _check_fefo(source_lots)

    # ERR_INSUFFICIENT_LOT_QTY: every line.quantity <= source lot available_qty.
    # Quantities accumulate per source lot across the run's lines.
    remaining = {}
    for sl in source_lots:
        remaining.setdefault(sl["id"], sl["available_qty"])
    for cl in lines:
        sl_id = cl["source_lot_id"]
        avail = Decimal(str(remaining[sl_id]))
        qty = Decimal(str(cl["quantity"]))
        if qty > avail:
            raise err("ERR_INSUFFICIENT_LOT_QTY",
                      "ConsumedLot quantity exceeds source lot available_qty")
        remaining[sl_id] = float((avail - qty).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))

    # ---- all gates passed: execute the atomic draw (cascade A) ----
    for cl in lines:
        sl = db.lots[cl["source_lot_id"]]
        new_avail = Decimal(str(sl["available_qty"])) - Decimal(str(cl["quantity"]))
        if new_avail < 0:
            new_avail = Decimal("0")
        sl["available_qty"] = round_qty(new_avail)
        # hop 2: a RELEASED lot reaching exactly 0 transitions to CONSUMED.
        if sl["available_qty"] == 0 and sl["status"] == "RELEASED":
            sl["status"] = "CONSUMED"
        touch(sl)

    # ---- mint the FINISHED lot ----
    ingredient = db.ingredients[run["ingredient_id"]]
    out = base_fields(common=True)
    started_at = parse_dt(run["started_at"], "started_at")
    exp = add_days(started_at, ingredient["shelf_life_days"])

    # effective_allergen_codes := distinct union of output ingredient declared
    # codes and every source lot's effective_allergen_codes.
    codes: list[str] = []
    for c in ingredient.get("declared_allergen_codes", []):
        if c not in codes:
            codes.append(c)
    for sl in source_lots:
        for c in sl.get("effective_allergen_codes", []):
            if c not in codes:
                codes.append(c)

    out.update({
        "facility_id": run["facility_id"],
        "supplier_id": None,
        "ingredient_id": run["ingredient_id"],
        "lot_code": "FIN-" + run["id"],
        "lot_kind": "FINISHED",
        "received_qty": round_qty(run["planned_output_qty"]),
        "available_qty": round_qty(run["planned_output_qty"]),
        "production_date": fmt_dt(started_at),
        "expiration_date": fmt_dt(exp),
        "effective_expiration_date": fmt_dt(exp),
        "cumulative_excursion_minutes": 0,
        "effective_allergen_codes": codes,
        "controlling_allergen_code": controlling_allergen_code(run["facility_id"], codes),
        "status": "RECEIVED",
        "hold_status": "FREE",
        "coa_status": "NOT_REQUIRED",
    })
    db.lots[out["id"]] = out

    run["status"] = "FINALIZED"
    run["output_lot_id"] = out["id"]
    touch(run)
    return run


def _check_fefo(source_lots: list) -> None:
    """Raise ERR_FEFO_VIOLATION if any consumed source lot bypasses an
    earlier-expiring eligible lot (PRD §3.4)."""
    consumed_ids = {sl["id"] for sl in source_lots}
    for sl in source_lots:
        ing = sl["ingredient_id"]
        fac = sl["facility_id"]
        sl_key = _fefo_key(sl)
        for other in db.lots.values():
            if other["id"] == sl["id"]:
                continue
            if other["id"] in consumed_ids:
                continue
            if other["status"] != "RELEASED":
                continue
            if other["hold_status"] != "FREE":
                continue
            if other["ingredient_id"] != ing or other["facility_id"] != fac:
                continue
            if _fefo_key(other) < sl_key:
                raise err("ERR_FEFO_VIOLATION",
                          "An earlier-expiring eligible lot was bypassed")


def _fefo_key(lot: dict):
    return (
        lot["effective_expiration_date"],
        lot["production_date"],
        lot.get("created_at", ""),
        lot.get("_seq", 0),
    )
