"""StorageBin service."""

from common import (
    BIN_CODE_RE,
    get_json_body,
    kg_to_json,
    paginate,
    parse_pagination,
    require_field,
    round_kg,
    sort_by_created_at,
    stamp_create,
    stamp_update,
)
from db import db
from errors import ERR_NOT_FOUND, ERR_VALIDATION, raise_error


def _serialize(bin_) -> dict:
    return {
        "id": bin_["id"],
        "created_at": bin_["created_at"],
        "updated_at": bin_["updated_at"],
        "version": bin_["version"],
        "bin_code": bin_["bin_code"],
        "warehouse_zone": bin_["warehouse_zone"],
        "capacity_kg": kg_to_json(bin_["capacity_kg"]),
        "occupied_kg": kg_to_json(bin_.get("occupied_kg", 0)),
        "status": bin_["status"],
    }


def get_bin_or_404(bin_id):
    b = db.storage_bins.get(bin_id)
    if b is None:
        raise_error(ERR_NOT_FOUND, f"storage bin {bin_id} not found")
    return b


def create_bin():
    body = get_json_body()
    bin_code = require_field(body, "bin_code", str)
    warehouse_zone = require_field(body, "warehouse_zone", str)
    capacity = body.get("capacity_kg")
    if capacity is None:
        raise_error(ERR_VALIDATION, "missing required field capacity_kg")
    try:
        capacity_f = float(capacity)
    except Exception:
        raise_error(ERR_VALIDATION, "capacity_kg must be numeric")
    if capacity_f <= 0:
        raise_error(ERR_VALIDATION, "capacity_kg must be > 0")
    if not BIN_CODE_RE.match(bin_code):
        raise_error(ERR_VALIDATION, "bin_code does not match ^WH-[A-Z][0-9]{3}$")
    with db.lock:
        for b in db.storage_bins.values():
            if b["bin_code"] == bin_code:
                raise_error(ERR_VALIDATION, "bin_code already exists")
        b = {
            "id": db.new_id(),
            "bin_code": bin_code,
            "warehouse_zone": warehouse_zone,
            "capacity_kg": capacity_f,
            "occupied_kg": 0.0,
            "status": "AVAILABLE",
        }
        stamp_create(b)
        db.storage_bins[b["id"]] = b
    return _serialize(b)


def get_bin(bin_id):
    b = get_bin_or_404(bin_id)
    return _serialize(b)


def recompute_bin(bin_):
    """Recompute occupied_kg and status for a bin.

    Per scaffold:
    - occupied_kg = round_half_up(sum(quantity_kg for HR in bin where parent
      batch.status NOT IN {DELIVERED, DISPOSED}), 2)
    - status: FULL if raw summed weight >= capacity; else QUARANTINE if any
      related batch.posture == BLOCKED; else AVAILABLE
    """
    raw_total = 0.0
    has_blocked = False
    for hr in db.harvest_records.values():
        if hr.get("storage_bin_id") != bin_["id"]:
            continue
        batch = db.planting_batches.get(hr["planting_batch_id"])
        if batch is None:
            continue
        if batch["status"] in {"DELIVERED", "DISPOSED"}:
            continue
        raw_total += float(hr["quantity_kg"])
        if batch.get("posture") == "BLOCKED":
            has_blocked = True
    bin_["occupied_kg"] = float(round_kg(raw_total))
    capacity = float(bin_["capacity_kg"])
    if raw_total >= capacity:
        bin_["status"] = "FULL"
    elif has_blocked:
        bin_["status"] = "QUARANTINE"
    else:
        bin_["status"] = "AVAILABLE"
    stamp_update(bin_)
