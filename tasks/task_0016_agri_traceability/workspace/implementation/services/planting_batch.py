"""PlantingBatch service: registration, declare-growing, derived fields."""

from flask import g

from common import (
    BATCH_CODE_RE,
    add_days_utc_midnight,
    get_json_body,
    kg_to_json,
    paginate,
    parse_iso_datetime,
    parse_pagination,
    require_field,
    sort_by_created_at,
    stamp_create,
    stamp_update,
)
from db import db
from errors import (
    ERR_BATCH_CODE_INVALID,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PLANTING_DATES_INVALID,
    ERR_VALIDATION,
    ERR_VERSION_CONFLICT,
    raise_error,
)
from services.audit import record_audit


def _serialize(batch: dict) -> dict:
    return {
        "id": batch["id"],
        "created_at": batch["created_at"],
        "updated_at": batch["updated_at"],
        "version": batch["version"],
        "batch_code": batch["batch_code"],
        "field_plot_id": batch["field_plot_id"],
        "plot_area_hectares": batch["plot_area_hectares"],
        "crop_variety": batch["crop_variety"],
        "planting_date": batch["planting_date"],
        "expected_harvest_start": batch["expected_harvest_start"],
        "expected_harvest_end": batch["expected_harvest_end"],
        "grower_id": batch["grower_id"],
        "grower_name": batch["grower_name"],
        "status": batch["status"],
        "posture": batch["posture"],
        "earliest_legal_harvest_date": batch.get("earliest_legal_harvest_date"),
        "total_quantity_kg": kg_to_json(batch.get("total_quantity_kg", 0)),
        "recall_status": batch["recall_status"],
    }


def get_batch_or_404(batch_id: str) -> dict:
    batch = db.planting_batches.get(batch_id)
    if batch is None:
        raise_error(ERR_NOT_FOUND, f"planting batch {batch_id} not found")
    return batch


def create_batch():
    body = get_json_body()
    batch_code = require_field(body, "batch_code", str)
    field_plot_id = require_field(body, "field_plot_id", str)
    plot_area_hectares = body.get("plot_area_hectares")
    if plot_area_hectares is None:
        raise_error(ERR_VALIDATION, "missing required field plot_area_hectares")
    crop_variety = require_field(body, "crop_variety", str)
    planting_date = require_field(body, "planting_date", str)
    expected_harvest_start = require_field(body, "expected_harvest_start", str)
    expected_harvest_end = require_field(body, "expected_harvest_end", str)
    grower_name = require_field(body, "grower_name", str)

    try:
        plot_area_f = float(plot_area_hectares)
    except Exception:
        raise_error(ERR_VALIDATION, "plot_area_hectares must be numeric")
    if plot_area_f <= 0:
        raise_error(ERR_VALIDATION, "plot_area_hectares must be > 0")

    pd = parse_iso_datetime(planting_date, "planting_date")
    ehs = parse_iso_datetime(expected_harvest_start, "expected_harvest_start")
    ehe = parse_iso_datetime(expected_harvest_end, "expected_harvest_end")

    # Batch code: format + uniqueness — both errors return ERR_BATCH_CODE_INVALID.
    if not BATCH_CODE_RE.match(batch_code):
        raise_error(ERR_BATCH_CODE_INVALID, "batch_code does not match ^PB-[A-Z0-9]{8}$")

    # Date sanity: planting_date <= expected_harvest_start, expected_harvest_end >= start
    if pd > ehs or ehe < ehs:
        raise_error(ERR_PLANTING_DATES_INVALID, "planting_date / expected harvest range invalid")

    with db.lock:
        # Uniqueness on batch_code
        for b in db.planting_batches.values():
            if b["batch_code"] == batch_code:
                raise_error(ERR_BATCH_CODE_INVALID, "batch_code already registered")
        batch = {
            "id": db.new_id(),
            "batch_code": batch_code,
            "field_plot_id": field_plot_id,
            "plot_area_hectares": plot_area_f,
            "crop_variety": crop_variety,
            "planting_date": planting_date,
            "expected_harvest_start": expected_harvest_start,
            "expected_harvest_end": expected_harvest_end,
            "grower_id": g.user_id,  # captured from acting Grower's X-User-ID
            "grower_name": grower_name,
            "status": "REGISTERED",
            "posture": "CLEAN",
            "earliest_legal_harvest_date": None,
            "total_quantity_kg": 0.0,
            "recall_status": "NONE",
        }
        stamp_create(batch)
        db.planting_batches[batch["id"]] = batch
        record_audit(
            "PlantingBatch", batch["id"], "CREATE", "REGISTERED",
            before_state=None,
            change_summary={"batch_code": batch_code, "grower_id": g.user_id},
        )
    return _serialize(batch)


