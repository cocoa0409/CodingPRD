"""Treatment batches: screening, dosing, yield, purity and QC adjudication."""

from flask import Blueprint, g

import db
import response
from db import store, touch
from errors import (
    ERR_ADDITIVE_DOSE_OUT_OF_SPEC,
    ERR_BATCH_QC_ALREADY_DECIDED,
    ERR_COVERED_CAPACITY_EXCEEDED,
    ERR_DEPOT_CLOSED,
    ERR_PURITY_BELOW_SPEC,
    ERR_REWORK_LIMIT_EXCEEDED,
    ERR_RUN_INVALID_STATE,
    ERR_SCREEN_SPEC_NOT_ALLOWED,
    ERR_UNCOVERED_STORAGE_NOT_ALLOWED,
    fail,
    invalid,
)
from middleware import auth, require_distinct_actor
from services import calc, derive, serialize
from util import D, ZERO, body, enum, filter_str, number, require, text

bp = Blueprint("batches", __name__)

DECISIONS = ("PASS", "FAIL", "REWORK")


def _maybe_auto_close(run):
    if run["status"] == "HOISTED" and derive.run_open_batch_count(run["id"]) == 0:
        run["status"] = "CLOSED"
        touch(run)


@bp.post("/salt/treatment-batches")
@auth("QualityLab")
def create_batch():
    payload = body()
    require(payload, ["production_run_id", "depot_id", "product_line",
                      "screen_spec", "anticaking_ppm", "corrosion_inhibitor_pct",
                      "input_tons", "moisture_pct", "storage_kind"])
    product_line = enum(payload, "product_line", calc.PRODUCT_LINES)
    screen_spec = enum(payload, "screen_spec", calc.SCREEN_SPECS)
    storage_kind = enum(payload, "storage_kind", calc.STORAGE_KINDS)
    anticaking = number(payload, "anticaking_ppm", minv=0, maxv=200)
    inhibitor = number(payload, "corrosion_inhibitor_pct", minv=0, maxv=5)
    input_tons = number(payload, "input_tons", gt=0)
    moisture = number(payload, "moisture_pct", minv=0, maxv=12)
    if "rework_count" in payload:
        invalid("rework_count is server-owned and may not be supplied")

    run = derive.get_run(payload["production_run_id"])
    depot = derive.get_depot(payload["depot_id"])

    if run["status"] not in ("HOISTED", "CLOSED"):
        fail(ERR_RUN_INVALID_STATE,
             "the parent run must be HOISTED or CLOSED to open a batch")
    if depot["depot_state"] == "CLOSED":
        fail(ERR_DEPOT_CLOSED, "the receiving depot is closed")

    spec = calc.PRODUCT_SPECS[product_line]
    if screen_spec not in spec["screens"]:
        fail(ERR_SCREEN_SPEC_NOT_ALLOWED,
             "screen_spec %s is not permitted for %s" % (screen_spec, product_line))
    lo, hi = spec["anticaking"]
    if D(anticaking) < lo or D(anticaking) > hi:
        fail(ERR_ADDITIVE_DOSE_OUT_OF_SPEC,
             "anticaking_ppm must be between %s and %s for %s"
             % (lo, hi, product_line))
    lo, hi = spec["inhibitor"]
    if D(inhibitor) < lo or D(inhibitor) > hi:
        fail(ERR_ADDITIVE_DOSE_OUT_OF_SPEC,
             "corrosion_inhibitor_pct must be between %s and %s for %s"
             % (lo, hi, product_line))
    if storage_kind == "OPEN_PAD" and spec["moisture_sensitive"]:
        fail(ERR_UNCOVERED_STORAGE_NOT_ALLOWED,
             "%s may never occupy open-pad storage" % product_line)

    panel = derive.get_panel(run["panel_id"])
    batch = db.stamp()
    batch.update({
        "production_run_id": run["id"],
        "depot_id": depot["id"],
        "product_line": product_line,
        "screen_spec": screen_spec,
        "anticaking_ppm": anticaking,
        "corrosion_inhibitor_pct": inhibitor,
        "input_tons": input_tons,
        "moisture_pct": moisture,
        "storage_kind": storage_kind,
        "yield_tons": calc.treatment_yield_tons(input_tons, screen_spec, moisture, 0),
        "purity_pct_nacl": calc.treatment_purity(panel["grade_pct_nacl"], screen_spec),
        "qc_state": "PENDING",
        "rework_count": 0,
        "created_by_user_id": g.user_id,
        "qc_decided_by_user_id": None,
    })
    store.batches[batch["id"]] = batch
    return response.created(serialize.batch_json(batch))


