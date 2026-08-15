"""Batch execution: start, consumption, completion, review, disposition (PRD 3.4-3.5)."""
from decimal import Decimal

from flask import Blueprint, request

from db import store, new_entity, touch, now_iso
from errors import (
    raise_error,
    ERR_BATCH_STATE,
    ERR_LOT_NOT_RELEASED,
    ERR_FORMULA_MATERIAL_MISMATCH,
    ERR_INSUFFICIENT_LOT_QUANTITY,
    ERR_INCOMPLETE_CONSUMPTION,
    ERR_LINE_NOT_CLEAN_VALIDATED,
    ERR_ALLERGEN_CHANGEOVER_REQUIRED,
    ERR_SOD_VIOLATION,
    ERR_YIELD_VARIANCE_EXCEEDED,
    ERR_ASSAY_LABEL_CLAIM_FAIL,
    ERR_COMPONENT_LOT_UNRESOLVED,
    ERR_STABILITY_NOT_COMPLETED,
    ERR_STALE_VERSION,
)
from middleware import require_roles, ANY_ROLE
from response import ok
from services import (
    batch_mo,
    compute_yield_variance_pct,
    formula_lines,
    mo_formula,
    recompute_lot_remaining,
    refresh_customer_aggregates,
)
from util import (
    body,
    dec,
    invalid,
    is_int,
    is_num,
    not_found,
    num_out,
    paginate,
    req_num,
    req_str,
    sorted_by_created,
)

bp = Blueprint("batches", __name__)

PRE_RELEASE_QUALITY = ("PENDING_QC", "ASSAY_HOLD", "QC_READY")


