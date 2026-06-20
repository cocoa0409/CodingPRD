"""PlantingEvent endpoints + seed FIFO waterfall debit (PRD §3.3, §3.5).

PlantingEvent state machine (SCAFFOLD §1.2):
  RECORDED -> VOIDED (void, Agronomist) — restores seed lots.
"""
from flask import Blueprint, request

import db
import lookups
import serializers
from errors import err
from helpers import (
    get_json_body,
    paginate,
    parse_pagination,
    require_number,
    require_str,
)
from middleware import require_roles
from response import array_response, object_response
from services import compute

bp = Blueprint("planting_events", __name__)


@bp.post("/planting-events")
@require_roles("Agronomist")
def create_planting():
    body = get_json_body()
    crop_plan_id = require_str(body, "crop_plan_id")
    input_lot_id = require_str(body, "input_lot_id")
    acres_planted = require_number(body, "acres_planted")
    seed_rate_per_acre = require_number(body, "seed_rate_per_acre")

    # Left-to-right existence (PRD §2.7): crop_plan_id before input_lot_id.
    plan = lookups.crop_plan(crop_plan_id)
    lot = lookups.input_lot(input_lot_id)

    if acres_planted <= 0:
        raise err("ERR_INVALID_REQUEST", "acres_planted must be > 0.")
    if seed_rate_per_acre <= 0:
        raise err("ERR_INVALID_REQUEST", "seed_rate_per_acre must be > 0.")

    # Cross-aggregate coherence (PRD §3.5, §2.10 priority 6): named lot must
    # stock a SEED-category product.
    product = db.input_products.get(lot["input_product_id"])
    if product is None or product["category"] != "SEED":
        raise err(
            "ERR_PRODUCT_CATEGORY_MISMATCH",
            "Planting input_lot must stock a SEED-category product.",
        )

    need = acres_planted * seed_rate_per_acre

    # Candidate lots: named lot first, then OTHER OPEN lots of the SAME product
    # by created_at ASC (FIFO). The named lot is consumed first regardless of
    # its position in the FIFO order (PRD §3.3).
    same_product_open = [
        l
        for l in db.input_lots.values()
        if l["input_product_id"] == lot["input_product_id"]
        and l["status"] == "OPEN"
        and l["id"] != lot["id"]
    ]
    same_product_open.sort(key=lambda l: (l["created_at"], l["_seq"]))
    candidates = [lot] + same_product_open

    # Plan the debit without mutating until coverage is confirmed (atomicity:
    # no partial debit persists on insufficiency — PRD §3.3).
    remaining = need
    plan_debits = []  # (lot, take)
    for cand in candidates:
        if remaining <= 0:
            break
        if cand["status"] != "OPEN":
            continue
        take = min(cand["quantity_remaining"], remaining)
        if take <= 0:
            continue
        plan_debits.append((cand, take))
        remaining -= take

    if remaining > 0:
        raise err(
            "ERR_INSUFFICIENT_INVENTORY",
            "Seed lot waterfall cannot cover seed_units_used.",
        )

    # Commit debits. Record the exact per-lot debits on the event (internal
    # bookkeeping, not serialized) so void restores precisely what this event
    # consumed regardless of other plantings' activity.
    debit_ledger = []
    for cand, take in plan_debits:
        cand["quantity_remaining"] -= take
        if cand["quantity_remaining"] == 0:
            cand["status"] = "DEPLETED"
        db.touch(cand)
        debit_ledger.append({"lot_id": cand["id"], "amount": take})

    rec = db.new_entity(
        {
            "crop_plan_id": crop_plan_id,
            "input_lot_id": input_lot_id,
            "acres_planted": acres_planted,
            "seed_rate_per_acre": seed_rate_per_acre,
            "seed_units_used": need,
            "status": "RECORDED",
            "_debit_ledger": debit_ledger,
        }
    )
    db.planting_events[rec["id"]] = rec

    compute.recompute_planted_acres(plan)
    db.touch(plan)

    return object_response(serializers.planting_event(rec), 201)


@bp.get("/planting-events/<pid>")
@require_roles("FarmManager", "Agronomist")
def get_planting(pid):
    rec = lookups.planting_event(pid)
    return object_response(serializers.planting_event(rec))


@bp.get("/planting-events")
@require_roles("FarmManager", "Agronomist")
def list_plantings():
    limit, offset = parse_pagination()
    records = list(db.planting_events.values())
    for key in ("crop_plan_id", "input_lot_id", "status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    page, total = paginate(records, limit, offset)
    return array_response(
        [serializers.planting_event(r) for r in page], limit, offset, total
    )


@bp.post("/planting-events/<pid>/void")
@require_roles("Agronomist")
def void_planting(pid):
    rec = lookups.planting_event(pid)
    if rec["status"] != "RECORDED":
        raise err("ERR_INVALID_STATE", "Planting is not RECORDED.")

    # Restore the debited quantity. The debit waterfall did not record per-lot
    # splits on the event, so restore by reversing onto the named lot's product
    # lots in the same waterfall order, capped by quantity_received headroom.
    # To restore deterministically we re-run the same waterfall order and add
    # back to each lot up to its original capacity. Since debits flowed named
    # lot first then FIFO, reverse the consumed amount onto those same lots.
    _restore_seed(rec)

    rec["status"] = "VOIDED"
    db.touch(rec)

    plan = db.crop_plans.get(rec["crop_plan_id"])
    if plan:
        compute.recompute_planted_acres(plan)
        db.touch(plan)

    return object_response(serializers.planting_event(rec))


def _restore_seed(planting):
    """Restore the exact quantities this planting debited (PRD §3.3).

    Uses the per-lot debit ledger recorded at create time so the restoration is
    precise. Lots that were DEPLETED may revert to OPEN.
    """
    for entry in planting.get("_debit_ledger", []):
        cand = db.input_lots.get(entry["lot_id"])
        if cand is None:
            continue
        cand["quantity_remaining"] += entry["amount"]
        if cand["quantity_remaining"] > 0 and cand["status"] == "DEPLETED":
            cand["status"] = "OPEN"
        db.touch(cand)
