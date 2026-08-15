"""Garden beds (PRD section 3.4)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import services
from app_util import body
from errors import err, err_forbidden_role, err_invalid_request, err_not_found, err_state
from middleware import ALL_ROLES, require_auth, require_role
from response import ok
from util import opt_str, pagination_args, req_enum, req_int, req_number, req_str

bp = Blueprint("beds", __name__)

SUN_EXPOSURES = {"FULL", "PARTIAL", "SHADE"}
BED_TARGETS = {"RESERVED", "PLANTED", "GROWING", "HARVEST_OPEN", "POST_HARVEST",
               "FALLOW", "OUT_OF_SERVICE"}


@bp.post("/api/beds")
def create_bed():
    ctx = require_auth()
    require_role(ctx, ["GardenAdmin", "Coordinator"])
    data = body()
    bed_code = req_str(data, "bed_code")
    size = req_int(data, "size_sq_ft")
    sun = req_enum(data, "sun_exposure", SUN_EXPOSURES)
    zone = req_str(data, "irrigation_zone")
    soil_ph = None
    if data.get("soil_ph") is not None:
        soil_ph = req_number(data, "soil_ph")
    if size <= 0:
        raise err_invalid_request("size_sq_ft must be > 0")
    if any(b["bed_code"] == bed_code for b in db.beds.values()):
        raise err("ERR_BED_CODE_TAKEN", "bed_code already exists")
    rec = services.create_record({
        "bed_code": bed_code,
        "size_sq_ft": size,
        "sun_exposure": sun,
        "irrigation_zone": zone,
        "soil_ph": soil_ph,
        "last_plant_family": None,
        "last_harvest_closed_at": None,
        "status": "FALLOW",
    })
    db.beds[rec["id"]] = rec
    return ok(services.bed_view(rec), status=201)


@bp.get("/api/beds")
def list_beds():
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    limit, offset = pagination_args(request.args)
    items = services.list_view(db.beds.values(),
                               {"status": "status", "irrigation_zone": "irrigation_zone"},
                               request.args, services.bed_view)
    total = len(items)
    return ok([services.bed_view(b) for b in items[offset:offset + limit]],
              pagination=(limit, offset, total))


def _get_bed(bed_id):
    bed = db.beds.get(bed_id)
    if bed is None:
        raise err_not_found("bed")
    return bed


@bp.get("/api/beds/<bedId>")
def get_bed(bedId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    return ok(services.bed_view(_get_bed(bedId)))


@bp.post("/api/beds/<bedId>/transition")
def transition_bed(bedId):
    ctx = require_auth()
    require_role(ctx, ["GardenAdmin", "Coordinator"])
    bed = _get_bed(bedId)
    data = body()
    to_state = req_str(data, "to_state")
    if to_state not in BED_TARGETS:
        raise err_invalid_request(f"to_state must be one of {sorted(BED_TARGETS)}")
    # per-transition actors: OUT_OF_SERVICE and remediation FALLOW are GardenAdmin-only
    if to_state == "OUT_OF_SERVICE" and ctx.role != "GardenAdmin":
        raise err_forbidden_role()
    if to_state == "FALLOW" and bed["status"] == "OUT_OF_SERVICE" and ctx.role != "GardenAdmin":
        raise err_forbidden_role()

    status = bed["status"]

    if to_state == "RESERVED":
        if status != "FALLOW":
            raise err_state("BED")
        if not any(s["status"] in {"OPEN_ENROLLMENT", "PLANTING"} for s in db.seasons.values()):
            raise err("ERR_SEASON_NOT_ACCEPTING", "no season is OPEN_ENROLLMENT or PLANTING")
        bed["status"] = "RESERVED"
        services.bump(bed)

    elif to_state == "PLANTED":
        if status != "RESERVED":
            raise err_state("BED")
        if not any(p["bed_id"] == bed["id"] and p["status"] in {"APPROVED", "PLANTED"}
                   for p in db.crop_plans.values()):
            raise err("ERR_CROP_PLANS_UNRESOLVED",
                      "at least one crop plan on this bed must be APPROVED or PLANTED")
        bed["status"] = "PLANTED"
        services.bump(bed)

    elif to_state == "GROWING":
        if status != "PLANTED":
            raise err_state("BED")
        bed["status"] = "GROWING"
        services.bump(bed)

    elif to_state == "HARVEST_OPEN":
        if status != "GROWING":
            raise err_state("BED")
        bed["status"] = "HARVEST_OPEN"
        services.bump(bed)
        for p in db.crop_plans.values():
            if p["bed_id"] == bed["id"] and p["status"] == "PLANTED":
                p["status"] = "HARVESTING"
                services.bump(p)

    elif to_state == "POST_HARVEST":
        if status != "HARVEST_OPEN":
            raise err_state("BED")
        if any(p["bed_id"] == bed["id"] and p["status"] in services.PLAN_ALLOCATING
               for p in db.crop_plans.values()):
            raise err("ERR_CROP_PLANS_UNRESOLVED",
                      "crop plans remain APPROVED, PLANTED, or HARVESTING on this bed")
        bed["status"] = "POST_HARVEST"
        bed["last_harvest_closed_at"] = clock.now()
        services.bump(bed)

    elif to_state == "FALLOW":
        if status == "OUT_OF_SERVICE":
            note = data.get("remediation_note")
            if not isinstance(note, str) or not note.strip():
                raise err_invalid_request("remediation_note must be non-empty")
            bed["status"] = "FALLOW"
            services.bump(bed)
        elif status == "POST_HARVEST":
            closed = bed["last_harvest_closed_at"]
            if closed is None or clock.now() < closed + timedelta(days=services.BED_BUFFER_DAYS):
                raise err("ERR_BED_REST_PERIOD_ACTIVE",
                          "bed must rest 14 days after harvest close")
            bed["status"] = "FALLOW"
            services.bump(bed)
        else:
            raise err_state("BED")

    elif to_state == "OUT_OF_SERVICE":
        if status == "OUT_OF_SERVICE":
            raise err_state("BED")
        bed["status"] = "OUT_OF_SERVICE"
        services.bump(bed)
        # cascade: PROPOSED/APPROVED plans on this bed -> WITHDRAWN (frees allocation)
        for p in db.crop_plans.values():
            if p["bed_id"] == bed["id"] and p["status"] in {"PROPOSED", "APPROVED"}:
                p["status"] = "WITHDRAWN"
                services.bump(p)

    return ok(services.bed_view(bed))
