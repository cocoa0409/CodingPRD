from flask import Blueprint

from calc import D
from envelope import success
from services import check_unique, children, require
from store import base_record, db, ordered
from validation import (
    CAMPAIGN_STATUSES,
    COLORS,
    COLOR_CHANGE_STATUSES,
    MACHINE_STATUSES,
    POSTURES,
    Num,
    Str,
    authorize,
    paginate,
    pagination,
    query_bool,
    query_enum,
    validate_body,
)

bp = Blueprint("furnaces", __name__)

ALL_OPERATORS = (
    "PlantManager",
    "PlantScheduler",
    "BatchHouseTech",
    "MoldEngineer",
    "QualityEngineer",
    "WarehouseOperator",
)


@bp.post("/glass-plant/furnaces")
def create_furnace():
    authorize("PlantManager")
    data = validate_body(
        [
            Str("code", min_len=1, max_len=32),
            Num("design_pull_tpd", gt=0, le=600, decimals=2),
            Num("refractory_life_total_units", gt=0, decimals=2),
        ]
    )
    check_unique(db.furnaces, "code", data["code"])
    record = base_record()
    record.update(
        {
            "code": data["code"],
            "design_pull_tpd": data["design_pull_tpd"],
            "current_color": "FLINT",
            "refractory_life_total_units": data["refractory_life_total_units"],
            "refractory_consumed_units": D("0.00"),
            "refractory_remaining_pct": D("100.00"),
            "posture": "OPERATING",
            "reserved_pull_tons": D("0.00"),
            "campaign_count": 0,
        }
    )
    db.furnaces[record["id"]] = record
    return success(record, 201)


@bp.get("/glass-plant/furnaces")
def list_furnaces():
    authorize(*ALL_OPERATORS)
    posture = query_enum("posture", POSTURES)
    limit, offset = pagination()
    records = ordered(list(db.furnaces.values()))
    if posture is not None:
        records = [r for r in records if r["posture"] == posture]
    page, meta = paginate(records, limit, offset)
    return success(page, 200, meta)


@bp.get("/glass-plant/furnaces/<furnace_id>")
def read_furnace(furnace_id):
    authorize(*ALL_OPERATORS)
    furnace = require(db.furnaces, furnace_id, "ERR_FURNACE_NOT_FOUND")
    return success(furnace)


@bp.get("/glass-plant/furnaces/<furnace_id>/campaigns")
def list_furnace_campaigns(furnace_id):
    authorize("PlantManager", "PlantScheduler", "QualityEngineer")
    status = query_enum("status", CAMPAIGN_STATUSES)
    limit, offset = pagination()
    require(db.furnaces, furnace_id, "ERR_FURNACE_NOT_FOUND")
    records = children(db.campaigns, "furnace_id", furnace_id)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, meta = paginate(records, limit, offset)
    return success(page, 200, meta)


@bp.get("/glass-plant/furnaces/<furnace_id>/batch-recipes")
def list_furnace_recipes(furnace_id):
    authorize("PlantManager", "PlantScheduler", "BatchHouseTech", "QualityEngineer")
    color = query_enum("color", COLORS)
    approved = query_bool("approved")
    limit, offset = pagination()
    require(db.furnaces, furnace_id, "ERR_FURNACE_NOT_FOUND")
    records = children(db.batch_recipes, "furnace_id", furnace_id)
    if color is not None:
        records = [r for r in records if r["color"] == color]
    if approved is not None:
        records = [r for r in records if r["approved"] is approved]
    page, meta = paginate(records, limit, offset)
    return success(page, 200, meta)


@bp.get("/glass-plant/furnaces/<furnace_id>/color-changes")
def list_furnace_color_changes(furnace_id):
    authorize("PlantManager", "PlantScheduler", "BatchHouseTech", "QualityEngineer")
    status = query_enum("status", COLOR_CHANGE_STATUSES)
    limit, offset = pagination()
    require(db.furnaces, furnace_id, "ERR_FURNACE_NOT_FOUND")
    records = children(db.color_changes, "furnace_id", furnace_id)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, meta = paginate(records, limit, offset)
    return success(page, 200, meta)


@bp.get("/glass-plant/furnaces/<furnace_id>/forming-machines")
def list_furnace_machines(furnace_id):
    authorize("PlantManager", "PlantScheduler", "MoldEngineer")
    status = query_enum("status", MACHINE_STATUSES)
    limit, offset = pagination()
    require(db.furnaces, furnace_id, "ERR_FURNACE_NOT_FOUND")
    records = children(db.forming_machines, "furnace_id", furnace_id)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, meta = paginate(records, limit, offset)
    return success(page, 200, meta)