def _get_batch(batch_id):
    batch = store["batches"].get(batch_id)
    if batch is None:
        not_found()
    return batch


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/api/batches")
@require_roles(*ANY_ROLE)
def list_batches(user_id, role):
    items = list(store["batches"].values())
    mo_id = request.args.get("mo_id")
    if mo_id is not None:
        items = [b for b in items if b["mo_id"] == mo_id]
    production_line_id = request.args.get("production_line_id")
    if production_line_id is not None:
        items = [b for b in items if b["production_line_id"] == production_line_id]
    quality_status = request.args.get("quality_status")
    if quality_status is not None:
        items = [b for b in items if b["quality_status"] == quality_status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/api/batches/<batch_id>")
@require_roles(*ANY_ROLE)
def get_batch(user_id, role, batch_id):
    return ok(_get_batch(batch_id))


# ---------------------------------------------------------------------------
# Start (line hygiene gate, PRD 3.4)
# ---------------------------------------------------------------------------
@bp.post("/api/batches/<batch_id>/start")
@require_roles("ProductionOperator")
def start_batch(user_id, role, batch_id):
    batch = _get_batch(batch_id)
    if batch["production_status"] != "CREATED":
        raise_error(ERR_BATCH_STATE, "Only a CREATED batch may be started")
    line = store["production_lines"].get(batch["production_line_id"])
    mo = batch_mo(batch)
    formula = mo_formula(mo) if mo else None
    allergen = formula["allergen_class"] if formula else "NONE"
    if line is not None:
        if line["cleaning_status"] == "CLEAN_VALIDATED":
            pass
        elif line["cleaning_status"] == "CLEAN_PENDING_VALIDATION":
            raise_error(
                ERR_LINE_NOT_CLEAN_VALIDATED,
                "Line cleaning is pending validation",
            )
        else:  # DIRTY
            if line["current_allergen_class"] != allergen:
                raise_error(
                    ERR_ALLERGEN_CHANGEOVER_REQUIRED,
                    "Line is DIRTY with a different allergen class; changeover required",
                )
    batch["production_status"] = "IN_PROCESS"
    touch(batch)
    if mo is not None and mo["status"] == "SCHEDULED":
        mo["status"] = "IN_PRODUCTION"
        touch(mo)
    return ok(batch)


# ---------------------------------------------------------------------------
# Consumption (PRD 3.4)
# ---------------------------------------------------------------------------
@bp.post("/api/batches/<batch_id>/consumptions")
@require_roles("ProductionOperator")
def record_consumption(user_id, role, batch_id):
    batch = _get_batch(batch_id)
    if batch["production_status"] != "IN_PROCESS":
        raise_error(ERR_BATCH_STATE, "Consumption requires an IN_PROCESS batch")
    data = body()
    material_lot_id = req_str(data, "material_lot_id")
    lot = store["material_lots"].get(material_lot_id)
    if lot is None:
        not_found("material_lot_id does not identify an existing material lot")
    if lot["status"] != "RELEASED":
        raise_error(ERR_LOT_NOT_RELEASED, "The consumed lot must be RELEASED")
    mo = batch_mo(batch)
    formula = mo_formula(mo) if mo else None
    line_material_ids = {l["raw_material_id"] for l in formula_lines(formula["id"])} if formula else set()
    if lot["raw_material_id"] not in line_material_ids:
        raise_error(
            ERR_FORMULA_MATERIAL_MISMATCH,
            "The lot's raw material does not appear among the ordered formula's lines",
        )
    qty = data.get("qty_consumed")
    if not is_num(qty):
        invalid("'qty_consumed' must be a number")
    if dec(qty) > dec(lot["qty_remaining"]):
        raise_error(
            ERR_INSUFFICIENT_LOT_QUANTITY,
            "qty_consumed exceeds the lot's qty_remaining",
        )
    if not dec(qty) > 0:
        invalid("'qty_consumed' must be greater than zero")
    row = new_entity({
        "batch_id": batch_id,
        "material_lot_id": material_lot_id,
        "qty_consumed": qty,
        "status": "ACTIVE",
        "voided_by_id": None,
    })
    store["batch_consumptions"][row["id"]] = row
    recompute_lot_remaining(lot)
    touch(lot)
    return ok(row, 201)


@bp.get("/api/batches/<batch_id>/consumptions")
@require_roles(*ANY_ROLE)
def list_consumptions(user_id, role, batch_id):
    batch = _get_batch(batch_id)
    items = sorted_by_created(
        c for c in store["batch_consumptions"].values() if c["batch_id"] == batch_id
    )
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.post("/api/batches/<batch_id>/consumptions/<consumption_id>/void")
@require_roles("ProductionOperator")
def void_consumption(user_id, role, batch_id, consumption_id):
    batch = _get_batch(batch_id)
    row = store["batch_consumptions"].get(consumption_id)
    if row is None or row["batch_id"] != batch_id:
        not_found()
    if batch["production_status"] != "IN_PROCESS":
        raise_error(ERR_BATCH_STATE, "Voiding requires an IN_PROCESS batch")
    if row["status"] != "ACTIVE":
        invalid("Only an ACTIVE consumption row may be voided")
    row["status"] = "VOIDED"
    row["voided_by_id"] = user_id
    touch(row)
    lot = store["material_lots"].get(row["material_lot_id"])
    if lot is not None:
        recompute_lot_remaining(lot)
        touch(lot)
    return ok(row)


# ---------------------------------------------------------------------------
# Completion and yield amendment (PRD 3.4)
# ---------------------------------------------------------------------------
def _read_yield_figures(data):
    actual_yield_units = data.get("actual_yield_units")
    if not is_int(actual_yield_units) or actual_yield_units < 0:
        invalid("'actual_yield_units' must be a non-negative integer")
    actual_bulk_mass_g = data.get("actual_bulk_mass_g")
    if not is_num(actual_bulk_mass_g) or not dec(actual_bulk_mass_g) >= 0:
        invalid("'actual_bulk_mass_g' must be a non-negative number")
    return actual_yield_units, actual_bulk_mass_g


@bp.post("/api/batches/<batch_id>/complete")
@require_roles("ProductionOperator")
def complete_batch(user_id, role, batch_id):
    batch = _get_batch(batch_id)
    if batch["production_status"] != "IN_PROCESS":
        raise_error(ERR_BATCH_STATE, "Only an IN_PROCESS batch may be completed")
    mo = batch_mo(batch)
    formula = mo_formula(mo) if mo else None
    lines = formula_lines(formula["id"]) if formula else []
    active_rows = [
        c for c in store["batch_consumptions"].values()
        if c["batch_id"] == batch_id and c["status"] == "ACTIVE"
    ]
    consumed_materials = set()
    for row in active_rows:
        lot = store["material_lots"].get(row["material_lot_id"])
        if lot is not None:
            consumed_materials.add(lot["raw_material_id"])
    for line in lines:
        if line["raw_material_id"] not in consumed_materials:
            raise_error(
                ERR_INCOMPLETE_CONSUMPTION,
                "Every formula line requires at least one ACTIVE consumption",
            )
    data = body()
    actual_yield_units, actual_bulk_mass_g = _read_yield_figures(data)
    variance = compute_yield_variance_pct(actual_yield_units, batch["theoretical_units"])
    batch["actual_yield_units"] = actual_yield_units
    batch["actual_bulk_mass_g"] = actual_bulk_mass_g
    batch["yield_variance_pct"] = num_out(variance)
    batch["completed_at"] = now_iso()
    batch["recorded_by_id"] = user_id
    batch["production_status"] = "COMPLETED"
    touch(batch)
    line = store["production_lines"].get(batch["production_line_id"])
    if line is not None:
        line["cleaning_status"] = "DIRTY"
        line["current_allergen_class"] = formula["allergen_class"] if formula else "NONE"
        touch(line)
    return ok(batch)


@bp.put("/api/batches/<batch_id>")
@require_roles("ProductionOperator")
def amend_batch(user_id, role, batch_id):
    batch = _get_batch(batch_id)
    data = body()
    # Optimistic concurrency (PRD 2.8): checked before any business logic.
    expected = data.get("expected_batch_version")
    if not is_int(expected):
        invalid("'expected_batch_version' must carry the caller's last-observed version")
    if expected != batch["version"]:
        raise_error(
            ERR_STALE_VERSION,
            "expected_batch_version does not match the batch's current version",
        )
    if batch["production_status"] != "COMPLETED":
        raise_error(ERR_BATCH_STATE, "Only a COMPLETED batch may be amended")
    actual_yield_units, actual_bulk_mass_g = _read_yield_figures(data)
    variance = compute_yield_variance_pct(actual_yield_units, batch["theoretical_units"])
    batch["actual_yield_units"] = actual_yield_units
    batch["actual_bulk_mass_g"] = actual_bulk_mass_g
    batch["yield_variance_pct"] = num_out(variance)
    touch(batch)
    return ok(batch)


# ---------------------------------------------------------------------------
# Record review (PRD 3.5)
# ---------------------------------------------------------------------------
@bp.post("/api/batches/<batch_id>/record-review")
@require_roles("QAManager")
def record_review(user_id, role, batch_id):
    batch = _get_batch(batch_id)
    if batch["production_status"] != "COMPLETED":
        raise_error(ERR_BATCH_STATE, "Record review requires a COMPLETED batch")
    if user_id == batch["recorded_by_id"]:
        raise_error(
            ERR_SOD_VIOLATION,
            "The reviewing manager must differ from the recording operator",
        )
    variance = batch["yield_variance_pct"]
    if variance is None or abs(dec(variance)) > Decimal("10.0"):
        raise_error(
            ERR_YIELD_VARIANCE_EXCEEDED,
            "abs(yield_variance_pct) exceeds the inclusive 10.0 tolerance",
        )
    batch["production_status"] = "RECORD_REVIEWED"
    batch["reviewed_by_id"] = user_id
    touch(batch)
    return ok(batch)


# ---------------------------------------------------------------------------
# Release / reject (PRD 3.5): gates evaluated in pinned order.
# ---------------------------------------------------------------------------
@bp.post("/api/batches/<batch_id>/release")
@require_roles("QAManager")
def release_batch(user_id, role, batch_id):
    batch = _get_batch(batch_id)
    if batch["quality_status"] not in PRE_RELEASE_QUALITY or batch["production_status"] != "RECORD_REVIEWED":
        raise_error(
            ERR_BATCH_STATE,
            "Release requires quality_status in {PENDING_QC, ASSAY_HOLD, QC_READY} and production_status RECORD_REVIEWED",
        )
    # (a) Assay gate.
    assay_ok = any(
        a["batch_id"] == batch_id and a["status"] == "ACCEPTED"
        and Decimal("90.0") <= dec(a["pct_of_claim"]) <= Decimal("110.0")
        for a in store["assay_results"].values()
    )
    if not assay_ok:
        raise_error(
            ERR_ASSAY_LABEL_CLAIM_FAIL,
            "No ACCEPTED assay with pct_of_claim within [90.0, 110.0] exists",
        )
    # (b) Component-lot gate.
    for row in store["batch_consumptions"].values():
        if row["batch_id"] != batch_id or row["status"] != "ACTIVE":
            continue
        lot = store["material_lots"].get(row["material_lot_id"])
        if lot is None or lot["status"] != "RELEASED":
            raise_error(
                ERR_COMPONENT_LOT_UNRESOLVED,
                "An ACTIVE consumption's material lot is not RELEASED",
            )
    # (c) Stability gate.
    study_done = any(
        s["batch_id"] == batch_id and s["status"] == "COMPLETED"
        for s in store["stability_studies"].values()
    )
    if not study_done or not batch.get("expiry_date"):
        raise_error(
            ERR_STABILITY_NOT_COMPLETED,
            "A COMPLETED stability study with an assigned expiry is required",
        )
    batch["quality_status"] = "RELEASED"
    touch(batch)
    mo = batch_mo(batch)
    if mo is not None and mo["status"] == "IN_PRODUCTION":
        mo["status"] = "COMPLETED"
        touch(mo)
        refresh_customer_aggregates(mo["customer_id"])
    return ok(batch)


@bp.post("/api/batches/<batch_id>/reject")
@require_roles("QAManager")
def reject_batch(user_id, role, batch_id):
    batch = _get_batch(batch_id)
    if batch["quality_status"] not in PRE_RELEASE_QUALITY:
        raise_error(
            ERR_BATCH_STATE,
            "Reject requires quality_status in {PENDING_QC, ASSAY_HOLD, QC_READY}",
        )
    batch["quality_status"] = "REJECTED"
    touch(batch)
    mo = batch_mo(batch)
    if mo is not None and mo["status"] == "IN_PRODUCTION":
        mo["status"] = "CANCELLED"
        touch(mo)
        refresh_customer_aggregates(mo["customer_id"])
    return ok(batch)
