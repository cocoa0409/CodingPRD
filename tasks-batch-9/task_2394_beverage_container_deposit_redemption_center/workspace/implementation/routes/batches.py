from flask import Blueprint, request

import calculations as calc
import clock
import db
import response
import validation as v
from db import touch
from errors import fail
from middleware import authenticate, own, own_batch
from routes.common import (filter_eq, fk, listing, lookup, require_operational,
                           unique)
from services import projections as proj

bp = Blueprint("batches", __name__)


@bp.post("/commodity-batches")
def create_batch():
    authenticate("PlantCounter", "CenterOperator", "ProgramAdmin")
    body = v.body()
    raw_center = body.get("center_id")
    if isinstance(raw_center, str):
        own(center_id=raw_center)
    center = fk("center", body, "center_id")
    v.req_str(body, "center_id")
    material = v.req_enum(body, "material", calc.COVERED_MATERIALS)
    batch_code = v.req_str(body, "batch_code")
    container_count = v.req_int(body, "container_count", minimum=1)

    require_operational(center)
    unique(db.batches, "batch_code", batch_code, "ERR_DUPLICATE_BATCH_CODE")

    if container_count > center["unbatched_container_count"]:
        fail("ERR_INSUFFICIENT_UNBATCHED_CONTAINERS",
             "The centre does not hold that many unbatched containers.")

    rec = db.new_record({
        "center_id": center["id"],
        "material": material,
        "batch_code": batch_code,
        "container_count": container_count,
        "contamination_pct": 0,
        "status": "ACCUMULATING",
        "bale_weights_kg": [],
        "bale_count": 0,
        "gross_weight_kg": 0,
        "pricing_mode": None,
        "quoted_price_cents_per_tonne": None,
        "effective_price_cents_per_tonne": 0,
        "gross_revenue_cents": 0,
        "freight_cents": 0,
        "net_revenue_cents": 0,
        "sold_at": None,
    })
    db.batches[rec["id"]] = rec
    proj.recompute_center_containers(center)
    return response.obj(db.public(rec), 201)


@bp.get("/commodity-batches/<rid>")
def get_batch(rid):
    authenticate("ProgramAdmin", "CenterOperator", "PlantCounter")
    rec = db.batches.get(rid)
    if rec is not None:
        own_batch(rec)
    rec = lookup("batch", rid)
    return response.obj(db.public(rec))


@bp.get("/commodity-batches")
def list_batches():
    authenticate("ProgramAdmin", "CenterOperator", "PlantCounter")
    rows = db.ordered(db.batches)
    for field in ("center_id", "material", "status"):
        rows = filter_eq(rows, field, request.args.get(field))
    return listing(rows)


@bp.post("/commodity-batches/<rid>/processing-actions")
def processing_action(rid):
    authenticate("PlantCounter", "ProgramAdmin")
    batch = lookup("batch", rid)
    body = v.body()
    action = v.req_enum(body, "action", ("SORT", "BALE"))
    contamination = None
    weights = None
    if action == "SORT":
        contamination = v.opt_num(body, "contamination_pct", 0, minimum=0, maximum=1)
    else:
        weights = v.req_num_list(body, "bale_weights_kg", minimum_exclusive=0)

    if action == "SORT":
        if batch["status"] != "ACCUMULATING":
            fail("ERR_INVALID_BATCH_STATE",
                 "SORT is not available from %s." % batch["status"])
        batch["contamination_pct"] = contamination
        batch["status"] = "SORTED"
    else:
        if batch["status"] != "SORTED":
            fail("ERR_INVALID_BATCH_STATE",
                 "BALE is not available from %s." % batch["status"])
        if calc.D(batch["contamination_pct"]) > calc.CONTAMINATION_LIMIT:
            fail("ERR_CONTAMINATION_LIMIT_EXCEEDED",
                 "The batch exceeds the five per cent contamination limit.")
        batch["bale_weights_kg"] = weights
        batch["bale_count"] = len(weights)
        batch["gross_weight_kg"] = float(calc.gross_weight(weights))
        batch["status"] = "BALED"

    touch(batch)
    return response.obj(db.public(batch))


@bp.post("/commodity-batches/<rid>/sale")
def sell_batch(rid):
    authenticate("CenterOperator", "ProgramAdmin")
    batch = db.batches.get(rid)
    if batch is not None:
        own_batch(batch)
    batch = lookup("batch", rid)
    body = v.body()
    period = fk("period", body, "period_id")
    pricing_mode = v.req_enum(body, "pricing_mode", ("SPOT", "INDEX"))
    quoted = v.req_int(body, "quoted_price_cents_per_tonne", minimum=0)
    v.req_str(body, "period_id")

    if batch["status"] != "BALED":
        fail("ERR_INVALID_BATCH_STATE",
             "A sale is not available from %s." % batch["status"])
    if period["status"] != "OPEN":
        fail("ERR_INVALID_PERIOD_STATE", "The reporting quarter is not OPEN.")

    result = calc.material_sale(batch["bale_weights_kg"], batch["gross_weight_kg"],
                               batch["contamination_pct"], pricing_mode, quoted)
    batch["pricing_mode"] = pricing_mode
    batch["quoted_price_cents_per_tonne"] = quoted
    batch.update(result)
    batch["status"] = "SOLD"
    batch["sold_at"] = clock.now_iso()
    touch(batch)

    proj.append_ledger_entry(period, "MATERIAL_REVENUE", result["net_revenue_cents"],
                             0, "COMMODITY_BATCH", batch["id"])
    proj.replay_period(period)
    return response.obj(db.public(batch))