def get_batch(batch_id):
    batch = get_batch_or_404(batch_id)
    role = g.user_role
    # Grower may only access own batch
    if role == "Grower" and batch["grower_id"] != g.user_id:
        raise_error(ERR_FORBIDDEN, "grower cannot access other growers' batches")
    return _serialize(batch)


def list_batches(args):
    limit, offset = parse_pagination()
    items = list(db.planting_batches.values())
    role = g.user_role
    if role == "Grower":
        items = [b for b in items if b["grower_id"] == g.user_id]
    status_f = args.get("status")
    posture_f = args.get("posture")
    recall_status_f = args.get("recall_status")
    if status_f is not None:
        items = [b for b in items if b["status"] == status_f]
    if posture_f is not None:
        items = [b for b in items if b["posture"] == posture_f]
    if recall_status_f is not None:
        items = [b for b in items if b["recall_status"] == recall_status_f]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return [_serialize(b) for b in page], limit, offset, total


def declare_growing(batch_id):
    body = get_json_body()
    with db.lock:
        batch = get_batch_or_404(batch_id)
        if batch["grower_id"] != g.user_id:
            raise_error(ERR_FORBIDDEN, "grower can only act on own batches")
        # OCC
        if "version" in body and body["version"] is not None:
            if body["version"] != batch["version"]:
                raise_error(ERR_VERSION_CONFLICT, "version mismatch")
        if batch["status"] != "REGISTERED":
            raise_error(ERR_INVALID_STATE, f"cannot declare-growing from status {batch['status']}")
        before = batch["status"]
        batch["status"] = "GROWING"
        stamp_update(batch)
        record_audit(
            "PlantingBatch", batch["id"], "STATE_TRANSITION", "GROWING",
            before_state=before,
            change_summary={"trigger": "declare_growing"},
        )
    return _serialize(batch)


# ---------------------------------------------------------------------------
# Derived field reconciliation helpers
# ---------------------------------------------------------------------------

def recompute_earliest_legal_harvest(batch):
    """Recompute earliest_legal_harvest_date over all applications on the batch."""
    candidates = []
    for app in db.agrochemical_applications.values():
        if app["planting_batch_id"] != batch["id"]:
            continue
        registry = db.pesticide_registry.get(app["registration_no"])
        if registry is None:
            continue
        wd = registry["withdrawal_period_days"]
        candidate = add_days_utc_midnight(app["application_date"], wd)
        candidates.append(candidate)
    batch["earliest_legal_harvest_date"] = max(candidates) if candidates else None


def recompute_total_quantity(batch):
    total = 0.0
    for hr in db.harvest_records.values():
        if hr["planting_batch_id"] == batch["id"]:
            total += float(hr["quantity_kg"])
    batch["total_quantity_kg"] = float(round(total + 0.0, 6))  # raw running sum
    # Actual JSON output rounding handled in serializer via kg_to_json


def recompute_posture(batch):
    """Recompute compliance posture based on agrochemical violations and inspection state.

    Posture is BLOCKED if a FAIL inspection is currently issued; else CLEAN.
    (FLAGGED is reserved for future use; PRD §3 leaves it as orthogonal but
    the only path that flips a non-CLEAN/non-BLOCKED posture is inspection FAIL.)
    """
    has_failed = False
    for r in db.inspection_reports.values():
        if r["planting_batch_id"] != batch["id"]:
            continue
        if r["status"] == "ISSUED" and r["result"] == "FAIL":
            has_failed = True
            break
    if has_failed:
        batch["posture"] = "BLOCKED"
    else:
        batch["posture"] = "CLEAN"
