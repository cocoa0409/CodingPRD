"""Season lifecycle and water ledger (PRD section 3.3)."""
from flask import Blueprint, request

import db
import services
from app_util import body
from errors import err, err_invalid_request, err_not_found, err_state, err_stale_version
from middleware import ALL_ROLES, require_auth, require_role
from response import ok
from util import opt_int, opt_str, pagination_args, parse_dt, req_int, req_str, require_field

bp = Blueprint("seasons", __name__)

SEASON_STATES = {"DRAFT", "OPEN_ENROLLMENT", "PLANTING", "GROWING", "HARVESTING",
                 "RECONCILIATION", "CLOSED", "CANCELLED"}
TRANSITION_TARGETS = {"OPEN_ENROLLMENT", "DRAFT", "PLANTING", "GROWING", "HARVESTING",
                      "RECONCILIATION", "CLOSED", "CANCELLED"}


@bp.post("/api/seasons")
def create_season():
    ctx = require_auth()
    require_role(ctx, ["GardenAdmin"])
    data = body()
    name = req_str(data, "name")
    signup_opens = parse_dt(require_field(data, "signup_opens_at"), "signup_opens_at")
    signup_closes = parse_dt(require_field(data, "signup_closes_at"), "signup_closes_at")
    starts = parse_dt(require_field(data, "season_starts_at"), "season_starts_at")
    ends = parse_dt(require_field(data, "season_ends_at"), "season_ends_at")
    budget = req_int(data, "water_budget_gallons")
    if signup_closes <= signup_opens:
        raise err_invalid_request("signup_closes_at must be strictly after signup_opens_at")
    if ends <= starts:
        raise err_invalid_request("season_ends_at must be strictly after season_starts_at")
    if budget <= 0:
        raise err_invalid_request("water_budget_gallons must be > 0")
    rec = services.create_record({
        "name": name,
        "signup_opens_at": signup_opens,
        "signup_closes_at": signup_closes,
        "season_starts_at": starts,
        "season_ends_at": ends,
        "water_budget_gallons": budget,
        "status": "DRAFT",
    })
    db.seasons[rec["id"]] = rec
    return ok(services.season_view(rec), status=201)


@bp.get("/api/seasons")
def list_seasons():
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    limit, offset = pagination_args(request.args)
    items = services.list_view(db.seasons.values(), {"status": "status"},
                               request.args, services.season_view)
    total = len(items)
    return ok([services.season_view(s) for s in items[offset:offset + limit]],
              pagination=(limit, offset, total))


def _get_season(season_id):
    season = db.seasons.get(season_id)
    if season is None:
        raise err_not_found("season")
    return season


