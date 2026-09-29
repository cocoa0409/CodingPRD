from datetime import timedelta

from flask import Blueprint

import calc
from calc import D
from envelope import success
from errors import fail
from services import (
    add_ledger,
    add_reserved_pull,
    aging_days_for_design,
    apply_posture,
    check_unique,
    recompute_remaining,
    require,
    wind_down,
)
from store import base_record, db, ordered, touch
from validation import (
    JOB_STATUSES,
    Enum,
    Id,
    Int,
    Num,
    Str,
    Text,
    Ts,
    authorize,
    paginate,
    pagination,
    query_enum,
    query_str,
    validate_body,
)

bp = Blueprint("jobs", __name__)

READERS = (
    "PlantManager",
    "PlantScheduler",
    "BatchHouseTech",
    "MoldEngineer",
    "QualityEngineer",
)

OPEN_JOB_STATUSES = ("SCHEDULED", "RUNNING")


# --------------------------------------------------------------------------- #
# window helpers
# --------------------------------------------------------------------------- #
def _machine_conflict(new_start, new_end, other_start, other_end, buffer_minutes):
    """Half-open windows with the buffer appended to whichever job starts first."""
    buffer_delta = timedelta(minutes=int(buffer_minutes))
    if new_start <= other_start:
        return (new_end + buffer_delta) > other_start
    return (other_end + buffer_delta) > new_start


def _overlaps_color_window(start, end, change):
    """Job window half-open [start, end); colour-change window closed."""
    return change["window_start_at"] < end and start <= change["window_end_at"]


def _projections(job, furnace, recipe):
    days = calc.window_days(job["window_start_at"], job["window_end_at"])
    nominal = calc.refractory_nominal(job["planned_pull_tpd"], days, recipe["color"])
    stress = calc.refractory_stress_adjusted(
        job["planned_pull_tpd"],
        days,
        recipe["color"],
        furnace["design_pull_tpd"],
        recipe["cullet_stress_factor"],
    )
    return nominal, stress


