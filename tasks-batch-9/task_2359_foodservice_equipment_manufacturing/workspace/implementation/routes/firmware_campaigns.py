"""FirmwareCampaign endpoints (PRD Section 3.8)."""
from flask import Blueprint

import validate
from db import db, insert, touch, ordered
from errors import ApiError
from middleware import authorize
from response import ok, created, ok_list
from routes.helpers import find, filter_by, unique_code
from services import calc, derive

bp = Blueprint("firmware_campaigns", __name__)

STATUSES = ("DRAFT", "SCHEDULED", "RUNNING", "COMPLETED", "ROLLED_BACK")
ROLES = ("ConnectedOpsEngineer", "PlatformAdmin")


@bp.post("/firmware-campaigns")
def create_campaign():
    authorize(*ROLES)
    payload = validate.body()
    equipment_model_id = validate.string_field(payload, "equipment_model_id")
    campaign_code = validate.string_field(payload, "campaign_code", min_len=1, max_len=32)
    target_firmware_version = validate.string_field(payload, "target_firmware_version", min_len=1)
    window_start, window_end = validate.window_fields(payload)
    cohort_scope = validate.enum_field(payload, "cohort_scope", calc.COHORT_SCOPES)

    find(db.equipment_models, equipment_model_id, "ERR_EQUIPMENT_MODEL_NOT_FOUND")
    unique_code(db.firmware_campaigns, campaign_code=campaign_code)

    campaign = insert(db.firmware_campaigns, {
        "equipment_model_id": equipment_model_id,
        "campaign_code": campaign_code,
        "target_firmware_version": target_firmware_version,
        "window_start": window_start,
        "window_end": window_end,
        "cohort_scope": cohort_scope,
        "status": "DRAFT",
        "cohort_unit_ids": [],
        "success_count": 0,
        "failure_count": 0,
        "success_rate": None,
        "_unit_results": {},
    })
    return created(campaign)


@bp.get("/firmware-campaigns")
def list_campaigns():
    authorize(*ROLES)
    limit, offset = validate.pagination()
    equipment_model_id = validate.str_arg("equipment_model_id")
    status = validate.enum_arg("status", STATUSES)

    items = ordered(db.firmware_campaigns)
    items = filter_by(items, "equipment_model_id", equipment_model_id)
    items = filter_by(items, "status", status)
    return ok_list(items, limit, offset)


@bp.get("/firmware-campaigns/<campaign_id>")
def get_campaign(campaign_id):
    authorize(*ROLES)
    campaign = find(db.firmware_campaigns, campaign_id, "ERR_CONNECTED_RESOURCE_NOT_FOUND")
    return ok(campaign)


