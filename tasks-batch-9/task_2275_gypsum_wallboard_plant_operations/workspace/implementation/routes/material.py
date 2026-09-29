"""Gypsum receipt and assay (PRD 3.2), calcination (PRD 3.3) and stucco
quality with its nonconformance cascade (PRD 3.4)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import validate as v
from db import base_entity, bump, db, ordered
from errors import fail
from middleware import ANY, acting_user_id, guard
from response import entity_response
from routes.common import (
    list_collection,
    require_batch,
    require_lot,
    require_ref,
    require_row,
)
from services.cascade import hold_run
from services.plant import (
    credit_silo,
    recompute_lot_balance,
    settle_plant,
)
from util import D, ZERO2, ZERO3, fmt_dt, rhu

bp = Blueprint("material", __name__)

SOURCE_TYPES = ("NATURAL", "SYNTHETIC")


# --------------------------------------------------------------- gypsum lots
@bp.post("/plant-ops/gypsum-lots")
@guard(("MaterialsController",))
def receive_lot():
    body = v.body_of()
    plant_id = v.text(body, "plant_id", min_len=1)
    source_type = v.enum(body, "source_type", SOURCE_TYPES)
    supplier_name = v.text(body, "supplier_name", min_len=1)
    received_tons = v.num(body, "received_tons", gt=0, scale=3)
    declared_free_moisture_pct = v.num(
        body, "declared_free_moisture_pct", ge="0.0", le="40.0"
    )
    declared_purity_pct = v.num(body, "declared_purity_pct", ge="0.0", le="100.0")

    plant = require_ref(db.plants, plant_id, "plant")

    lot = base_entity()
    lot.update(
        {
            "plant_id": plant["id"],
            "source_type": source_type,
            "supplier_name": supplier_name,
            "received_tons": received_tons,
            "declared_free_moisture_pct": declared_free_moisture_pct,
            "declared_purity_pct": declared_purity_pct,
            "free_moisture_pct": None,
            "purity_pct": None,
            "chloride_ppm": None,
            "assayed_at": None,
            "assay_count": 0,
            "quarantine_reason": None,
            "consumed_tons": ZERO3,
            "remaining_tons": received_tons,
            "status": "RECEIVED",
        }
    )
    db.gypsum_lots[lot["id"]] = lot
    return entity_response(lot, 201)


@bp.get("/plant-ops/gypsum-lots")
@guard(ANY)
def list_lots():
    return list_collection(db.gypsum_lots, ("plant_id", "status", "source_type"))


@bp.get("/plant-ops/gypsum-lots/<lot_id>")
@guard(ANY)
def read_lot(lot_id):
    return entity_response(require_lot(lot_id))


@bp.post("/plant-ops/gypsum-lots/<lot_id>/assay")
@guard(("MaterialsController",))
def assay_lot(lot_id):
    lot = require_lot(lot_id)
    body = v.body_of()
    free_moisture_pct = v.num(body, "free_moisture_pct", ge=0)
    purity_pct = v.num(body, "purity_pct", ge=0)
    chloride_ppm = v.integer(body, "chloride_ppm", ge=0)

    if int(lot["assay_count"]) >= calc.MAX_ASSAYS:
        fail("ERR_MAX_ASSAYS_REACHED", "this lot has already been assayed 3 times")
    if lot["status"] not in ("RECEIVED", "QUARANTINED"):
        fail("ERR_INVALID_STATE", "a lot in %s may not be assayed" % lot["status"])

    plant = db.plants[lot["plant_id"]]
    status, reason = calc.lot_assay_disposition(
        lot, plant, free_moisture_pct, purity_pct, chloride_ppm
    )

    lot["free_moisture_pct"] = free_moisture_pct
    lot["purity_pct"] = purity_pct
    lot["chloride_ppm"] = chloride_ppm
    lot["assayed_at"] = fmt_dt(db.now())
    lot["_assayed_at"] = db.now()
    lot["assay_count"] = int(lot["assay_count"]) + 1
    lot["status"] = status
    lot["quarantine_reason"] = reason
    bump(lot)
    return entity_response(lot)


@bp.post("/plant-ops/gypsum-lots/<lot_id>/reject")
@guard(("MaterialsController",))
def reject_lot(lot_id):
    lot = require_lot(lot_id)
    body = v.body_of()
    v.text(body, "reject_note", required=False)

    if lot["status"] != "QUARANTINED":
        fail("ERR_INVALID_STATE", "only a QUARANTINED lot may be rejected")
    if D(lot["consumed_tons"]) != Decimal(0):
        fail("ERR_INVALID_STATE", "a lot that has been drawn from may not be rejected")

    lot["remaining_tons"] = ZERO3
    lot["status"] = "REJECTED"
    bump(lot)
    return entity_response(lot)


@bp.get("/plant-ops/gypsum-lots/<lot_id>/feeds")
@guard(ANY)
def list_lot_feeds(lot_id):
    lot = require_lot(lot_id)
    base = [f for f in ordered(db.batch_feeds) if f["lot_id"] == lot["id"]]
    return list_collection(db.batch_feeds, (), base=base)


# ----------------------------------------------------------- calciner batches
def _batch_feeds(batch_id):
    return [f for f in ordered(db.batch_feeds) if f["batch_id"] == batch_id]


def _recompute_batch_metrics(batch):
    feeds = _batch_feeds(batch["id"])
    total = Decimal(0)
    for f in feeds:
        total += D(f["tons_fed"])
    batch["feed_tons_total"] = rhu(total, 3)
    plan_moisture, plan_purity, as_fed = calc.batch_blend_metrics(feeds)
    batch["feed_moisture_plan_pct"] = plan_moisture
    batch["feed_purity_plan_pct"] = plan_purity
    batch["feed_moisture_as_fed_pct"] = as_fed


@bp.post("/plant-ops/calciner-batches")
@guard(("MaterialsController",))
def plan_batch():
    body = v.body_of()
    plant_id = v.text(body, "plant_id", min_len=1)
    target_stucco_tons = v.num(body, "target_stucco_tons", gt=0)
    calcination_temp_f = v.num(body, "calcination_temp_f", ge="250.0", le="400.0")
    feed_rate_tph = v.num(body, "feed_rate_tph", gt=0)
    start_raw, start = v.instant(body, "feed_window_start")
    end_raw, end = v.instant(body, "feed_window_end")

    plant = require_ref(db.plants, plant_id, "plant")

    if end <= start:
        fail("ERR_INVALID_WINDOW", "feed_window_end must be strictly after feed_window_start")

    siblings = [
        b
        for b in ordered(db.calciner_batches)
        if b["plant_id"] == plant["id"] and b["status"] in ("PLANNED", "FEEDING", "CALCINING")
    ]
    if calc.calciner_capacity_exceeded(
        start, end, feed_rate_tph, siblings, plant["calciner_capacity_tph"]
    ):
        fail(
            "ERR_CALCINER_CAPACITY_EXCEEDED",
            "aggregate calciner feed rate exceeds plant capacity in this window",
        )

    batch = base_entity()
    batch.update(
        {
            "plant_id": plant["id"],
            "target_stucco_tons": target_stucco_tons,
            "calcination_temp_f": calcination_temp_f,
            "feed_rate_tph": feed_rate_tph,
            "feed_window_start": start_raw,
            "feed_window_end": end_raw,
            "_feed_window_start": start,
            "_feed_window_end": end,
            "feed_tons_total": ZERO3,
            "feed_moisture_plan_pct": None,
            "feed_moisture_as_fed_pct": None,
            "feed_purity_plan_pct": None,
            "stucco_yield_plan_tons": ZERO3,
            "stucco_yield_actual_tons": ZERO3,
            "stucco_quality_flag": "PENDING",
            "abort_reason": None,
            "status": "PLANNED",
        }
    )
    db.calciner_batches[batch["id"]] = batch
    return entity_response(batch, 201)


@bp.get("/plant-ops/calciner-batches")
@guard(ANY)
def list_batches():
    return list_collection(
        db.calciner_batches, ("plant_id", "status", "stucco_quality_flag")
    )


@bp.get("/plant-ops/calciner-batches/<batch_id>")
@guard(ANY)
def read_batch(batch_id):
    return entity_response(require_batch(batch_id))


@bp.post("/plant-ops/calciner-batches/<batch_id>/feeds")
@guard(("MaterialsController",))
def create_feed(batch_id):
    batch = require_batch(batch_id)
    body = v.body_of()
    lot_id = v.text(body, "lot_id", min_len=1)
    tons_fed = v.num(body, "tons_fed", gt=0, scale=3)
    measured_free_moisture_pct = v.num(
        body, "measured_free_moisture_pct", ge="0.0", le="40.0"
    )
    expected_lot_version = v.integer(body, "expected_lot_version", ge=0)

    lot = require_ref(db.gypsum_lots, lot_id, "gypsum lot")

    if lot["plant_id"] != batch["plant_id"]:
        fail("ERR_PLANT_SCOPE_MISMATCH", "the source lot belongs to a different plant")

    if expected_lot_version != int(lot["version"]):
        fail(
            "ERR_STALE_LOT_VERSION",
            "expected_lot_version %s does not match the lot's current version %s"
            % (expected_lot_version, lot["version"]),
        )

    if batch["status"] not in ("PLANNED", "FEEDING"):
        fail("ERR_INVALID_STATE", "a batch in %s accepts no further feed" % batch["status"])
    if lot["status"] != "APPROVED":
        fail("ERR_LOT_NOT_APPROVED", "the source lot is %s, not APPROVED" % lot["status"])

    assayed_at = lot.get("_assayed_at")
    if assayed_at is None or db.now() > assayed_at + timedelta(days=calc.ASSAY_VALIDITY_DAYS):
        fail("ERR_ASSAY_EXPIRED", "the source lot's assay is more than 30 days old")

    if tons_fed > D(lot["remaining_tons"]):
        fail("ERR_LOT_TONS_INSUFFICIENT", "tons_fed exceeds the lot's remaining tonnage")

    assay_moisture = D(lot["free_moisture_pct"])
    assay_purity = D(lot["purity_pct"])

    feed = base_entity(versioned=False)
    feed.update(
        {
            "batch_id": batch["id"],
            "lot_id": lot["id"],
            "tons_fed": tons_fed,
            "measured_free_moisture_pct": measured_free_moisture_pct,
            "assay_free_moisture_pct": assay_moisture,
            "assay_purity_pct": assay_purity,
            "feed_seq": len(_batch_feeds(batch["id"])) + 1,
            "dry_tons_plan": rhu(tons_fed * (Decimal(1) - assay_moisture / Decimal(100)), 6),
            "dry_tons_as_fed": rhu(
                tons_fed * (Decimal(1) - measured_free_moisture_pct / Decimal(100)), 6
            ),
        }
    )
    db.batch_feeds[feed["id"]] = feed

    # lot side
    remaining = recompute_lot_balance(lot)
    if remaining == ZERO3:
        lot["status"] = "DEPLETED"
    bump(lot)

    # batch side
    batch["status"] = "FEEDING"
    _recompute_batch_metrics(batch)
    bump(batch)

    return entity_response(feed, 201)


@bp.get("/plant-ops/calciner-batches/<batch_id>/feeds")
@guard(ANY)
def list_batch_feeds(batch_id):
    batch = require_batch(batch_id)
    return list_collection(db.batch_feeds, (), base=_batch_feeds(batch["id"]))


@bp.post("/plant-ops/calciner-batches/<batch_id>/close-feed")
@guard(("MaterialsController",))
def close_feed(batch_id):
    batch = require_batch(batch_id)
    v.body_of()

    if batch["status"] != "FEEDING":
        fail("ERR_INVALID_STATE", "only a FEEDING batch may close its feed side")
    if D(batch["feed_tons_total"]) <= Decimal(0):
        fail("ERR_INVALID_STATE", "an empty batch may not be closed")

    feeds = _batch_feeds(batch["id"])
    _recompute_batch_metrics(batch)
    batch["stucco_yield_plan_tons"] = calc.stucco_yield_tons(feeds, "PLAN")
    batch["status"] = "CALCINING"
    bump(batch)
    return entity_response(batch)


@bp.post("/plant-ops/calciner-batches/<batch_id>/stucco-tests")
@guard(("QualityInspector",))
def create_stucco_test(batch_id):
    batch = require_batch(batch_id)
    body = v.body_of()
    sample_seq = v.integer(body, "sample_seq", ge=1)
    combined_water_pct = v.num(body, "combined_water_pct", ge="0.0", le="25.0")
    free_water_pct = v.num(body, "free_water_pct", ge="0.0", le="5.0")
    set_time_minutes = v.num(body, "set_time_minutes", ge="0.0", le="60.0")
    normal_consistency_cc = v.num(body, "normal_consistency_cc", ge="40.0", le="140.0")

    for existing in db.stucco_tests.values():
        if existing["batch_id"] == batch["id"] and existing["sample_seq"] == sample_seq:
            fail("ERR_INVALID_REQUEST", "sample_seq %s already exists on this batch" % sample_seq)

    if batch["status"] not in ("CALCINING", "COMPLETED"):
        fail(
            "ERR_INVALID_STATE",
            "a batch in %s may not be sampled" % batch["status"],
        )

    result = calc.stucco_test_result(combined_water_pct, free_water_pct, set_time_minutes)
    plant = db.plants[batch["plant_id"]]

    completing = batch["status"] == "CALCINING" and result in ("PASS", "MARGINAL")
    actual_yield = None
    if completing:
        actual_yield = calc.stucco_yield_tons(_batch_feeds(batch["id"]), "AS_FED")
        if rhu(D(plant["stucco_on_hand_tons"]) + actual_yield, 3) > D(
            plant["stucco_silo_capacity_tons"]
        ):
            fail(
                "ERR_SILO_CAPACITY_EXCEEDED",
                "the silo cannot absorb this batch's actual yield",
            )

    test = base_entity(versioned=False)
    test.update(
        {
            "batch_id": batch["id"],
            "sample_seq": sample_seq,
            "combined_water_pct": combined_water_pct,
            "free_water_pct": free_water_pct,
            "set_time_minutes": set_time_minutes,
            "normal_consistency_cc": normal_consistency_cc,
            "result": result,
            "recorded_by_user_id": acting_user_id(),
            "tested_at": fmt_dt(db.now()),
        }
    )
    db.stucco_tests[test["id"]] = test

    was_completed = batch["status"] == "COMPLETED"
    batch["stucco_quality_flag"] = result

    if completing:
        batch["status"] = "COMPLETED"
        batch["stucco_yield_actual_tons"] = actual_yield
        credit_silo(plant, actual_yield)
        settle_plant(plant)
    elif was_completed and result == "FAIL":
        _stucco_nonconformance_cascade(batch, plant)

    bump(batch)
    return entity_response(test, 201)


def _stucco_nonconformance_cascade(batch, plant):
    """PRD 3.4: a retained sample failing on a COMPLETED batch pulls board back."""
    for run in ordered(db.production_runs):
        if run["calciner_batch_id"] != batch["id"]:
            continue
        if run["status"] not in ("RUNNING", "COMPLETED"):
            continue
        if run["quality_state"] not in ("UNTESTED", "IN_TEST", "RELEASED", "DOWNGRADED"):
            continue
        hold_run(run, plant, "STUCCO_NONCONFORMING")


@bp.get("/plant-ops/calciner-batches/<batch_id>/stucco-tests")
@guard(ANY)
def list_batch_stucco_tests(batch_id):
    batch = require_batch(batch_id)
    base = [t for t in ordered(db.stucco_tests) if t["batch_id"] == batch["id"]]
    return list_collection(db.stucco_tests, (), base=base)


@bp.post("/plant-ops/calciner-batches/<batch_id>/abort")
@guard(("MaterialsController",))
def abort_batch(batch_id):
    batch = require_batch(batch_id)
    body = v.body_of()
    abort_reason = v.text(body, "abort_reason", required=False)

    if batch["status"] not in ("PLANNED", "FEEDING", "CALCINING"):
        fail("ERR_INVALID_STATE", "a batch in %s may not be aborted" % batch["status"])
    if batch["status"] == "CALCINING":
        for run in db.production_runs.values():
            if run["calciner_batch_id"] == batch["id"] and run["status"] in (
                "SCHEDULED",
                "RUNNING",
            ):
                fail(
                    "ERR_INVALID_STATE",
                    "a scheduled or running production run still names this batch",
                )

    had_feeds = batch["status"] in ("FEEDING", "CALCINING")
    batch["status"] = "ABORTED"
    batch["abort_reason"] = abort_reason

    if had_feeds:
        lot_ids = []
        for feed in _batch_feeds(batch["id"]):
            if feed["lot_id"] not in lot_ids:
                lot_ids.append(feed["lot_id"])
        for lot_id in lot_ids:
            lot = db.gypsum_lots.get(lot_id)
            if lot is None:
                continue
            remaining = recompute_lot_balance(lot)
            if lot["status"] == "DEPLETED" and remaining > ZERO3:
                lot["status"] = "APPROVED"
            bump(lot)

    batch["feed_tons_total"] = ZERO3
    batch["feed_moisture_plan_pct"] = ZERO2
    batch["feed_moisture_as_fed_pct"] = ZERO2
    batch["feed_purity_plan_pct"] = ZERO2
    batch["stucco_yield_plan_tons"] = ZERO3
    batch["stucco_yield_actual_tons"] = ZERO3
    bump(batch)
    return entity_response(batch)


# --------------------------------------------------------- flat measurements
@bp.get("/plant-ops/batch-feeds")
@guard(ANY)
def list_feeds():
    return list_collection(db.batch_feeds, ("batch_id", "lot_id"))


@bp.get("/plant-ops/batch-feeds/<feed_id>")
@guard(ANY)
def read_feed(feed_id):
    return entity_response(require_row(db.batch_feeds, feed_id, "batch feed"))


@bp.get("/plant-ops/stucco-tests")
@guard(ANY)
def list_stucco_tests():
    return list_collection(db.stucco_tests, ("batch_id", "result"))


@bp.get("/plant-ops/stucco-tests/<stucco_test_id>")
@guard(ANY)
def read_stucco_test(stucco_test_id):
    return entity_response(require_row(db.stucco_tests, stucco_test_id, "stucco test"))