# --------------------------------------------------------------------------- #
# create
# --------------------------------------------------------------------------- #
@bp.post("/glass-plant/production-jobs")
def create_job():
    authorize("PlantScheduler")
    data = validate_body(
        [
            Id("campaign_id"),
            Id("furnace_id"),
            Id("forming_machine_id"),
            Id("batch_recipe_id"),
            Id("bottle_design_id"),
            Str("code", min_len=1, max_len=32),
            Ts("window_start_at"),
            Ts("window_end_at"),
            Num("planned_pull_tpd", gt=0, decimals=2),
            Int("expected_furnace_version", ge=1),
            Id("mold_set_id", required=False),
        ]
    )
    # 6: foreign keys resolve in declared field order.
    campaign = require(db.campaigns, data["campaign_id"], "ERR_CAMPAIGN_NOT_FOUND")
    furnace = require(db.furnaces, data["furnace_id"], "ERR_FURNACE_NOT_FOUND")
    machine = require(
        db.forming_machines, data["forming_machine_id"], "ERR_FORMING_MACHINE_NOT_FOUND"
    )
    recipe = require(db.batch_recipes, data["batch_recipe_id"], "ERR_BATCH_RECIPE_NOT_FOUND")
    design = require(db.bottle_designs, data["bottle_design_id"], "ERR_BOTTLE_DESIGN_NOT_FOUND")
    mold_set = None
    if data["mold_set_id"] is not None:
        mold_set = require(db.mold_sets, data["mold_set_id"], "ERR_MOLD_SET_NOT_FOUND")

    # 9 campaign active
    if campaign["status"] != "ACTIVE":
        fail("ERR_CAMPAIGN_NOT_ACTIVE")
    # 23 stale furnace version
    if int(data["expected_furnace_version"]) != int(furnace["version"]):
        fail("ERR_STALE_FURNACE_VERSION")
    # 25 colour agreement
    if recipe["color"] != furnace["current_color"] or design["color"] != furnace["current_color"]:
        fail("ERR_COLOR_MISMATCH")
    # 26 over-pull limits
    planned = D(data["planned_pull_tpd"])
    design_pull = D(furnace["design_pull_tpd"])
    if planned > design_pull * D("1.15"):
        fail("ERR_OVER_PULL_LIMIT")
    if furnace["posture"] == "RESTRICTED" and planned > design_pull:
        fail("ERR_OVER_PULL_LIMIT")
    # 29 machine, recipe and campaign all belong to the furnace
    if (
        machine["furnace_id"] != furnace["id"]
        or recipe["furnace_id"] != furnace["id"]
        or campaign["furnace_id"] != furnace["id"]
    ):
        fail("ERR_FURNACE_MISMATCH")
    # 30 mold set belongs to the design
    if mold_set is not None and mold_set["bottle_design_id"] != design["id"]:
        fail("ERR_MOLD_SET_DESIGN_MISMATCH")

    start = data["window_start_at"]
    end = data["window_end_at"]
    # 33 window order
    if not end > start:
        fail("ERR_WINDOW_ORDER_INVALID")
    # 34 containment inside the campaign window (closed for containment)
    if start < campaign["window_start_at"] or end > campaign["window_end_at"]:
        fail("ERR_JOB_WINDOW_OUTSIDE_CAMPAIGN")
    # 35 machine window collision
    for other in db.production_jobs.values():
        if other["forming_machine_id"] != machine["id"]:
            continue
        if other["status"] not in OPEN_JOB_STATUSES:
            continue
        if _machine_conflict(
            start,
            end,
            other["window_start_at"],
            other["window_end_at"],
            machine["changeover_buffer_minutes"],
        ):
            fail("ERR_MACHINE_WINDOW_CONFLICT")
    # 36 scheduled colour-change collision on the furnace
    for change in db.color_changes.values():
        if change["furnace_id"] != furnace["id"] or change["status"] != "SCHEDULED":
            continue
        if _overlaps_color_window(start, end, change):
            fail("ERR_COLOR_CHANGE_WINDOW_CONFLICT")
    # 39 code uniqueness
    check_unique(db.production_jobs, "code", data["code"])
    # 47 the reservation must fit the campaign pull pool
    reserved = calc.reserved_melt_tons(planned, calc.window_days(start, end))
    pool = calc.pull_pool_tons(
        campaign["target_pull_tpd"],
        calc.window_days(campaign["window_start_at"], campaign["window_end_at"]),
    )
    available = calc.available_pull_tons(
        pool, campaign["melt_tons_charged"], furnace["reserved_pull_tons"]
    )
    if reserved > available:
        fail("ERR_PULL_CAPACITY_EXCEEDED")

    record = base_record()
    record.update(
        {
            "campaign_id": campaign["id"],
            "furnace_id": furnace["id"],
            "forming_machine_id": machine["id"],
            "batch_recipe_id": recipe["id"],
            "bottle_design_id": design["id"],
            "mold_set_id": mold_set["id"] if mold_set else None,
            "code": data["code"],
            "window_start_at": start,
            "window_end_at": end,
            "planned_pull_tpd": data["planned_pull_tpd"],
            "status": "SCHEDULED",
            "reserved_melt_tons": reserved,
            "changeover_minutes": 0,
            "refractory_wear_units": D("0.00"),
            "produced_units": 0,
            "outcome_note": None,
        }
    )
    nominal, stress = _projections(record, furnace, recipe)
    record["projected_refractory_units_nominal"] = nominal
    record["projected_refractory_units_stress_adjusted"] = stress
    db.production_jobs[record["id"]] = record

    add_reserved_pull(furnace, reserved)
    touch(furnace)
    return success(record, 201)


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #
@bp.get("/glass-plant/production-jobs")
def list_jobs():
    authorize(*READERS)
    status = query_enum("status", JOB_STATUSES)
    filters = {}
    for name in (
        "campaign_id",
        "furnace_id",
        "forming_machine_id",
        "batch_recipe_id",
        "bottle_design_id",
        "mold_set_id",
    ):
        value = query_str(name)
        if value is not None:
            filters[name] = value
    limit, offset = pagination()
    records = ordered(list(db.production_jobs.values()))
    for name, value in filters.items():
        records = [r for r in records if r[name] == value]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, meta = paginate(records, limit, offset)
    return success(page, 200, meta)


