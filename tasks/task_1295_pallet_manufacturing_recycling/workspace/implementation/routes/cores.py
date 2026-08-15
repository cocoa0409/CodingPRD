"""CorePurchaseBatch and CoreUnit endpoints."""

from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import (
    require_roles, get_json_body, parse_pagination, paginate,
    req_field, opt_field, as_str, as_int, as_enum,
)
from response import success
from services.calc import (
    compute_final_settlement, compute_grade_yield_variance_bp,
)
from services.helpers import (
    init_common, touch, serialize, serialize_list, sorted_by_creation,
    get_or_404, ref_or_404,
)

bp = Blueprint("cores", __name__)

SPECIES = ("PINE", "OAK", "MIXED")
SORT_GRADES = ("A", "B", "SCRAP")


def _validate_grade_mix(mix):
    if not isinstance(mix, dict):
        raise_err("ERR_INVALID_REQUEST", "estimated_grade_mix must be an object")
    for key in ("A", "B", "SCRAP"):
        if key not in mix:
            raise_err("ERR_INVALID_REQUEST", "estimated_grade_mix must carry A, B, and SCRAP")
        val = mix[key]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise_err("ERR_INVALID_REQUEST", "estimated_grade_mix values must be numbers")
        if val < 0:
            raise_err("ERR_INVALID_REQUEST", "estimated_grade_mix values must be >= 0")
    total = sum(float(mix[k]) for k in ("A", "B", "SCRAP"))
    if abs(total - 1.0) > 1e-9:
        raise_err("ERR_INVALID_REQUEST", "estimated_grade_mix values must sum to 1.0")
    return {"A": mix["A"], "B": mix["B"], "SCRAP": mix["SCRAP"]}


@bp.post("/pallet-ops/core-batches")
def create_batch():
    require_roles("ProcurementManager")
    body = get_json_body()
    supplier_name = as_str(req_field(body, "supplier_name"), "supplier_name")
    agreed = as_int(req_field(body, "agreed_unit_price_cents"), "agreed_unit_price_cents", minimum=0)
    manifest_count = as_int(req_field(body, "manifest_count"), "manifest_count", minimum=1)
    mix = _validate_grade_mix(req_field(body, "estimated_grade_mix"))

    batch = {
        "supplier_name": supplier_name,
        "agreed_unit_price_cents": agreed,
        "manifest_count": manifest_count,
        "estimated_grade_mix": mix,
        "received_count": 0,
        "provisional_settlement_cents": manifest_count * agreed,
        "final_settlement_cents": None,
        "grade_yield_variance_bp": None,
        "status": "RECEIVING",
    }
    init_common(batch)
    db.core_batches[batch["id"]] = batch
    return success(serialize(batch), status=201)


@bp.get("/pallet-ops/core-batches")
def list_batches():
    require_roles()
    limit, offset = parse_pagination()
    items = list(db.core_batches.values())
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success(serialize_list(page), pagination=pagination, is_list=True)


@bp.get("/pallet-ops/core-batches/<bid>")
def get_batch(bid):
    require_roles()
    batch = get_or_404(db.core_batches, bid, "CorePurchaseBatch")
    return success(serialize(batch))


@bp.post("/pallet-ops/core-batches/<bid>/begin-sorting")
def begin_sorting(bid):
    require_roles("YardSupervisor")
    batch = get_or_404(db.core_batches, bid, "CorePurchaseBatch")
    if batch["status"] != "RECEIVING":
        raise_err("ERR_BATCH_NOT_RECEIVING", "begin-sorting requires batch RECEIVING")
    batch["status"] = "SORTING"
    touch(batch)
    return success(serialize(batch))


@bp.post("/pallet-ops/core-batches/<bid>/finish-sorting")
def finish_sorting(bid):
    require_roles("YardSupervisor")
    batch = get_or_404(db.core_batches, bid, "CorePurchaseBatch")
    if batch["status"] != "SORTING":
        raise_err("ERR_BATCH_NOT_SORTING", "finish-sorting requires batch SORTING")
    cores = [c for c in db.core_units.values() if c["batch_id"] == bid]
    if any(c["grade"] == "UNSORTED" for c in cores):
        raise_err("ERR_CORES_UNSORTED", "finish-sorting blocked: UNSORTED cores remain in the batch")
    batch["received_count"] = len(cores)
    batch["status"] = "AUDIT"
    touch(batch)
    return success(serialize(batch))


