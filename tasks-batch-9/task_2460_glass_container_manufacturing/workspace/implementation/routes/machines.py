from flask import Blueprint

from envelope import success
from services import check_unique, require
from store import base_record, db
from validation import (
    MOLD_FAMILIES,
    Enum,
    Id,
    Int,
    Str,
    authorize,
    validate_body,
)

bp = Blueprint("machines", __name__)

DEFAULT_CHANGEOVER_BUFFER_MINUTES = 45


@bp.post("/glass-plant/forming-machines")
def create_machine():
    authorize("PlantManager")
    data = validate_body(
        [
            Id("furnace_id"),
            Str("code", min_len=1, max_len=32),
            Int("section_count", ge=4, le=20),
            Int("max_cavities", ge=4, le=80),
            Enum("primary_mold_family", MOLD_FAMILIES),
            Int("changeover_buffer_minutes", required=False, ge=0, le=240),
        ]
    )
    furnace = require(db.furnaces, data["furnace_id"], "ERR_FURNACE_NOT_FOUND")
    check_unique(db.forming_machines, "code", data["code"])

    buffer_minutes = data["changeover_buffer_minutes"]
    if buffer_minutes is None:
        buffer_minutes = DEFAULT_CHANGEOVER_BUFFER_MINUTES

    record = base_record()
    record.update(
        {
            "furnace_id": furnace["id"],
            "code": data["code"],
            "section_count": data["section_count"],
            "max_cavities": data["max_cavities"],
            "primary_mold_family": data["primary_mold_family"],
            "changeover_buffer_minutes": buffer_minutes,
            "status": "IDLE",
            "mounted_cavities": 0,
        }
    )
    db.forming_machines[record["id"]] = record
    return success(record, 201)


@bp.get("/glass-plant/forming-machines/<forming_machine_id>")
def read_machine(forming_machine_id):
    authorize("PlantManager", "PlantScheduler", "MoldEngineer", "QualityEngineer")
    machine = require(
        db.forming_machines, forming_machine_id, "ERR_FORMING_MACHINE_NOT_FOUND"
    )
    return success(machine)