@bp.get("/glass-plant/production-jobs/<production_job_id>")
def read_job(production_job_id):
    authorize(*READERS)
    job = require(db.production_jobs, production_job_id, "ERR_PRODUCTION_JOB_NOT_FOUND")
    return success(job)


@bp.get("/glass-plant/production-jobs/<production_job_id>/refractory-projection")
def read_projection(production_job_id):
    """Computed read: recomputes the nominal figure on demand and mutates nothing."""
    authorize("PlantManager", "PlantScheduler", "QualityEngineer")
    job = require(db.production_jobs, production_job_id, "ERR_PRODUCTION_JOB_NOT_FOUND")
    furnace = db.furnaces[job["furnace_id"]]
    recipe = db.batch_recipes[job["batch_recipe_id"]]
    nominal, stress = _projections(job, furnace, recipe)
    return success(
        {
            "production_job_id": job["id"],
            "projected_refractory_units_nominal": nominal,
            "projected_refractory_units_stress_adjusted": stress,
        }
    )


# --------------------------------------------------------------------------- #
# start
# --------------------------------------------------------------------------- #
@bp.post("/glass-plant/production-jobs/<production_job_id>/start")
def start_job(production_job_id):
    authorize("PlantScheduler")
    job = require(db.production_jobs, production_job_id, "ERR_PRODUCTION_JOB_NOT_FOUND")
    campaign = db.campaigns[job["campaign_id"]]
    furnace = db.furnaces[job["furnace_id"]]
    machine = db.forming_machines[job["forming_machine_id"]]
    recipe = db.batch_recipes[job["batch_recipe_id"]]
    design = db.bottle_designs[job["bottle_design_id"]]

    # 9 -> 10 -> 11 -> 13 -> 18 -> machine idle -> 40
    if campaign["status"] != "ACTIVE":
        fail("ERR_CAMPAIGN_NOT_ACTIVE")
    if job["status"] != "SCHEDULED":
        fail("ERR_JOB_STATE_INVALID")
    mold_set = db.mold_sets.get(job["mold_set_id"]) if job["mold_set_id"] else None
    if mold_set is None or mold_set["status"] != "AVAILABLE":
        fail("ERR_MOLD_SET_STATE_INVALID")
    if design["status"] != "APPROVED":
        fail("ERR_DESIGN_NOT_APPROVED")
    if not recipe["approved"]:
        fail("ERR_RECIPE_NOT_APPROVED")
    if furnace["posture"] not in ("OPERATING", "RESTRICTED"):
        fail("ERR_FURNACE_POSTURE_BLOCKED")
    if machine["status"] != "IDLE":
        fail("ERR_RUNNING_JOB_PRESENT")
    if int(mold_set["cavity_count"]) + int(machine["mounted_cavities"]) > int(
        machine["max_cavities"]
    ):
        fail("ERR_CAVITY_CAPACITY_EXCEEDED")

    job["changeover_minutes"] = calc.changeover_minutes(
        mold_set["mold_family"],
        machine["primary_mold_family"],
        mold_set["cavity_count"],
        design["cavity_count"],
        mold_set["condition_score"],
    )
    job["status"] = "RUNNING"
    touch(job)

    mold_set["status"] = "MOUNTED"
    mold_set["forming_machine_id"] = machine["id"]
    mold_set["mount_count"] = int(mold_set["mount_count"]) + 1
    touch(mold_set)

    machine["status"] = "RUNNING"
    machine["mounted_cavities"] = int(machine["mounted_cavities"]) + int(
        mold_set["cavity_count"]
    )
    touch(machine)
    return success(job)


