from flask import Blueprint

from auth import authenticate, require_role
from db import store
from envelope import success_object, success_list
from errors import raise_err, ERR_MOLD_NOT_FOUND, ERR_MACHINE_LINE_NOT_FOUND, \
    ERR_CAVITY_BLOCKOUT_NOT_FOUND, ERR_DUPLICATE_CODE, ERR_INVALID_STATE, \
    ERR_ALREADY_TERMINAL, ERR_LINE_BUSY, ERR_STALE_VERSION, \
    ERR_MOLD_NOT_INSTALLED, ERR_CAVITY_OUT_OF_RANGE, ERR_CAVITY_ALREADY_BLOCKED
from services import stamp_new, touch, ser_mold, ser_blockout, \
    ser_schedule_slot, sorted_rows
from util import new_id, logical_now
from validate import get_body, check_fields, pagination_params, query_filter

bp = Blueprint("molds", __name__)

MOLD_READ_ROLES = ["PlantAdmin", "ProcessEngineer", "QualityTechnician",
                   "ProductionScheduler"]
BLOCKOUT_READ_ROLES = ["PlantAdmin", "ProcessEngineer", "QualityTechnician"]
SLOT_READ_ROLES = ["PlantAdmin", "ProcessEngineer", "ProductionScheduler"]
SLOT_STATUSES = {"CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
BLOCKOUT_STATUSES = {"OPEN", "CLEARED"}
BLOCKOUT_REASONS = {"DAMAGE", "CONTAMINATION_HOLD", "PREVENTIVE",
                    "QUALITY_HOLD"}


def get_mold_or_404(mold_id):
    mold = store.molds.get(mold_id)
    if mold is None:
        raise_err(ERR_MOLD_NOT_FOUND, "Mold id does not resolve")
    return mold


@bp.post("/molds")
def create_mold():
    _, role = authenticate()
    require_role(role, ["PlantAdmin"])
    body = check_fields(get_body(), {
        "mold_code": ("str", True),
        "base_cavities": ("int", True),
        "compatible_resins": ("resin_list", True),
        "reference_weight_g": ("number", True),
    })
    for m in store.molds.values():
        if m["mold_code"] == body["mold_code"]:
            raise_err(ERR_DUPLICATE_CODE, "mold_code must be unique")
    mold = {
        "mold_code": body["mold_code"],
        "base_cavities": body["base_cavities"],
        "compatible_resins": body["compatible_resins"],
        "reference_weight_g": body["reference_weight_g"],
        "installed_line_id": None,
        "status": "STORAGE",
    }
    stamp_new(mold, new_id())
    store.molds[mold["id"]] = mold
    return success_object(ser_mold(mold), 201)


@bp.get("/molds/<mid>")
def get_mold(mid):
    _, role = authenticate()
    require_role(role, MOLD_READ_ROLES)
    return success_object(ser_mold(get_mold_or_404(mid)))


@bp.post("/molds/<mid>/install")
def install_mold(mid):
    _, role = authenticate()
    require_role(role, ["ProcessEngineer"])
    body = check_fields(get_body(), {"machine_line_id": ("str", True)})
    mold = get_mold_or_404(mid)
    line = store.machine_lines.get(body["machine_line_id"])
    if line is None:
        raise_err(ERR_MACHINE_LINE_NOT_FOUND,
                  "MachineLine id does not resolve")
    # state: mold must be STORAGE
    if mold["status"] != "STORAGE":
        raise_err(ERR_INVALID_STATE, "Mold is not in STORAGE")
    # no other mold may be installed on the line (line must be IDLE)
    other = None
    for m in store.molds.values():
        if (m["id"] != mold["id"] and m["installed_line_id"] == line["id"]
                and m["status"] == "INSTALLED"):
            other = m
            break
    if other is not None or line["status"] != "IDLE":
        raise_err(ERR_LINE_BUSY,
                  "Target line already hosts a mold or is not IDLE")
    mold["status"] = "INSTALLED"
    mold["installed_line_id"] = line["id"]
    touch(mold)
    line["status"] = "CHANGEOVER"
    touch(line)
    return success_object(ser_mold(mold))


@bp.post("/molds/<mid>/remove")
def remove_mold(mid):
    _, role = authenticate()
    require_role(role, ["ProcessEngineer"])
    check_fields(get_body(), {})
    mold = get_mold_or_404(mid)
    if mold["status"] != "INSTALLED":
        raise_err(ERR_INVALID_STATE, "Mold is not INSTALLED")
    for r in store.production_runs.values():
        if r["mold_id"] == mold["id"] and r["status"] == "OPEN":
            raise_err(ERR_INVALID_STATE,
                      "Mold has an OPEN production run")
    line = store.machine_lines.get(mold["installed_line_id"])
    if line is not None and line["status"] == "RUNNING":
        raise_err(ERR_INVALID_STATE, "Hosting line is RUNNING")
    mold["status"] = "STORAGE"
    mold["installed_line_id"] = None
    touch(mold)
    if line is not None and line["status"] == "CHANGEOVER":
        line["status"] = "IDLE"
        touch(line)
    return success_object(ser_mold(mold))


@bp.get("/molds/<mid>/schedule-slots")
def mold_slots(mid):
    _, role = authenticate()
    require_role(role, SLOT_READ_ROLES)
    get_mold_or_404(mid)
    status = query_filter("status", SLOT_STATUSES)
    limit, offset = pagination_params()
    rows = [s for s in store.schedule_slots.values() if s["mold_id"] == mid]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    rows = sorted_rows(rows)
    page = rows[offset:offset + limit]
    return success_list([ser_schedule_slot(s) for s in page], limit, offset,
                        len(rows))


# ---------------------------------------------------------------------------
# cavity blockouts
# ---------------------------------------------------------------------------

@bp.post("/molds/<mid>/cavity-blockouts")
def create_blockout(mid):
    _, role = authenticate()
    require_role(role, ["ProcessEngineer"])
    body = check_fields(get_body(), {
        "cavity_index": ("int", True),
        "reason": ("enum", True, BLOCKOUT_REASONS),
        "expected_mold_version": ("int", True),
    })
    mold = get_mold_or_404(mid)
    # OCC precedes all other state rules
    if body["expected_mold_version"] != mold["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_mold_version does not equal the mold's version")
    if mold["status"] != "INSTALLED":
        raise_err(ERR_MOLD_NOT_INSTALLED,
                  "Cavity blockouts require an INSTALLED mold")
    if not (1 <= body["cavity_index"] <= mold["base_cavities"]):
        raise_err(ERR_CAVITY_OUT_OF_RANGE,
                  "cavity_index outside 1..base_cavities")
    for b in store.cavity_blockouts.values():
        if (b["mold_id"] == mold["id"] and b["status"] == "OPEN"
                and b["cavity_index"] == body["cavity_index"]):
            raise_err(ERR_CAVITY_ALREADY_BLOCKED,
                      "An OPEN blockout already exists for this cavity")
    blockout = {
        "mold_id": mold["id"],
        "cavity_index": body["cavity_index"],
        "reason": body["reason"],
        "blocked_at": logical_now(),
        "cleared_at": None,
        "status": "OPEN",
    }
    stamp_new(blockout, new_id())
    store.cavity_blockouts[blockout["id"]] = blockout
    touch(mold)  # cavitation figures recomputed; mold version advances
    return success_object(ser_blockout(blockout), 201)


@bp.get("/molds/<mid>/cavity-blockouts")
def list_blockouts(mid):
    _, role = authenticate()
    require_role(role, BLOCKOUT_READ_ROLES)
    get_mold_or_404(mid)
    status = query_filter("status", BLOCKOUT_STATUSES)
    limit, offset = pagination_params()
    rows = [b for b in store.cavity_blockouts.values() if b["mold_id"] == mid]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    rows = sorted_rows(rows)
    page = rows[offset:offset + limit]
    return success_list([ser_blockout(b) for b in page], limit, offset,
                        len(rows))


@bp.get("/cavity-blockouts/<bid>")
def get_blockout(bid):
    _, role = authenticate()
    require_role(role, BLOCKOUT_READ_ROLES)
    b = store.cavity_blockouts.get(bid)
    if b is None:
        raise_err(ERR_CAVITY_BLOCKOUT_NOT_FOUND,
                  "CavityBlockout id does not resolve")
    return success_object(ser_blockout(b))


@bp.post("/cavity-blockouts/<bid>/clear")
def clear_blockout(bid):
    _, role = authenticate()
    require_role(role, ["ProcessEngineer"])
    check_fields(get_body(), {})
    b = store.cavity_blockouts.get(bid)
    if b is None:
        raise_err(ERR_CAVITY_BLOCKOUT_NOT_FOUND,
                  "CavityBlockout id does not resolve")
    if b["status"] == "CLEARED":
        raise_err(ERR_ALREADY_TERMINAL, "Blockout is already CLEARED")
    b["status"] = "CLEARED"
    b["cleared_at"] = logical_now()
    touch(b)
    mold = store.molds.get(b["mold_id"])
    if mold is not None:
        touch(mold)  # cavitation figures recomputed
    return success_object(ser_blockout(b))