@bp.get("/api/seasons/<seasonId>")
def get_season(seasonId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    return ok(services.season_view(_get_season(seasonId)))


@bp.patch("/api/seasons/<seasonId>")
def patch_season(seasonId):
    ctx = require_auth()
    require_role(ctx, ["GardenAdmin"])
    season = _get_season(seasonId)
    data = body()
    # shape (tier 5): expected_season_version is required by the OCC contract
    expected = req_int(data, "expected_season_version")
    name = opt_str(data, "name", None)
    signup_opens = parse_dt(data["signup_opens_at"], "signup_opens_at") if data.get("signup_opens_at") is not None else None
    signup_closes = parse_dt(data["signup_closes_at"], "signup_closes_at") if data.get("signup_closes_at") is not None else None
    starts = parse_dt(data["season_starts_at"], "season_starts_at") if data.get("season_starts_at") is not None else None
    ends = parse_dt(data["season_ends_at"], "season_ends_at") if data.get("season_ends_at") is not None else None
    budget = opt_int(data, "water_budget_gallons", None)
    if budget is not None and budget <= 0:
        raise err_invalid_request("water_budget_gallons must be > 0")
    new_signup_opens = signup_opens if signup_opens is not None else season["signup_opens_at"]
    new_signup_closes = signup_closes if signup_closes is not None else season["signup_closes_at"]
    new_starts = starts if starts is not None else season["season_starts_at"]
    new_ends = ends if ends is not None else season["season_ends_at"]
    if new_signup_closes <= new_signup_opens:
        raise err_invalid_request("signup_closes_at must be strictly after signup_opens_at")
    if new_ends <= new_starts:
        raise err_invalid_request("season_ends_at must be strictly after season_starts_at")
    if name is not None and not name.strip():
        raise err_invalid_request("name must be non-empty")
    # from-state (tier 6): config editable only while DRAFT or OPEN_ENROLLMENT
    if season["status"] not in {"DRAFT", "OPEN_ENROLLMENT"}:
        raise err_state("SEASON")
    # OCC (tier 17)
    if expected != season["version"]:
        raise err_stale_version()
    if name is not None:
        season["name"] = name
    season["signup_opens_at"] = new_signup_opens
    season["signup_closes_at"] = new_signup_closes
    season["season_starts_at"] = new_starts
    season["season_ends_at"] = new_ends
    if budget is not None:
        season["water_budget_gallons"] = budget
    services.bump(season)
    return ok(services.season_view(season))


@bp.post("/api/seasons/<seasonId>/transition")
def transition_season(seasonId):
    ctx = require_auth()
    require_role(ctx, ["GardenAdmin"])
    season = _get_season(seasonId)
    data = body()
    to_state = req_str(data, "to_state")
    if to_state not in TRANSITION_TARGETS:
        raise err_invalid_request(f"to_state must be one of {sorted(TRANSITION_TARGETS)}")
    sid = season["id"]
    status = season["status"]

    if to_state == "OPEN_ENROLLMENT":
        if status != "DRAFT":
            raise err_state("SEASON")
        if not any(b["status"] != "OUT_OF_SERVICE" for b in db.beds.values()):
            raise err("ERR_SEASON_GUARD_ACTIVE_BED_REQUIRED",
                      "at least one garden bed not OUT_OF_SERVICE is required")
        season["status"] = "OPEN_ENROLLMENT"
        services.bump(season)

    elif to_state == "DRAFT":
        if status != "OPEN_ENROLLMENT":
            raise err_state("SEASON")
        if (any(s["season_id"] == sid for s in db.slots.values())
                or any(p["season_id"] == sid for p in db.crop_plans.values())
                or any(i["season_id"] == sid for i in db.irrigations.values())):
            raise err("ERR_SEASON_REVERT_BLOCKED",
                      "season has slots, crop plans, or irrigation schedules")
        season["status"] = "DRAFT"
        services.bump(season)

    elif to_state == "PLANTING":
        if status != "OPEN_ENROLLMENT":
            raise err_state("SEASON")
        if not any(p["season_id"] == sid and p["status"] in {"APPROVED", "PLANTED"}
                   for p in db.crop_plans.values()):
            raise err("ERR_CROP_PLANS_UNRESOLVED",
                      "at least one crop plan must be APPROVED or PLANTED")
        season["status"] = "PLANTING"
        services.bump(season)

    elif to_state == "GROWING":
        if status != "PLANTING":
            raise err_state("SEASON")
        if any(p["season_id"] == sid and p["status"] in {"PROPOSED", "APPROVED"}
               for p in db.crop_plans.values()):
            raise err("ERR_CROP_PLANS_UNRESOLVED",
                      "crop plans remain in PROPOSED or APPROVED")
        season["status"] = "GROWING"
        services.bump(season)
        for b in db.beds.values():
            if b["status"] == "PLANTED":
                b["status"] = "GROWING"
                services.bump(b)

    elif to_state == "HARVESTING":
        if status != "GROWING":
            raise err_state("SEASON")
        if any(i["season_id"] == sid and i["status"] in {"DUE", "MISSED"}
               for i in db.irrigations.values()):
            raise err("ERR_IRRIGATION_UNRESOLVED", "irrigation schedules remain DUE or MISSED")
        season["status"] = "HARVESTING"
        services.bump(season)
        for b in db.beds.values():
            if b["status"] == "GROWING":
                b["status"] = "HARVEST_OPEN"
                services.bump(b)
                for p in db.crop_plans.values():
                    if p["bed_id"] == b["id"] and p["status"] == "PLANTED":
                        p["status"] = "HARVESTING"
                        services.bump(p)

    elif to_state == "RECONCILIATION":
        if status != "HARVESTING":
            raise err_state("SEASON")
        if any(h["season_id"] == sid and h["status"] == "SUBMITTED" for h in db.harvests.values()):
            raise err("ERR_HARVEST_LOGS_UNVERIFIED", "harvest logs remain SUBMITTED")
        season_log_ids = {h["id"] for h in db.harvests.values() if h["season_id"] == sid}
        if any(a["harvest_log_id"] in season_log_ids and a["status"] == "PENDING"
               for a in db.allocations.values()):
            raise err("ERR_ALLOCATIONS_PENDING", "donation allocations remain PENDING")
        season["status"] = "RECONCILIATION"
        services.bump(season)
        for i in db.irrigations.values():
            if i["season_id"] == sid and i["status"] in {"SCHEDULED", "DUE"}:
                i["status"] = "CANCELLED"
                services.bump(i)

    elif to_state == "CLOSED":
        if status != "RECONCILIATION":
            raise err_state("SEASON")
        if any(i["season_id"] == sid and i["status"] in {"SCHEDULED", "DUE", "MISSED", "LOGGED"}
               for i in db.irrigations.values()):
            raise err("ERR_IRRIGATION_UNRESOLVED", "irrigation schedules remain unresolved")
        if any(h["season_id"] == sid and h["status"] in {"DRAFT", "SUBMITTED", "VERIFIED"}
               for h in db.harvests.values()):
            raise err("ERR_HARVEST_LOGS_UNVERIFIED", "harvest logs remain unresolved")
        season["status"] = "CLOSED"
        services.bump(season)

    elif to_state == "CANCELLED":
        if status not in {"DRAFT", "OPEN_ENROLLMENT", "PLANTING"}:
            raise err_state("SEASON")
        season["status"] = "CANCELLED"
        services.bump(season)
        # cascade: crop plans in PROPOSED/APPROVED -> WITHDRAWN
        for p in db.crop_plans.values():
            if p["season_id"] == sid and p["status"] in {"PROPOSED", "APPROVED"}:
                was_approved = p["status"] == "APPROVED"
                p["status"] = "WITHDRAWN"
                services.bump(p)
                if was_approved:
                    bed = db.beds.get(p["bed_id"])
                    if bed is not None:
                        services.bump(bed)
        # cascade: slots in DRAFT/OPEN/FULL -> CANCELLED (with their own cascades)
        for s in db.slots.values():
            if s["season_id"] == sid and s["status"] in {"DRAFT", "OPEN", "FULL"}:
                s["status"] = "CANCELLED"
                services.bump(s)
                services.cancel_slot_cascade(s)
        # cascade: irrigation in SCHEDULED/DUE -> CANCELLED
        for i in db.irrigations.values():
            if i["season_id"] == sid and i["status"] in {"SCHEDULED", "DUE"}:
                i["status"] = "CANCELLED"
                services.bump(i)

    return ok(services.season_view(season))