# --------------------------------------------------------------------------- #
# close
# --------------------------------------------------------------------------- #
def _create_pack_lot(job, campaign, design):
    customer = db.customers[design["customer_id"]]
    lot = base_record()
    packed_units = int(job["produced_units"])
    lot.update(
        {
            "production_job_id": job["id"],
            "campaign_id": campaign["id"],
            "bottle_design_id": design["id"],
            "customer_id": customer["id"],
            "lot_code": "%s-L1" % job["code"],
            "packed_units": packed_units,
            "unit_weight_g": design["nominal_weight_g"],
            "palletization_standard": customer["palletization_standard"],
            "reject_units": 0,
            "net_packed_units": packed_units,
            "major_ppm": D("0.0"),
            "minor_ppm": D("0.0"),
            "final_yield_pct": D("0.00"),
            "pallet_count": 0,
            "shipped_at": None,
            "quality_status": "PENDING_INSPECTION",
            "logistics_status": "IN_AGING",
        }
    )
    gross_tons = calc.tons_from_units(packed_units, design["nominal_weight_g"])
    lot["provisional_yield_pct"] = calc.provisional_yield_pct(
        gross_tons, job["reserved_melt_tons"]
    )
    lot["aged_until_at"] = lot["created_at"] + timedelta(days=aging_days_for_design(design))
    db.pack_lots[lot["id"]] = lot
    return lot


@bp.post("/glass-plant/production-jobs/<production_job_id>/close")
def close_job(production_job_id):
    authorize("PlantScheduler")
    data = validate_body(
        [
            Enum("outcome", ("COMPLETED", "ABORTED")),
            Int("produced_units", required=False, ge=0),
            Text("outcome_note", required=False, max_len=400),
        ]
    )
    if data["outcome"] == "COMPLETED":
        if data["produced_units"] is None or int(data["produced_units"]) < 1:
            fail("ERR_VALIDATION", "produced_units must be at least 1 on a COMPLETED close.")

    job = require(db.production_jobs, production_job_id, "ERR_PRODUCTION_JOB_NOT_FOUND")
    if job["status"] != "RUNNING":
        fail("ERR_JOB_STATE_INVALID")

    campaign = db.campaigns[job["campaign_id"]]
    furnace = db.furnaces[job["furnace_id"]]
    machine = db.forming_machines[job["forming_machine_id"]]
    recipe = db.batch_recipes[job["batch_recipe_id"]]
    design = db.bottle_designs[job["bottle_design_id"]]

    # refractory wear: the stress-adjusted variant is what actually gets charged
    days = calc.window_days(job["window_start_at"], job["window_end_at"])
    wear = calc.refractory_stress_adjusted(
        job["planned_pull_tpd"],
        days,
        recipe["color"],
        furnace["design_pull_tpd"],
        recipe["cullet_stress_factor"],
    )
    job["refractory_wear_units"] = wear
    furnace["refractory_consumed_units"] = calc.rhu(
        D(furnace["refractory_consumed_units"]) + wear, 2
    )
    recompute_remaining(furnace)

    # reserved tons leave the furnace pool and land in the campaign ledger
    add_reserved_pull(furnace, -D(job["reserved_melt_tons"]))
    add_ledger(campaign, "melt_tons_charged", job["reserved_melt_tons"])

    job["outcome_note"] = data["outcome_note"]
    lot = None
    if data["outcome"] == "COMPLETED":
        job["produced_units"] = int(data["produced_units"])
        job["status"] = "COMPLETED"
    else:
        job["status"] = "ABORTED"
    touch(job)

    machine["status"] = "IDLE"
    touch(machine)

    if job["status"] == "COMPLETED":
        lot = _create_pack_lot(job, campaign, design)

    apply_posture(furnace)
    furnace["updated_at"] = db.clock
    if (
        D(furnace["refractory_remaining_pct"]) <= calc.REBUILD_DUE_PCT
        and campaign["status"] == "ACTIVE"
    ):
        wind_down(campaign)
    return success(job)


# --------------------------------------------------------------------------- #
# cancel
# --------------------------------------------------------------------------- #
@bp.post("/glass-plant/production-jobs/<production_job_id>/cancel")
def cancel_job(production_job_id):
    authorize("PlantScheduler")
    job = require(db.production_jobs, production_job_id, "ERR_PRODUCTION_JOB_NOT_FOUND")
    if job["status"] != "SCHEDULED":
        fail("ERR_JOB_STATE_INVALID")
    furnace = db.furnaces[job["furnace_id"]]
    job["status"] = "CANCELLED"
    touch(job)
    add_reserved_pull(furnace, -D(job["reserved_melt_tons"]))
    touch(furnace)
    return success(job)