@bp.post("/pallet-ops/core-batches/<bid>/close")
def close_batch(bid):
    require_roles("ProcurementManager")
    batch = get_or_404(db.core_batches, bid, "CorePurchaseBatch")
    if batch["status"] != "AUDIT":
        raise_err("ERR_BATCH_NOT_AUDIT", "close requires batch AUDIT")
    cores = [c for c in db.core_units.values() if c["batch_id"] == bid and c["grade"] != "UNSORTED"]
    batch["final_settlement_cents"] = compute_final_settlement(batch, cores)
    batch["grade_yield_variance_bp"] = compute_grade_yield_variance_bp(batch, cores)
    # provisional_settlement_cents retained (never zeroed).
    batch["status"] = "CLOSED"
    touch(batch)
    return success(serialize(batch))


# --- CoreUnit -------------------------------------------------------------------

@bp.post("/pallet-ops/core-units")
def create_core_units():
    require_roles("YardSupervisor")
    body = get_json_body()
    batch_id = as_str(req_field(body, "batch_id"), "batch_id")
    batch = ref_or_404(db.core_batches, batch_id, "batch_id")
    species = as_enum(req_field(body, "species"), "species", SPECIES)
    condition_notes = opt_field(body, "condition_notes", "")
    if not isinstance(condition_notes, str):
        raise_err("ERR_INVALID_REQUEST", "condition_notes must be a string")
    count = opt_field(body, "count", 1)
    count = as_int(count, "count", minimum=1)

    if batch["status"] not in ("RECEIVING", "SORTING"):
        raise_err(
            "ERR_INVALID_STATE",
            "Core receiving requires batch RECEIVING or SORTING",
        )

    created = []
    for _ in range(count):
        core = {
            "batch_id": batch_id,
            "grade": "UNSORTED",
            "species": species,
            "condition_notes": condition_notes,
            "repair_cycle_count": 0,
            "processing_status": "YARD",
            "rework_of_id": None,
        }
        init_common(core)
        db.core_units[core["id"]] = core
        created.append(core)
    # Bulk create returns the first created row (201 create contract); all rows
    # are retrievable via the list endpoint filtered by batch_id.
    return success(serialize(created[0]), status=201)


@bp.get("/pallet-ops/core-units")
def list_core_units():
    require_roles()
    limit, offset = parse_pagination()
    items = list(db.core_units.values())
    batch_id = request.args.get("batch_id")
    if batch_id is not None:
        items = [c for c in items if c["batch_id"] == batch_id]
    grade = request.args.get("grade")
    if grade is not None:
        items = [c for c in items if c["grade"] == grade]
    proc = request.args.get("processing_status")
    if proc is not None:
        items = [c for c in items if c["processing_status"] == proc]
    rework = request.args.get("rework_of_id")
    if rework is not None:
        items = [c for c in items if c.get("rework_of_id") == rework]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success(serialize_list(page), pagination=pagination, is_list=True)


@bp.get("/pallet-ops/core-units/<cid>")
def get_core_unit(cid):
    require_roles()
    core = get_or_404(db.core_units, cid, "CoreUnit")
    return success(serialize(core))


@bp.post("/pallet-ops/core-units/<cid>/sort")
def sort_core_unit(cid):
    require_roles("YardSupervisor")
    core = get_or_404(db.core_units, cid, "CoreUnit")
    body = get_json_body()
    grade = as_enum(req_field(body, "grade"), "grade", SORT_GRADES)
    notes = opt_field(body, "condition_notes", None)
    if notes is not None and not isinstance(notes, str):
        raise_err("ERR_INVALID_REQUEST", "condition_notes must be a string")

    batch = db.core_batches.get(core["batch_id"])
    if batch is None or batch["status"] != "SORTING":
        raise_err("ERR_BATCH_NOT_SORTING", "core sort requires batch SORTING")
    if core["grade"] != "UNSORTED":
        raise_err("ERR_CORE_ALREADY_SORTED", "sort requires grade == UNSORTED")

    # Resolve effective notes (payload overrides the stored note).
    effective_notes = notes if notes is not None else core["condition_notes"]
    if grade == "SCRAP" and not effective_notes:
        raise_err(
            "ERR_SCRAP_NOTE_REQUIRED",
            "Sorting to SCRAP requires a non-empty condition_notes",
        )

    core["grade"] = grade
    if notes is not None:
        core["condition_notes"] = notes
    if grade == "SCRAP":
        core["processing_status"] = "GRINDING_QUEUED"
    touch(core)
    return success(serialize(core))
