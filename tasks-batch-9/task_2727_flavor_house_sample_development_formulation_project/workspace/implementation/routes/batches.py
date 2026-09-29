"""ScaleUpBatch endpoints (PRD §3.9)."""

from flask import Blueprint, request

import serializers as S
from db import base_entity, db, touch
from errors import fail
from middleware import ALL_ROLES, auth
from response import created, ok
from routes.common import list_response, need
from services import costing, ledger
from validate import (as_decimal, as_enum, as_int, as_str, body_json, optional,
                      require)

bp = Blueprint("batches", __name__)


def _batch(batch_id):
    return need(db.batches, batch_id, "ERR_BATCH_NOT_FOUND", "scale-up batch")


@bp.post("/scale-up-batches")
def create_batch():
    auth(["TechnicalDirector"])
    body = body_json()
    formula_id = as_str(require(body, "formula_id"), "formula_id")
    target_kg = as_int(require(body, "target_kg"), "target_kg",
                       minimum=1, maximum=20000)
    formula = need(db.formulas, formula_id, "ERR_FORMULA_NOT_FOUND", "formula")
    if formula["status"] != "APPROVED":
        fail("ERR_FORMULA_NOT_APPROVED",
             "cannot scale up a formula in status %s" % formula["status"])

    batch = base_entity()
    batch.update({
        "formula_id": formula["id"],
        "target_kg": target_kg,
        "pinned_formula_version": formula["version"],
        "status": "REQUESTED",
        "material_cost_cents": None,
        "compounding_fee_pct": None,
        "compounding_fee_cents": None,
        "batch_total_cents": None,
        "production_cost_per_kg_cents": None,
        "tolerance_spec": [],
        "measured_yield_kg": None,
        "yield_variance_pct": None,
        "decision_note": None,
        "cancellation_reason": None,
    })
    db.batches[batch["id"]] = batch
    return created(S.batch_out(batch))


@bp.get("/scale-up-batches")
def list_batches():
    auth(ALL_ROLES)
    formula_id = request.args.get("formula_id")
    status = request.args.get("status")
    rows = []
    for batch in db.batches.values():
        if formula_id is not None and batch["formula_id"] != formula_id:
            continue
        if status is not None and batch["status"] != status:
            continue
        rows.append(batch)
    return list_response(rows, S.batch_out)


@bp.get("/scale-up-batches/<batch_id>")
def get_batch(batch_id):
    auth(ALL_ROLES)
    return ok(S.batch_out(_batch(batch_id)))


@bp.post("/scale-up-batches/<batch_id>/tolerance")
def set_tolerance(batch_id):
    auth(["TechnicalDirector"])
    body_json()
    batch = _batch(batch_id)
    if batch["status"] not in ("REQUESTED", "REJECTED"):
        fail("ERR_BATCH_STATE_INVALID",
             "cannot set tolerance on a batch in status %s" % batch["status"])
    formula = db.formulas.get(batch["formula_id"])
    if formula is None or formula["status"] != "APPROVED":
        fail("ERR_FORMULA_NOT_APPROVED", "the batch's formula is not APPROVED")
    if batch["pinned_formula_version"] != formula["version"]:
        fail("ERR_PINNED_FORMULA_STALE",
             "the batch pins formula version %s but the formula is at %s"
             % (batch["pinned_formula_version"], formula["version"]))

    costing.apply_production_cost(batch, formula)
    costing.build_tolerance_spec(batch, formula)
    batch["measured_yield_kg"] = None
    batch["yield_variance_pct"] = None
    batch["status"] = "TOLERANCE_SET"
    touch(batch)
    return ok(S.batch_out(batch))


@bp.post("/scale-up-batches/<batch_id>/pilot-run")
def pilot_run(batch_id):
    auth(["LabTech"])
    body = body_json()
    measured = as_decimal(require(body, "measured_yield_kg"),
                          "measured_yield_kg", 4, ge=0)
    batch = _batch(batch_id)
    if batch["status"] != "TOLERANCE_SET":
        fail("ERR_BATCH_STATE_INVALID",
             "cannot report a pilot run for a batch in status %s"
             % batch["status"])
    batch["measured_yield_kg"] = measured
    batch["yield_variance_pct"] = ledger.yield_variance_pct(measured,
                                                            batch["target_kg"])
    batch["status"] = "PILOT_RUN"
    touch(batch)
    return ok(S.batch_out(batch))


@bp.post("/scale-up-batches/<batch_id>/decision")
def decide_batch(batch_id):
    auth(["TechnicalDirector"])
    body = body_json()
    decision = as_enum(require(body, "decision"), "decision",
                       ("QUALIFIED", "REJECTED"))
    note = optional(body, "decision_note")
    if note is not None:
        note = as_str(note, "decision_note")
    batch = _batch(batch_id)
    if batch["status"] != "PILOT_RUN":
        fail("ERR_BATCH_STATE_INVALID",
             "cannot decide a batch in status %s" % batch["status"])
    batch["status"] = decision
    if note is not None:
        batch["decision_note"] = note
    touch(batch)
    return ok(S.batch_out(batch))
