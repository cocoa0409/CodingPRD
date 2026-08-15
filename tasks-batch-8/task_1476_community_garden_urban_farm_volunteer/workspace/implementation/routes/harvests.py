"""Harvest logs: create gates per PRD 3.8 (a refining section), PATCH, transitions."""
from flask import Blueprint, request

import clock
import db
import services
from app_util import body
from errors import err, err_forbidden_role, err_invalid_request, err_not_found, err_ownership, err_sod, err_state
from middleware import ALL_ROLES, require_auth, require_role
from response import ok
from util import opt_bool, opt_int, pagination_args, parse_dt, req_bool, req_enum, req_int, req_str, require_field

bp = Blueprint("harvests", __name__)

FOUR = ["GardenAdmin", "Coordinator", "Volunteer", "GroupLeader"]
FIVE = ["GardenAdmin", "Coordinator", "Volunteer", "GroupLeader", "FoodSafetyOfficer"]
OFFICERS = ["GardenAdmin", "FoodSafetyOfficer"]
GRADES = {"A", "B", "C"}
HARVEST_TARGETS = {"SUBMITTED", "VERIFIED", "REJECTED", "DRAFT", "DISCARDED"}


def _get_harvest(harvest_id):
    log = db.harvests.get(harvest_id)
    if log is None:
        raise err_not_found("harvest")
    return log


@bp.post("/api/harvest-logs")
def create_harvest():
    ctx = require_auth()
    require_role(ctx, FOUR)
    data = body()
    # existence (tier 3), body FKs in declared input order
    season_id = require_field(data, "season_id")
    season = db.seasons.get(season_id)
    if season is None:
        raise err_not_found("season")
    bed_id = require_field(data, "bed_id")
    bed = db.beds.get(bed_id)
    if bed is None:
        raise err_not_found("bed")
    logger_id = require_field(data, "logged_by_volunteer_id")
    logger = db.volunteers.get(logger_id)
    if logger is None:
        raise err_not_found("volunteer")
    crop_plan_id = data.get("crop_plan_id")
    if crop_plan_id is not None and db.crop_plans.get(crop_plan_id) is None:
        raise err_not_found("crop_plan")
    # ownership (tier 4)
    if ctx.role in {"Volunteer", "GroupLeader"} and ctx.user_id != logger_id:
        raise err_ownership()
    # shape (tier 5)
    crop_type = req_str(data, "crop_type")
    weight = req_int(data, "weight_grams")
    if weight <= 0:
        raise err_invalid_request("weight_grams must be > 0")
    grade = req_enum(data, "quality_grade", GRADES)
    harvested_at = parse_dt(require_field(data, "harvested_at"), "harvested_at")
    attestation = require_field(data, "safety_attestation")
    if not isinstance(attestation, bool):
        raise err_invalid_request("safety_attestation must be a boolean")
    # --- PRD 3.8 workflow gate sequence ---
    if season["status"] != "HARVESTING":
        raise err("ERR_SEASON_NOT_ACCEPTING", "season must be HARVESTING to log harvests")
    if bed["status"] != "HARVEST_OPEN":
        raise err("ERR_BED_NOT_HARVEST_OPEN", "bed must be HARVEST_OPEN to log harvests")
    if logger["orientation_status"] != "ORIENTED":
        raise err("ERR_ORIENTATION_REQUIRED", "logger orientation_status is not ORIENTED")
    if logger["waiver_status"] != "SIGNED":
        raise err("ERR_WAIVER_REQUIRED", "logger waiver_status is not SIGNED")
    if logger["standing"] == "SUSPENDED":
        raise err("ERR_VOLUNTEER_SUSPENDED", "logger is SUSPENDED")
    if not services.has_active_cert(logger_id, "PRODUCE_SAFETY"):
        raise err("ERR_PRODUCE_SAFETY_CERT_REQUIRED",
                  "logger must hold an ACTIVE PRODUCE_SAFETY certification")
    if attestation is not True:
        raise err("ERR_SAFETY_ATTESTATION_REQUIRED", "safety_attestation must be true")
    if not (season["season_starts_at"] <= harvested_at <= season["season_ends_at"]):
        raise err("ERR_OUTSIDE_SEASON_WINDOW", "harvested_at lies outside the season window")
    if harvested_at > clock.now():
        raise err("ERR_HARVEST_IN_FUTURE", "harvested_at must not be after the current clock")
    rec = services.create_record({
        "season_id": season_id,
        "bed_id": bed_id,
        "crop_plan_id": crop_plan_id,
        "logged_by_volunteer_id": logger_id,
        "crop_type": crop_type,
        "weight_grams": weight,
        "quality_grade": grade,
        "harvested_at": harvested_at,
        "safety_attestation": attestation,
        "rejection_reason": None,
        "status": "DRAFT",
    })
    db.harvests[rec["id"]] = rec
    return ok(services.harvest_view(rec), status=201)


@bp.get("/api/harvest-logs")
def list_harvests():
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    limit, offset = pagination_args(request.args)
    items = services.list_view(
        db.harvests.values(),
        {"season_id": "season_id", "bed_id": "bed_id",
         "logged_by_volunteer_id": "logged_by_volunteer_id", "status": "status",
         "crop_plan_id": "crop_plan_id"},
        request.args, services.harvest_view,
    )
    total = len(items)
    return ok([services.harvest_view(h) for h in items[offset:offset + limit]],
              pagination=(limit, offset, total))


