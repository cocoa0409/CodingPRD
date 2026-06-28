from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import auth
from response import object_response, list_response
from services import domain
from services.query import get_or_404, get_ref_or_404, paginate
from validate import get_body, req_str, pagination_params

bp = Blueprint("placements", __name__)


@bp.route("/restoration/placements", methods=["POST"])
def create_placement():
    auth(["Technician"])
    body = get_body()
    # priority 4: body FK existence (job_id, chamber_id, equipment_unit_id).
    job_id = req_str(body, "job_id")
    chamber_id = req_str(body, "chamber_id")
    equipment_unit_id = req_str(body, "equipment_unit_id")
    job = get_ref_or_404(db.jobs, job_id)
    chamber = get_ref_or_404(db.chambers, chamber_id)
    unit = get_ref_or_404(db.units, equipment_unit_id)

    # priority 9: unit must be AVAILABLE and chamber must belong to the placement's job.
    if unit["status"] != "AVAILABLE" or chamber["job_id"] != job_id:
        raise err("ERR_EQUIPMENT_NOT_AVAILABLE",
                  "Equipment unit not AVAILABLE, or chamber not on the placement's job.")

    placement = {
        "job_id": job_id,
        "chamber_id": chamber_id,
        "equipment_unit_id": equipment_unit_id,
        "kind": unit["kind"],
        "placed_on_day": job["monitoring_day"],
        "removed_on_day": None,
        "billable_days": 0,
        "status": "ACTIVE",
    }
    stamp_create(placement)
    db.placements[placement["id"]] = placement

    # cross-entity side effect: unit -> DEPLOYED, active_placement_id set.
    unit["status"] = "DEPLOYED"
    unit["active_placement_id"] = placement["id"]
    touch(unit)

    return object_response(placement, status=201)


@bp.route("/restoration/placements/<placement_id>", methods=["GET"])
def get_placement(placement_id):
    auth(["Technician", "Dispatcher", "Adjuster", "PlatformAdmin"])
    return object_response(get_or_404(db.placements, placement_id))


@bp.route("/restoration/placements", methods=["GET"])
def list_placements():
    auth(["Technician", "Dispatcher", "Adjuster", "PlatformAdmin"])
    job_id = request.args.get("job_id")
    chamber_id = request.args.get("chamber_id")
    equipment_unit_id = request.args.get("equipment_unit_id")
    status = request.args.get("status")
    limit, offset = pagination_params()

    items = list(db.placements.values())
    if job_id is not None:
        items = [p for p in items if p["job_id"] == job_id]
    if chamber_id is not None:
        items = [p for p in items if p["chamber_id"] == chamber_id]
    if equipment_unit_id is not None:
        items = [p for p in items if p["equipment_unit_id"] == equipment_unit_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/restoration/placements/<placement_id>/remove", methods=["POST"])
def remove_placement(placement_id):
    auth(["Technician"])
    placement = get_or_404(db.placements, placement_id)

    # priority 6: only an ACTIVE placement may be removed.
    if placement["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE placement can be removed.")

    job = db.jobs.get(placement["job_id"])
    monitoring_day = job["monitoring_day"] if job is not None else placement["placed_on_day"]
    placement["removed_on_day"] = monitoring_day
    placement["billable_days"] = max(1, monitoring_day - placement["placed_on_day"])
    placement["status"] = "REMOVED"
    touch(placement)

    # cross-entity: unit -> AVAILABLE, active_placement_id cleared.
    unit = db.units.get(placement["equipment_unit_id"])
    if unit is not None:
        unit["status"] = "AVAILABLE"
        unit["active_placement_id"] = None
        touch(unit)

    return object_response(placement)
