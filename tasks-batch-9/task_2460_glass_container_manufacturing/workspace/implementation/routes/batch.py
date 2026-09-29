from datetime import timedelta

from flask import Blueprint

import calc
from calc import D
from envelope import success
from errors import fail
from services import (
    add_ledger,
    check_unique,
    live_campaign_for_furnace,
    require,
)
from store import base_record, db, touch
from validation import (
    COLORS,
    Enum,
    Id,
    Num,
    Str,
    Text,
    Ts,
    authorize,
    validate_body,
)

bp = Blueprint("batch", __name__)

# PRD 3.3: colour-purity ceiling per colour, sitting on top of the type range.
CULLET_CEILING = {"FLINT": D("90.00"), "AMBER": D("95.00"), "GREEN": D("95.00")}


def _check_cullet(recipe_color, cullet_ratio_pct):
    if D(cullet_ratio_pct) > CULLET_CEILING[recipe_color]:
        fail("ERR_CULLET_RATIO_UNSAFE")


# --------------------------------------------------------------------------- #
# batch recipes
# --------------------------------------------------------------------------- #
@bp.post("/glass-plant/batch-recipes")
def create_recipe():
    authorize("BatchHouseTech")
    data = validate_body(
        [
            Id("furnace_id"),
            Str("code", min_len=1, max_len=32),
            Enum("color", COLORS),
            Num("cullet_ratio_pct", ge=0, le=95, decimals=2),
            Num("soda_ash_kg_per_ton", gt=0, decimals=2),
            Num("colorant_kg_per_ton", ge=0, decimals=2),
        ]
    )
    furnace = require(db.furnaces, data["furnace_id"], "ERR_FURNACE_NOT_FOUND")
    _check_cullet(data["color"], data["cullet_ratio_pct"])
    check_unique(db.batch_recipes, "code", data["code"])

    record = base_record()
    record.update(
        {
            "furnace_id": furnace["id"],
            "code": data["code"],
            "color": data["color"],
            "cullet_ratio_pct": data["cullet_ratio_pct"],
            "soda_ash_kg_per_ton": data["soda_ash_kg_per_ton"],
            "colorant_kg_per_ton": data["colorant_kg_per_ton"],
            "approved": False,
            "cullet_stress_factor": calc.cullet_stress_factor(data["cullet_ratio_pct"]),
        }
    )
    db.batch_recipes[record["id"]] = record
    return success(record, 201)


@bp.get("/glass-plant/batch-recipes/<batch_recipe_id>")
def read_recipe(batch_recipe_id):
    authorize("PlantManager", "PlantScheduler", "BatchHouseTech", "QualityEngineer")
    recipe = require(db.batch_recipes, batch_recipe_id, "ERR_BATCH_RECIPE_NOT_FOUND")
    return success(recipe)


@bp.post("/glass-plant/batch-recipes/<batch_recipe_id>/approve")
def approve_recipe(batch_recipe_id):
    authorize("BatchHouseTech")
    recipe = require(db.batch_recipes, batch_recipe_id, "ERR_BATCH_RECIPE_NOT_FOUND")
    _check_cullet(recipe["color"], recipe["cullet_ratio_pct"])
    recipe["approved"] = True
    touch(recipe)
    return success(recipe)


# --------------------------------------------------------------------------- #
# colour changes
# --------------------------------------------------------------------------- #
def _color_windows_overlap(a_start, a_end, b_start, b_end):
    """Both closed intervals: sharing a single endpoint counts as an overlap."""
    return a_start <= b_end and b_start <= a_end


def _job_overlaps_color_window(job, start, end):
    """Job window is half-open [start, end); colour window is closed [start, end]."""
    return job["window_start_at"] <= end and start < job["window_end_at"]


