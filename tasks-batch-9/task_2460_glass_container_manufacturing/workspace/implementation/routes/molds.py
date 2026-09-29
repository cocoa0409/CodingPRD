from flask import Blueprint

from envelope import success
from errors import fail
from services import check_unique, require
from store import base_record, db, ordered, touch
from validation import (
    MOLD_FAMILIES,
    MOLD_SET_STATUSES,
    OWNERS,
    Enum,
    Id,
    Int,
    Str,
    authorize,
    paginate,
    pagination,
    query_enum,
    query_str,
    validate_body,
)

bp = Blueprint("molds", __name__)

READERS = ("PlantManager", "PlantScheduler", "MoldEngineer", "QualityEngineer")

SCRAP_CONDITION_FLOOR = 40


@bp.post("/glass-plant/mold-sets")
def create_mold_set():
    authorize("MoldEngineer")
    data = validate_body(
        [
            Id("bottle_design_id"),
            Str("code", min_len=1, max_len=32),
            Int("cavity_count", ge=1, le=20),
            Enum("mold_family", MOLD_FAMILIES),
            Enum("owner", OWNERS),
            Int("condition_score", ge=0, le=100),
        ]
    )
    design = require(db.bottle_designs, data["bottle_design_id"], "ERR_BOTTLE_DESIGN_NOT_FOUND")
    check_unique(db.mold_sets, "code", data["code"])

    record = base_record()
    record.update(
        {
            "bottle_design_id": design["id"],
            "code": data["code"],
            "cavity_count": data["cavity_count"],
            "mold_family": data["mold_family"],
            "owner": data["owner"],
            "condition_score": data["condition_score"],
            "status": "AVAILABLE",
            "mount_count": 0,
            "forming_machine_id": None,
        }
    )
    db.mold_sets[record["id"]] = record
    return success(record, 201)


@bp.get("/glass-plant/mold-sets")
def list_mold_sets():
    authorize(*READERS)
    status = query_enum("status", MOLD_SET_STATUSES)
    owner = query_enum("owner", OWNERS)
    bottle_design_id = query_str("bottle_design_id")
    forming_machine_id = query_str("forming_machine_id")
    limit, offset = pagination()
    records = ordered(list(db.mold_sets.values()))
    if bottle_design_id is not None:
        records = [r for r in records if r["bottle_design_id"] == bottle_design_id]
    if forming_machine_id is not None:
        records = [r for r in records if r["forming_machine_id"] == forming_machine_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if owner is not None:
        records = [r for r in records if r["owner"] == owner]
    page, meta = paginate(records, limit, offset)
    return success(page, 200, meta)


@bp.get("/glass-plant/mold-sets/<mold_set_id>")
def read_mold_set(mold_set_id):
    authorize(*READERS)
    mold_set = require(db.mold_sets, mold_set_id, "ERR_MOLD_SET_NOT_FOUND")
    return success(mold_set)


@bp.post("/glass-plant/mold-sets/<mold_set_id>/unmount")
def unmount_mold_set(mold_set_id):
    authorize("MoldEngineer")
    mold_set = require(db.mold_sets, mold_set_id, "ERR_MOLD_SET_NOT_FOUND")
    if mold_set["status"] != "MOUNTED":
        fail("ERR_MOLD_SET_STATE_INVALID")
    for job in db.production_jobs.values():
        if job["mold_set_id"] == mold_set["id"] and job["status"] == "RUNNING":
            fail("ERR_RUNNING_JOB_PRESENT")

    machine = db.forming_machines.get(mold_set["forming_machine_id"])
    if machine is not None:
        machine["mounted_cavities"] = max(
            0, int(machine["mounted_cavities"]) - int(mold_set["cavity_count"])
        )
        touch(machine)
    mold_set["forming_machine_id"] = None
    mold_set["status"] = "AVAILABLE"
    touch(mold_set)
    return success(mold_set)


@bp.post("/glass-plant/mold-sets/<mold_set_id>/send-to-repair")
def send_to_repair(mold_set_id):
    authorize("MoldEngineer")
    mold_set = require(db.mold_sets, mold_set_id, "ERR_MOLD_SET_NOT_FOUND")
    if mold_set["status"] != "AVAILABLE":
        fail("ERR_MOLD_SET_STATE_INVALID")
    mold_set["status"] = "IN_REPAIR"
    touch(mold_set)
    return success(mold_set)


@bp.post("/glass-plant/mold-sets/<mold_set_id>/return-from-repair")
def return_from_repair(mold_set_id):
    authorize("MoldEngineer")
    data = validate_body([Int("condition_score", ge=0, le=100)])
    mold_set = require(db.mold_sets, mold_set_id, "ERR_MOLD_SET_NOT_FOUND")
    if mold_set["status"] != "IN_REPAIR":
        fail("ERR_MOLD_SET_STATE_INVALID")
    # Both branches write the re-graded score back; only the state differs.
    mold_set["condition_score"] = data["condition_score"]
    if int(data["condition_score"]) >= SCRAP_CONDITION_FLOOR:
        mold_set["status"] = "AVAILABLE"
    else:
        mold_set["status"] = "SCRAPPED"
    touch(mold_set)
    return success(mold_set)
