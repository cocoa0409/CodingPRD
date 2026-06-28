from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import auth
from response import object_response, list_response
from services import calc, domain
from services.query import get_or_404, get_ref_or_404, paginate
from validate import (
    get_body, req_str, req_int, opt_int, req_number, pagination_params,
)

bp = Blueprint("chambers", __name__)


@bp.route("/restoration/chambers", methods=["POST"])
def create_chamber():
    auth(["Technician"])
    body = get_body()
    # priority 4: body FK existence (job_id) before priority 5 field validity.
    job_id = req_str(body, "job_id")
    job = get_ref_or_404(db.jobs, job_id)

    room_label = req_str(body, "room_label")
    floor_area_sqft = req_int(body, "floor_area_sqft", minimum=0)
    wet_wall_linear_ft = opt_int(body, "wet_wall_linear_ft", default=0, minimum=0)
    dehu_ppd_rating = req_int(body, "dehu_ppd_rating", minimum=1)
    dry_standard_pct = req_number(body, "dry_standard_pct")

    # priority 10: room_label unique among the job's non-DECOMMISSIONED chambers.
    for c in domain.non_decommissioned_chambers(job_id):
        if c["room_label"] == room_label:
            raise err("ERR_DUPLICATE_ROOM_LABEL",
                      "room_label already used by a non-DECOMMISSIONED chamber on the job.")

    klass = calc.sizing_class(job)
    air_movers_required = calc.compute_air_movers_required(
        floor_area_sqft, wet_wall_linear_ft, klass)
    dehumidifiers_required = calc.compute_dehumidifiers_required(
        floor_area_sqft, dehu_ppd_rating, klass)

    entity = {
        "job_id": job_id,
        "room_label": room_label,
        "floor_area_sqft": floor_area_sqft,
        "wet_wall_linear_ft": wet_wall_linear_ft,
        "dehu_ppd_rating": dehu_ppd_rating,
        "dry_standard_pct": dry_standard_pct,
        "latest_moisture_content_pct": None,
        "is_dry": False,
        "air_movers_required": air_movers_required,
        "dehumidifiers_required": dehumidifiers_required,
        "status": "OPEN",
    }
    stamp_create(entity)
    db.chambers[entity["id"]] = entity
    return object_response(entity, status=201)


@bp.route("/restoration/chambers/<chamber_id>", methods=["GET"])
def get_chamber(chamber_id):
    auth(["Technician", "Dispatcher", "Adjuster", "PlatformAdmin"])
    return object_response(get_or_404(db.chambers, chamber_id))


@bp.route("/restoration/chambers", methods=["GET"])
def list_chambers():
    auth(["Technician", "Dispatcher", "Adjuster", "PlatformAdmin"])
    job_id = request.args.get("job_id")
    status = request.args.get("status")
    limit, offset = pagination_params()

    items = list(db.chambers.values())
    if job_id is not None:
        items = [c for c in items if c["job_id"] == job_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/restoration/chambers/<chamber_id>/decommission", methods=["POST"])
def decommission_chamber(chamber_id):
    auth(["Technician"])
    chamber = get_or_404(db.chambers, chamber_id)

    # priority 6: state validity — only OPEN or DRIED may decommission.
    if chamber["status"] not in ("OPEN", "DRIED"):
        raise err("ERR_INVALID_STATE",
                  "Chamber cannot be decommissioned from its current state.")

    # business rule: no ACTIVE placement may reference this chamber.
    if domain.active_placements_for_chamber(chamber_id):
        raise err("ERR_CHAMBER_HAS_EQUIPMENT",
                  "Chamber still holds an ACTIVE equipment placement.")

    chamber["status"] = "DECOMMISSIONED"
    touch(chamber)

    job = db.jobs.get(chamber["job_id"])
    if job is not None:
        domain.on_chamber_decommissioned(job)
    return object_response(chamber)


@bp.route("/restoration/chambers/<chamber_id>/readings", methods=["POST"])
def create_reading(chamber_id):
    auth(["Technician"])
    chamber = get_or_404(db.chambers, chamber_id)
    body = get_body()
    temp_f = req_number(body, "temp_f")
    relative_humidity_pct = req_number(body, "relative_humidity_pct", minimum=0, maximum=100)
    moisture_content_pct = req_number(body, "moisture_content_pct")

    job = db.jobs.get(chamber["job_id"])

    gpp = calc.compute_gpp(temp_f, relative_humidity_pct)

    reading = {
        "job_id": chamber["job_id"],
        "chamber_id": chamber_id,
        "monitoring_day": job["monitoring_day"] if job is not None else 0,
        "temp_f": temp_f,
        "relative_humidity_pct": relative_humidity_pct,
        "moisture_content_pct": moisture_content_pct,
        "gpp": gpp,
    }
    # MoistureReading is immutable: only id + created_at (PRD §2.4).
    stamp_create(reading, with_version=False)
    db.readings[reading["id"]] = reading

    # Recompute chamber dry state / auto-transition, then bubble up to the job.
    if job is not None:
        domain.on_reading_logged(chamber, job)
    else:
        domain.recompute_chamber_dry(chamber)

    return object_response(reading, status=201)