@bp.post("/firmware-campaigns/<campaign_id>/schedule")
def schedule_campaign(campaign_id):
    authorize(*ROLES)
    campaign = find(db.firmware_campaigns, campaign_id, "ERR_CONNECTED_RESOURCE_NOT_FOUND")

    if campaign["status"] != "DRAFT":
        raise ApiError("ERR_CONNECTED_STATE_INVALID",
                       "a %s campaign cannot be scheduled" % campaign["status"])

    model = db.equipment_models[campaign["equipment_model_id"]]
    if model["certification_posture"] == "SUSPENDED":
        raise ApiError("ERR_MODEL_LISTING_SUSPENDED",
                       "the model's certification posture is SUSPENDED")

    concurrent = 0
    for other in ordered(db.firmware_campaigns):
        if other["id"] == campaign["id"]:
            continue
        if other["equipment_model_id"] != campaign["equipment_model_id"]:
            continue
        if other["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        # half-open, unpadded intersection
        if other["window_start"] < campaign["window_end"] \
                and campaign["window_start"] < other["window_end"]:
            concurrent += 1
    if concurrent >= calc.MAX_CONCURRENT_CAMPAIGNS_PER_MODEL:
        raise ApiError("ERR_CAMPAIGN_WINDOW_SATURATED",
                       "the model already has %d concurrent rollouts in this window" % concurrent)

    fleet = [u for u in ordered(db.connected_units)
             if u["equipment_model_id"] == campaign["equipment_model_id"]]
    for unit in fleet:
        derive.refresh_unit_coverage(unit)
    eligible = [u for u in fleet
                if u["service_program_status"] in ("ACTIVE", "EXTENDED")
                and u["firmware_version"] != campaign["target_firmware_version"]]
    cohort_size = calc.COHORT_SIZE[campaign["cohort_scope"]]
    if len(eligible) < cohort_size:
        raise ApiError("ERR_NO_ELIGIBLE_UNITS",
                       "only %d eligible units, %d required" % (len(eligible), cohort_size))

    # sickest first: health_score ascending, created_at ascending
    by_created = sorted(eligible, key=lambda u: (u["created_at"], u["_seq"]))
    selected = sorted(by_created, key=lambda u: u["health_score"])[:cohort_size]

    campaign["status"] = "SCHEDULED"
    campaign["cohort_unit_ids"] = [u["id"] for u in selected]
    touch(campaign)
    return ok(campaign)


@bp.post("/firmware-campaigns/<campaign_id>/start")
def start_campaign(campaign_id):
    authorize(*ROLES)
    campaign = find(db.firmware_campaigns, campaign_id, "ERR_CONNECTED_RESOURCE_NOT_FOUND")

    if campaign["status"] != "SCHEDULED":
        raise ApiError("ERR_CONNECTED_STATE_INVALID",
                       "a %s campaign cannot be started" % campaign["status"])
    if db.clock < campaign["window_start"] or db.clock >= campaign["window_end"]:
        raise ApiError("ERR_CAMPAIGN_WINDOW_NOT_OPEN", "the rollout window is not open")

    campaign["status"] = "RUNNING"
    campaign["success_count"] = 0
    campaign["failure_count"] = 0
    campaign["_unit_results"] = {}
    touch(campaign)
    return ok(campaign)


@bp.post("/firmware-campaigns/<campaign_id>/unit-results")
def report_unit_result(campaign_id):
    authorize(*ROLES)
    payload = validate.body()
    connected_unit_id = validate.string_field(payload, "connected_unit_id")
    outcome = validate.enum_field(payload, "outcome", ("SUCCESS", "FAILURE"))

    campaign = find(db.firmware_campaigns, campaign_id, "ERR_CONNECTED_RESOURCE_NOT_FOUND")
    find(db.connected_units, connected_unit_id, "ERR_CONNECTED_RESOURCE_NOT_FOUND")

    if campaign["status"] != "RUNNING":
        raise ApiError("ERR_CONNECTED_STATE_INVALID",
                       "results are only accepted while the campaign is RUNNING")

    results = campaign.setdefault("_unit_results", {})
    if connected_unit_id not in campaign["cohort_unit_ids"] or connected_unit_id in results:
        raise ApiError("ERR_UNIT_NOT_IN_COHORT",
                       "the unit is not in the cohort or has already reported")

    results[connected_unit_id] = outcome
    if outcome == "SUCCESS":
        campaign["success_count"] += 1
    else:
        campaign["failure_count"] += 1
    touch(campaign)
    return ok(campaign)


@bp.post("/firmware-campaigns/<campaign_id>/close")
def close_campaign(campaign_id):
    authorize(*ROLES)
    payload = validate.body()
    disposition = validate.enum_field(payload, "disposition", ("COMPLETE", "ROLL_BACK"))

    campaign = find(db.firmware_campaigns, campaign_id, "ERR_CONNECTED_RESOURCE_NOT_FOUND")
    if campaign["status"] != "RUNNING":
        raise ApiError("ERR_CONNECTED_STATE_INVALID",
                       "a %s campaign cannot be closed" % campaign["status"])

    cohort_ids = list(campaign["cohort_unit_ids"])
    cohort_size = len(cohort_ids)
    reported = campaign["success_count"] + campaign["failure_count"]
    if cohort_size == 0 or reported != cohort_size:
        raise ApiError("ERR_CAMPAIGN_SUCCESS_RATE_TOO_LOW",
                       "every cohort unit must report before the campaign can be closed")

    success_rate = calc.round4(calc.Decimal(campaign["success_count"]) / calc.Decimal(cohort_size))
    if disposition == "COMPLETE" and success_rate < calc.MIN_SUCCESS_RATE:
        raise ApiError("ERR_CAMPAIGN_SUCCESS_RATE_TOO_LOW",
                       "the success rate %s is below the %s floor"
                       % (success_rate, calc.MIN_SUCCESS_RATE))

    results = campaign.get("_unit_results", {})
    campaign["status"] = "COMPLETED" if disposition == "COMPLETE" else "ROLLED_BACK"
    campaign["success_rate"] = float(success_rate)
    touch(campaign)

    for unit_id in cohort_ids:
        unit = db.connected_units.get(unit_id)
        if unit is None:
            continue
        if results.get(unit_id) == "SUCCESS":
            if disposition == "COMPLETE":
                if unit["firmware_version"] != campaign["target_firmware_version"]:
                    unit["firmware_version"] = campaign["target_firmware_version"]
                    touch(unit)
            else:
                unit["recipe_book_version"] += 1
                touch(unit)

    for unit_id in cohort_ids:
        unit = db.connected_units.get(unit_id)
        if unit is not None:
            derive.refresh_health_score(unit)

    return ok(campaign)
