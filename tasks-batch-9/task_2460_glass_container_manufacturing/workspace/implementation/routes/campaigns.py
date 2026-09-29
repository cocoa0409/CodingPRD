from flask import Blueprint

import calc
from calc import D
from envelope import success
from errors import fail
from services import (
    apply_posture,
    campaign_jobs,
    check_unique,
    reconcile_campaign,
    require,
    wind_down,
)
from store import base_record, db, touch
from validation import Num, Str, Ts, Id, authorize, validate_body

bp = Blueprint("campaigns", __name__)


@bp.post("/glass-plant/campaigns")
def create_campaign():
    authorize("PlantManager")
    data = validate_body(
        [
            Id("furnace_id"),
            Str("code", min_len=1, max_len=32),
            Num("target_pull_tpd", gt=0, decimals=2),
            Ts("window_start_at"),
            Ts("window_end_at"),
        ]
    )
    furnace = require(db.furnaces, data["furnace_id"], "ERR_FURNACE_NOT_FOUND")
    # 33 window order -> 39 code uniqueness -> 46 target pull vs design pull
    if not data["window_end_at"] > data["window_start_at"]:
        fail("ERR_WINDOW_ORDER_INVALID")
    check_unique(db.campaigns, "code", data["code"])
    if D(data["target_pull_tpd"]) > D(furnace["design_pull_tpd"]):
        fail("ERR_TARGET_PULL_EXCEEDS_DESIGN")

    record = base_record()
    record.update(
        {
            "furnace_id": furnace["id"],
            "code": data["code"],
            "target_pull_tpd": data["target_pull_tpd"],
            "window_start_at": data["window_start_at"],
            "window_end_at": data["window_end_at"],
            "status": "PLANNED",
            "melt_tons_charged": D("0.00"),
            "packed_tons": D("0.00"),
            "transition_loss_tons": D("0.00"),
            "reject_loss_tons": D("0.00"),
            "unaccounted_loss_tons": D("0.00"),
            "projected_refractory_units_nominal": D("0.00"),
            "rebuild_window_start_at": None,
            "rebuild_window_end_at": None,
        }
    )
    db.campaigns[record["id"]] = record

    furnace["campaign_count"] = int(furnace["campaign_count"]) + 1
    touch(furnace)
    return success(record, 201)


@bp.get("/glass-plant/campaigns/<campaign_id>")
def read_campaign(campaign_id):
    authorize("PlantManager", "PlantScheduler", "BatchHouseTech", "QualityEngineer")
    campaign = require(db.campaigns, campaign_id, "ERR_CAMPAIGN_NOT_FOUND")
    return success(campaign)


@bp.post("/glass-plant/campaigns/<campaign_id>/activate")
def activate_campaign(campaign_id):
    authorize("PlantManager")
    campaign = require(db.campaigns, campaign_id, "ERR_CAMPAIGN_NOT_FOUND")
    furnace = db.furnaces[campaign["furnace_id"]]
    if campaign["status"] != "PLANNED":
        fail("ERR_CAMPAIGN_STATE_INVALID")
    if furnace["posture"] == "COLD":
        fail("ERR_FURNACE_POSTURE_BLOCKED")
    for other in db.campaigns.values():
        if (
            other["id"] != campaign["id"]
            and other["furnace_id"] == furnace["id"]
            and other["status"] in ("ACTIVE", "WIND_DOWN")
        ):
            fail("ERR_FURNACE_CAMPAIGN_CONFLICT")

    campaign["status"] = "ACTIVE"
    days = calc.window_days(campaign["window_start_at"], campaign["window_end_at"])
    campaign["projected_refractory_units_nominal"] = calc.refractory_nominal(
        campaign["target_pull_tpd"], days, furnace["current_color"]
    )
    apply_posture(furnace)
    furnace["updated_at"] = db.clock
    touch(campaign)
    return success(campaign)


@bp.post("/glass-plant/campaigns/<campaign_id>/wind-down")
def wind_down_campaign(campaign_id):
    authorize("PlantManager")
    campaign = require(db.campaigns, campaign_id, "ERR_CAMPAIGN_NOT_FOUND")
    if campaign["status"] != "ACTIVE":
        fail("ERR_CAMPAIGN_STATE_INVALID")
    for job in campaign_jobs(campaign["id"]):
        if job["status"] == "RUNNING":
            fail("ERR_RUNNING_JOB_PRESENT")
    wind_down(campaign)
    return success(campaign)


@bp.post("/glass-plant/campaigns/<campaign_id>/schedule-rebuild")
def schedule_rebuild(campaign_id):
    authorize("PlantManager")
    data = validate_body([Ts("rebuild_window_start_at"), Ts("rebuild_window_end_at")])
    campaign = require(db.campaigns, campaign_id, "ERR_CAMPAIGN_NOT_FOUND")
    furnace = db.furnaces[campaign["furnace_id"]]
    if campaign["status"] != "WIND_DOWN":
        fail("ERR_CAMPAIGN_STATE_INVALID")
    for job in campaign_jobs(campaign["id"]):
        if job["status"] in ("SCHEDULED", "RUNNING"):
            fail("ERR_OPEN_JOBS_PRESENT")
    if not data["rebuild_window_start_at"] > campaign["window_end_at"]:
        fail("ERR_WINDOW_ORDER_INVALID")
    if not data["rebuild_window_end_at"] > data["rebuild_window_start_at"]:
        fail("ERR_WINDOW_ORDER_INVALID")

    campaign["rebuild_window_start_at"] = data["rebuild_window_start_at"]
    campaign["rebuild_window_end_at"] = data["rebuild_window_end_at"]
    campaign["status"] = "REBUILD_SCHEDULED"
    apply_posture(furnace)
    furnace["updated_at"] = db.clock
    for change in list(db.color_changes.values()):
        if (
            change["furnace_id"] == furnace["id"]
            and change["status"] == "SCHEDULED"
            and change["window_start_at"] >= data["rebuild_window_start_at"]
        ):
            change["status"] = "ABORTED"
            touch(change)
    touch(campaign)
    return success(campaign)


@bp.post("/glass-plant/campaigns/<campaign_id>/close")
def close_campaign(campaign_id):
    authorize("PlantManager")
    campaign = require(db.campaigns, campaign_id, "ERR_CAMPAIGN_NOT_FOUND")
    furnace = db.furnaces[campaign["furnace_id"]]
    if campaign["status"] != "REBUILD_SCHEDULED":
        fail("ERR_CAMPAIGN_STATE_INVALID")
    for lot in db.pack_lots.values():
        if lot["campaign_id"] == campaign["id"] and lot["quality_status"] == "PENDING_INSPECTION":
            fail("ERR_OPEN_LOTS_PRESENT")

    campaign["status"] = "CLOSED"
    reconcile_campaign(campaign)
    furnace["refractory_consumed_units"] = D("0.00")
    furnace["refractory_remaining_pct"] = D("100.00")
    apply_posture(furnace)
    furnace["updated_at"] = db.clock
    touch(campaign)
    return success(campaign)