@bp.post("/glass-plant/color-changes")
def create_color_change():
    authorize("BatchHouseTech")
    data = validate_body(
        [
            Id("furnace_id"),
            Enum("to_color", COLORS),
            Ts("window_start_at"),
            Ts("window_end_at"),
            Num("transition_loss_tons", gt=0, decimals=2),
        ]
    )
    furnace = require(db.furnaces, data["furnace_id"], "ERR_FURNACE_NOT_FOUND")
    # PRD 3.3: naming the colour the furnace already melts is a malformed request.
    if data["to_color"] == furnace["current_color"]:
        fail("ERR_VALIDATION", "to_color must differ from the furnace's current_color.")
    if not data["window_end_at"] > data["window_start_at"]:
        fail("ERR_WINDOW_ORDER_INVALID")

    start = data["window_start_at"]
    end = data["window_end_at"]
    for change in db.color_changes.values():
        if change["furnace_id"] != furnace["id"]:
            continue
        if change["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if _color_windows_overlap(start, end, change["window_start_at"], change["window_end_at"]):
            fail("ERR_COLOR_CHANGE_WINDOW_CONFLICT")
    for job in db.production_jobs.values():
        if job["furnace_id"] != furnace["id"] or job["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        if _job_overlaps_color_window(job, start, end):
            fail("ERR_COLOR_CHANGE_WINDOW_CONFLICT")

    # rolling 30-day allowance measured from the new change's window_start_at
    floor = start - timedelta(days=30)
    count = 1
    for change in db.color_changes.values():
        if change["furnace_id"] != furnace["id"]:
            continue
        if change["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if floor <= change["window_start_at"] <= start:
            count += 1
    if count > 4:
        fail("ERR_COLOR_CHANGE_RATE_EXCEEDED")

    record = base_record()
    record.update(
        {
            "furnace_id": furnace["id"],
            "from_color": furnace["current_color"],
            "to_color": data["to_color"],
            "window_start_at": start,
            "window_end_at": end,
            "transition_loss_tons": data["transition_loss_tons"],
            "status": "SCHEDULED",
        }
    )
    db.color_changes[record["id"]] = record
    return success(record, 201)


@bp.get("/glass-plant/color-changes/<color_change_id>")
def read_color_change(color_change_id):
    authorize("PlantManager", "PlantScheduler", "BatchHouseTech", "QualityEngineer")
    change = require(db.color_changes, color_change_id, "ERR_COLOR_CHANGE_NOT_FOUND")
    return success(change)


@bp.post("/glass-plant/color-changes/<color_change_id>/complete")
def complete_color_change(color_change_id):
    authorize("BatchHouseTech")
    change = require(db.color_changes, color_change_id, "ERR_COLOR_CHANGE_NOT_FOUND")
    furnace = db.furnaces[change["furnace_id"]]
    if change["status"] != "SCHEDULED":
        fail("ERR_COLOR_CHANGE_STATE_INVALID")
    for job in db.production_jobs.values():
        if job["furnace_id"] != furnace["id"] or job["status"] != "RUNNING":
            continue
        if _job_overlaps_color_window(job, change["window_start_at"], change["window_end_at"]):
            fail("ERR_RUNNING_JOB_PRESENT")
    if db.clock < change["window_end_at"]:
        fail("ERR_WINDOW_NOT_ELAPSED")

    change["status"] = "COMPLETED"
    furnace["current_color"] = change["to_color"]
    touch(furnace)
    campaign = live_campaign_for_furnace(furnace["id"])
    if campaign is not None:
        add_ledger(campaign, "melt_tons_charged", change["transition_loss_tons"])
    touch(change)
    return success(change)


@bp.post("/glass-plant/color-changes/<color_change_id>/abort")
def abort_color_change(color_change_id):
    authorize("BatchHouseTech")
    validate_body([Text("reason", required=False)])
    change = require(db.color_changes, color_change_id, "ERR_COLOR_CHANGE_NOT_FOUND")
    if change["status"] != "SCHEDULED":
        fail("ERR_COLOR_CHANGE_STATE_INVALID")
    change["status"] = "ABORTED"
    touch(change)
    return success(change)