@bp.get("/salt/treatment-batches/<batch_id>")
@auth()
def read_batch(batch_id):
    return response.ok(serialize.batch_json(derive.get_batch(batch_id)))


@bp.get("/salt/treatment-batches")
@auth()
def list_batches():
    rows = list(store.batches.values())
    for name in ("production_run_id", "depot_id", "qc_state", "product_line",
                 "screen_spec"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return response.page(db.by_seq(rows), serialize.batch_json)


@bp.post("/salt/treatment-batches/<batch_id>/qc-decision")
@auth("QualityLab")
def qc_decision(batch_id):
    payload = body()

    # stage 3 -- the decider may never be the batch's creator
    known = store.batches.get(batch_id)
    if known is not None:
        require_distinct_actor(known["created_by_user_id"],
                               "the deciding user may not be the batch's creator")

    require(payload, ["decision"])
    decision = enum(payload, "decision", DECISIONS)
    if "note" in payload and payload["note"] is not None:
        text(payload, "note", minlen=0, maxlen=2000)

    batch = derive.get_batch(batch_id)
    run = derive.get_run(batch["production_run_id"])
    depot = derive.get_depot(batch["depot_id"])

    if batch["qc_state"] in ("PASSED", "FAILED"):
        fail(ERR_BATCH_QC_ALREADY_DECIDED,
             "batch quality control is already final (%s)" % batch["qc_state"])
    if decision == "REWORK" and int(batch["rework_count"]) >= 2:
        fail(ERR_REWORK_LIMIT_EXCEEDED,
             "the batch has already been reworked twice")

    if decision == "PASS":
        spec = calc.PRODUCT_SPECS[batch["product_line"]]
        if depot["depot_state"] == "CLOSED":
            fail(ERR_DEPOT_CLOSED, "the receiving depot is closed")
        if D(batch["purity_pct_nacl"]) < spec["min_purity"]:
            fail(ERR_PURITY_BELOW_SPEC,
                 "purity %s is below the %s minimum of %s"
                 % (batch["purity_pct_nacl"], batch["product_line"],
                    spec["min_purity"]))
        if batch["storage_kind"] != "COVERED" and spec["moisture_sensitive"]:
            fail(ERR_UNCOVERED_STORAGE_NOT_ALLOWED,
                 "%s may never occupy open-pad storage" % batch["product_line"])
        yield_tons = D(batch["yield_tons"])
        if batch["storage_kind"] == "COVERED":
            stored = derive.depot_covered_stored(depot["id"])
            capacity = D(depot["covered_capacity_tons"])
        else:
            stored = derive.depot_open_pad_stored(depot["id"])
            capacity = D(depot["open_pad_capacity_tons"])
        if stored + yield_tons > capacity:
            fail(ERR_COVERED_CAPACITY_EXCEEDED,
                 "stored %s plus %s exceeds the depot capacity %s"
                 % (stored, yield_tons, capacity))

        batch["qc_state"] = "PASSED"
        batch["qc_decided_by_user_id"] = g.user_id
        touch(batch)

        lot = db.stamp()
        lot.update({
            "depot_id": depot["id"],
            "treatment_batch_id": batch["id"],
            "product_line": batch["product_line"],
            "purity_pct_nacl": batch["purity_pct_nacl"],
            "storage_kind": batch["storage_kind"],
            "tons_on_hand": yield_tons,
            "lot_state": "AVAILABLE",
            "quarantine_reason": None,
        })
        store.lots[lot["id"]] = lot
        derive.maybe_auto_surge(depot)
        touch(depot)
        _maybe_auto_close(run)

    elif decision == "FAIL":
        batch["qc_state"] = "FAILED"
        batch["qc_decided_by_user_id"] = g.user_id
        touch(batch)
        _maybe_auto_close(run)

    else:
        batch["rework_count"] = int(batch["rework_count"]) + 1
        batch["yield_tons"] = calc.treatment_yield_tons(
            batch["input_tons"], batch["screen_spec"], batch["moisture_pct"],
            batch["rework_count"])
        batch["qc_decided_by_user_id"] = g.user_id
        touch(batch)

    return response.ok(serialize.batch_json(batch))