@bp.get("/api/harvest-logs/<harvestLogId>")
def get_harvest(harvestLogId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    return ok(services.harvest_view(_get_harvest(harvestLogId)))


@bp.patch("/api/harvest-logs/<harvestLogId>")
def patch_harvest(harvestLogId):
    ctx = require_auth()
    require_role(ctx, FOUR)
    log = _get_harvest(harvestLogId)
    data = body()
    # body FK existence (tier 3): crop_plan_id when provided
    if "crop_plan_id" in data and data["crop_plan_id"] is not None \
            and db.crop_plans.get(data["crop_plan_id"]) is None:
        raise err_not_found("crop_plan")
    # ownership (tier 4)
    if ctx.role in {"Volunteer", "GroupLeader"} and ctx.user_id != log["logged_by_volunteer_id"]:
        raise err_ownership()
    # shape of provided fields (tier 5)
    updates = {}
    if data.get("crop_type") is not None:
        updates["crop_type"] = req_str(data, "crop_type")
    if data.get("weight_grams") is not None:
        w = req_int(data, "weight_grams")
        if w <= 0:
            raise err_invalid_request("weight_grams must be > 0")
        updates["weight_grams"] = w
    if data.get("quality_grade") is not None:
        updates["quality_grade"] = req_enum(data, "quality_grade", GRADES)
    if data.get("harvested_at") is not None:
        updates["harvested_at"] = parse_dt(data["harvested_at"], "harvested_at")
    if data.get("safety_attestation") is not None:
        updates["safety_attestation"] = req_bool(data, "safety_attestation")
    if "crop_plan_id" in data:
        updates["crop_plan_id"] = data["crop_plan_id"]
    # from-state (tier 6): only DRAFT logs are editable
    if log["status"] != "DRAFT":
        raise err_state("HARVEST")
    log.update(updates)
    services.bump(log)
    return ok(services.harvest_view(log))


@bp.post("/api/harvest-logs/<harvestLogId>/transition")
def transition_harvest(harvestLogId):
    ctx = require_auth()
    require_role(ctx, FIVE)
    log = _get_harvest(harvestLogId)
    data = body()
    to_state = req_str(data, "to_state")
    if to_state not in HARVEST_TARGETS:
        raise err_invalid_request(f"to_state must be one of {sorted(HARVEST_TARGETS)}")
    # per-transition actors
    if to_state in {"VERIFIED", "REJECTED"} and ctx.role not in OFFICERS:
        raise err_forbidden_role()
    if to_state in {"SUBMITTED", "DRAFT", "DISCARDED"} and ctx.role not in FOUR:
        raise err_forbidden_role()
    # ownership (tier 4): self-service transitions act on own logs only
    if to_state in {"SUBMITTED", "DRAFT", "DISCARDED"} \
            and ctx.role in {"Volunteer", "GroupLeader"} \
            and ctx.user_id != log["logged_by_volunteer_id"]:
        raise err_ownership()
    # SoD (tier 4): verifier must not be the logger (GardenAdmin identity is opaque)
    if to_state == "VERIFIED" and ctx.role != "GardenAdmin" \
            and ctx.user_id == log["logged_by_volunteer_id"]:
        raise err_sod()

    if to_state == "SUBMITTED":
        if log["status"] != "DRAFT":
            raise err_state("HARVEST")
        if log["safety_attestation"] is not True:
            raise err("ERR_SAFETY_ATTESTATION_REQUIRED", "safety_attestation must be true")
        if not services.has_active_cert(log["logged_by_volunteer_id"], "PRODUCE_SAFETY"):
            raise err("ERR_PRODUCE_SAFETY_CERT_REQUIRED",
                      "logger must hold an ACTIVE PRODUCE_SAFETY certification at submit time")
        log["status"] = "SUBMITTED"
        services.bump(log)

    elif to_state == "VERIFIED":
        if log["status"] != "SUBMITTED":
            raise err_state("HARVEST")
        if not services.has_active_cert(log["logged_by_volunteer_id"], "PRODUCE_SAFETY"):
            raise err("ERR_PRODUCE_SAFETY_CERT_REQUIRED",
                      "logger must still hold an ACTIVE PRODUCE_SAFETY certification")
        log["status"] = "VERIFIED"
        services.bump(log)

    elif to_state == "REJECTED":
        reason = data.get("rejection_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise err_invalid_request("rejection_reason must be non-empty")
        if log["status"] != "SUBMITTED":
            raise err_state("HARVEST")
        log["status"] = "REJECTED"
        log["rejection_reason"] = reason
        services.bump(log)

    elif to_state == "DRAFT":
        if log["status"] != "REJECTED":
            raise err_state("HARVEST")
        log["status"] = "DRAFT"
        log["rejection_reason"] = None
        services.bump(log)

    elif to_state == "DISCARDED":
        if log["status"] != "DRAFT":
            raise err_state("HARVEST")
        log["status"] = "DISCARDED"
        services.bump(log)

    return ok(services.harvest_view(log))
