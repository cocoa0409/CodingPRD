"""Crop plans (PRD section 3.4)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import services
from app_util import body
from errors import err, err_forbidden_role, err_invalid_request, err_not_found, err_ownership, err_state
from middleware import ALL_ROLES, require_auth, require_role
from response import ok
from util import opt_int, opt_str, pagination_args, parse_date, req_int, req_str, require_field

bp = Blueprint("crop_plans", __name__)

FOUR = ["GardenAdmin", "Coordinator", "Volunteer", "GroupLeader"]
PLAN_TARGETS = {"APPROVED", "REJECTED", "PROPOSED", "PLANTED", "COMPLETE", "WITHDRAWN"}
STAFF = ["GardenAdmin", "Coordinator"]


@bp.post("/api/crop-plans")
def create_crop_plan():
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
    proposer_id = require_field(data, "proposer_volunteer_id")
    if db.volunteers.get(proposer_id) is None:
        raise err_not_found("volunteer")
    # ownership (tier 4)
    if ctx.role in {"Volunteer", "GroupLeader"} and ctx.user_id != proposer_id:
        raise err_ownership()
    # shape (tier 5)
    crop_type = req_str(data, "crop_type")
    plant_family = req_str(data, "plant_family")
    requested = req_int(data, "requested_sq_ft")
    if requested <= 0:
        raise err_invalid_request("requested_sq_ft must be > 0")
    start = parse_date(require_field(data, "planned_start_date"), "planned_start_date")
    end = parse_date(require_field(data, "planned_end_date"), "planned_end_date")
    if end <= start:
        raise err_invalid_request("planned_end_date must be strictly after planned_start_date")
    expected_yield = opt_int(data, "expected_yield_grams", 0)
    if expected_yield < 0:
        raise err_invalid_request("expected_yield_grams must be >= 0")
    # cross-entity guards (tier 7)
    if season["status"] not in {"OPEN_ENROLLMENT", "PLANTING"}:
        raise err("ERR_SEASON_NOT_ACCEPTING", "season is not accepting crop plans")
    if bed["status"] == "OUT_OF_SERVICE":
        raise err("ERR_BED_NOT_AVAILABLE", "bed is OUT_OF_SERVICE")
    rec = services.create_record({
        "season_id": season_id,
        "bed_id": bed_id,
        "proposer_volunteer_id": proposer_id,
        "crop_type": crop_type,
        "plant_family": plant_family,
        "requested_sq_ft": requested,
        "planned_start_date": start,
        "planned_end_date": end,
        "expected_yield_grams": expected_yield,
        "rejection_reason": None,
        "status": "PROPOSED",
    })
    db.crop_plans[rec["id"]] = rec
    return ok(services.crop_plan_view(rec), status=201)


@bp.get("/api/crop-plans")
def list_crop_plans():
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    limit, offset = pagination_args(request.args)
    items = services.list_view(
        db.crop_plans.values(),
        {"season_id": "season_id", "bed_id": "bed_id",
         "proposer_volunteer_id": "proposer_volunteer_id", "status": "status"},
        request.args, services.crop_plan_view,
    )
    total = len(items)
    return ok([services.crop_plan_view(p) for p in items[offset:offset + limit]],
              pagination=(limit, offset, total))


def _get_plan(cropPlanId):
    plan = db.crop_plans.get(cropPlanId)
    if plan is None:
        raise err_not_found("crop_plan")
    return plan


@bp.get("/api/crop-plans/<cropPlanId>")
def get_crop_plan(cropPlanId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    return ok(services.crop_plan_view(_get_plan(cropPlanId)))


def _occupancy_conflict(bed_id: str, candidate: dict) -> bool:
    """14-day cover-crop buffer rule; adjacency forbidden (strict <)."""
    buf = timedelta(days=services.BED_BUFFER_DAYS)
    a_start, a_end = candidate["planned_start_date"], candidate["planned_end_date"]
    for other in db.crop_plans.values():
        if other["id"] == candidate["id"]:
            continue
        if other["bed_id"] != bed_id or other["status"] not in services.PLAN_ALLOCATING:
            continue
        b_start, b_end = other["planned_start_date"], other["planned_end_date"]
        if not ((a_end + buf) < b_start or (b_end + buf) < a_start):
            return True
    return False


@bp.post("/api/crop-plans/<cropPlanId>/transition")
def transition_crop_plan(cropPlanId):
    ctx = require_auth()
    require_role(ctx, FOUR)
    plan = _get_plan(cropPlanId)
    data = body()
    to_state = req_str(data, "to_state")
    if to_state not in PLAN_TARGETS:
        raise err_invalid_request(f"to_state must be one of {sorted(PLAN_TARGETS)}")
    # per-transition actors: APPROVED / REJECTED / COMPLETE are staff-only
    if to_state in {"APPROVED", "REJECTED", "COMPLETE"} and ctx.role not in STAFF:
        raise err_forbidden_role()
    # ownership (tier 4) for self-service transitions
    if ctx.role in {"Volunteer", "GroupLeader"} and ctx.user_id != plan["proposer_volunteer_id"]:
        raise err_ownership()

    bed = db.beds.get(plan["bed_id"])
    season = db.seasons.get(plan["season_id"])

    if to_state == "APPROVED":
        if plan["status"] != "PROPOSED":
            raise err_state("CROP_PLAN")
        if season is None or season["status"] not in {"OPEN_ENROLLMENT", "PLANTING"}:
            raise err("ERR_SEASON_NOT_ACCEPTING", "season is not accepting plan approvals")
        if bed is None or bed["status"] not in {"FALLOW", "RESERVED"}:
            raise err("ERR_BED_NOT_AVAILABLE", "bed must be FALLOW or RESERVED for approval")
        # tier order: rotation (12) -> occupancy (13) -> capacity (14)
        if bed["last_plant_family"] is not None and plan["plant_family"] == bed["last_plant_family"]:
            raise err("ERR_CROP_ROTATION_VIOLATION",
                      "plant_family matches the bed's most recently completed family")
        if _occupancy_conflict(plan["bed_id"], plan):
            raise err("ERR_BED_OCCUPANCY_OVERLAP",
                      "occupancy windows violate the 14-day buffer rule")
        allocated = services.bed_allocated_sq_ft(plan["bed_id"])
        if allocated + plan["requested_sq_ft"] > bed["size_sq_ft"]:
            raise err("ERR_BED_CAPACITY_EXCEEDED", "bed capacity exceeded")
        plan["status"] = "APPROVED"
        services.bump(plan)
        services.bump(bed)

    elif to_state == "REJECTED":
        reason = data.get("rejection_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise err_invalid_request("rejection_reason must be non-empty")
        if plan["status"] != "PROPOSED":
            raise err_state("CROP_PLAN")
        plan["status"] = "REJECTED"
        plan["rejection_reason"] = reason
        services.bump(plan)

    elif to_state == "PROPOSED":
        if plan["status"] != "REJECTED":
            raise err_state("CROP_PLAN")
        # optional field updates on resubmit
        new_sq_ft = plan["requested_sq_ft"]
        if data.get("requested_sq_ft") is not None:
            new_sq_ft = req_int(data, "requested_sq_ft")
            if new_sq_ft <= 0:
                raise err_invalid_request("requested_sq_ft must be > 0")
        new_start = plan["planned_start_date"]
        if data.get("planned_start_date") is not None:
            new_start = parse_date(data["planned_start_date"], "planned_start_date")
        new_end = plan["planned_end_date"]
        if data.get("planned_end_date") is not None:
            new_end = parse_date(data["planned_end_date"], "planned_end_date")
        if new_end <= new_start:
            raise err_invalid_request("planned_end_date must be strictly after planned_start_date")
        if data.get("crop_type") is not None:
            plan["crop_type"] = req_str(data, "crop_type")
        if data.get("plant_family") is not None:
            plan["plant_family"] = req_str(data, "plant_family")
        plan["requested_sq_ft"] = new_sq_ft
        plan["planned_start_date"] = new_start
        plan["planned_end_date"] = new_end
        plan["rejection_reason"] = None
        plan["status"] = "PROPOSED"
        services.bump(plan)

    elif to_state == "PLANTED":
        if plan["status"] != "APPROVED":
            raise err_state("CROP_PLAN")
        if season is None or season["status"] != "PLANTING":
            raise err("ERR_SEASON_NOT_ACCEPTING", "season must be PLANTING")
        if bed is None or bed["status"] not in {"RESERVED", "PLANTED"}:
            raise err("ERR_BED_NOT_AVAILABLE", "bed must be RESERVED or PLANTED")
        plan["status"] = "PLANTED"
        services.bump(plan)

    elif to_state == "COMPLETE":
        if plan["status"] != "HARVESTING":
            raise err_state("CROP_PLAN")
        plan["status"] = "COMPLETE"
        services.bump(plan)
        if bed is not None:
            bed["last_plant_family"] = plan["plant_family"]
            services.bump(bed)

    elif to_state == "WITHDRAWN":
        if plan["status"] not in {"PROPOSED", "APPROVED"}:
            raise err_state("CROP_PLAN")
        was_approved = plan["status"] == "APPROVED"
        plan["status"] = "WITHDRAWN"
        services.bump(plan)
        if was_approved and bed is not None:
            services.bump(bed)

    return ok(services.crop_plan_view(plan))
