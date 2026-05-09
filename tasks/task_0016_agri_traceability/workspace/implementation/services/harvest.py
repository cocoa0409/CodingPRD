"""HarvestRecord service."""

from flask import g

from common import (
    get_json_body,
    paginate,
    parse_iso_datetime,
    parse_pagination,
    require_field,
    sort_by_created_at,
    stamp_create_immutable,
    stamp_update,
)
from db import db
from errors import (
    ERR_BIN_CAPACITY_EXCEEDED,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    ERR_WITHDRAWAL_NOT_ELAPSED,
    raise_error,
)
from services.audit import record_audit
from services.planting_batch import get_batch_or_404
from services.storage_bin import get_bin_or_404, recompute_bin


def _serialize(hr: dict) -> dict:
    return {
        "id": hr["id"],
        "created_at": hr["created_at"],
        "planting_batch_id": hr["planting_batch_id"],
        "harvest_date": hr["harvest_date"],
        "quantity_kg": float(hr["quantity_kg"]),
        "quality_grade": hr["quality_grade"],
        "packaging_spec": hr["packaging_spec"],
        "storage_bin_id": hr["storage_bin_id"],
    }


def get_harvest_or_404(hr_id):
    hr = db.harvest_records.get(hr_id)
    if hr is None:
        raise_error(ERR_NOT_FOUND, f"harvest record {hr_id} not found")
    return hr


def create_harvest(batch_id):
    body = get_json_body()
    harvest_date = require_field(body, "harvest_date", str)
    quantity = body.get("quantity_kg")
    if quantity is None:
        raise_error(ERR_VALIDATION, "missing required field quantity_kg")
    quality_grade = require_field(body, "quality_grade", str)
    packaging_spec = require_field(body, "packaging_spec", str)
    storage_bin_id = require_field(body, "storage_bin_id", str)

    try:
        qty_f = float(quantity)
    except Exception:
        raise_error(ERR_VALIDATION, "quantity_kg must be numeric")
    if qty_f <= 0:
        raise_error(ERR_VALIDATION, "quantity_kg must be > 0")
    if quality_grade not in {"A", "B", "C", "REJECT"}:
        raise_error(ERR_VALIDATION, "quality_grade must be A|B|C|REJECT")

    hd = parse_iso_datetime(harvest_date, "harvest_date")

    with db.lock:
        batch = get_batch_or_404(batch_id)
        if batch["grower_id"] != g.user_id:
            raise_error(ERR_FORBIDDEN, "grower can only act on own batches")

        # State: must be GROWING or HARVESTED (subsequent harvests allowed)
        if batch["status"] not in {"GROWING", "HARVESTED"}:
            raise_error(ERR_INVALID_STATE, f"cannot record harvest on batch in {batch['status']}")

        # Withdrawal-period guard
        elhd = batch.get("earliest_legal_harvest_date")
        if elhd is not None:
            elhd_dt = parse_iso_datetime(elhd)
            if hd < elhd_dt:
                raise_error(ERR_WITHDRAWAL_NOT_ELAPSED, "harvest_date precedes earliest_legal_harvest_date")

        # Bin existence + capacity
        bin_ = get_bin_or_404(storage_bin_id)
        # QUARANTINE blocks insertion
        if bin_["status"] == "QUARANTINE":
            raise_error(ERR_BIN_CAPACITY_EXCEEDED, "destination bin is QUARANTINE")
        # Capacity check: current occupied + new <= capacity (use raw sum, not the rounded display)
        current_raw = 0.0
        for h in db.harvest_records.values():
            if h.get("storage_bin_id") != bin_["id"]:
                continue
            b = db.planting_batches.get(h["planting_batch_id"])
            if b is None or b["status"] in {"DELIVERED", "DISPOSED"}:
                continue
            current_raw += float(h["quantity_kg"])
        if current_raw + qty_f > float(bin_["capacity_kg"]):
            raise_error(ERR_BIN_CAPACITY_EXCEEDED, "harvest would exceed bin capacity")

        hr = {
            "id": db.new_id(),
            "planting_batch_id": batch_id,
            "harvest_date": harvest_date,
            "quantity_kg": qty_f,
            "quality_grade": quality_grade,
            "packaging_spec": packaging_spec,
            "storage_bin_id": storage_bin_id,
        }
        stamp_create_immutable(hr)
        db.harvest_records[hr["id"]] = hr

        # Side effects: bin occupancy + batch.total_quantity_kg + first-harvest transition
        before_status = batch["status"]
        batch["total_quantity_kg"] = float(batch.get("total_quantity_kg", 0.0)) + qty_f
        if before_status == "GROWING":
            batch["status"] = "HARVESTED"
        stamp_update(batch)
        recompute_bin(bin_)

        record_audit(
            "HarvestRecord", hr["id"], "CREATE", "CREATED",
            before_state=None,
            change_summary={"batch_id": batch_id, "quantity_kg": qty_f},
        )
        if before_status != batch["status"]:
            record_audit(
                "PlantingBatch", batch["id"], "STATE_TRANSITION", batch["status"],
                before_state=before_status,
                change_summary={"trigger": "first_harvest"},
            )
    return _serialize(hr)


def list_harvests(batch_id, args):
    get_batch_or_404(batch_id)
    limit, offset = parse_pagination()
    items = [h for h in db.harvest_records.values() if h["planting_batch_id"] == batch_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return [_serialize(h) for h in page], limit, offset, total
