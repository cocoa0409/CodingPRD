"""NicuBed resource + manual stay placement (PRD §3.4)."""

from flask import Blueprint, request

import db
import services
from errors import (
    APIError,
    ERR_BED_INTERVAL_OVERLAP,
    invalid_request,
    invalid_state,
    not_found,
)
from helpers import (
    get_body,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object
from services import ACUITY_ORDER

bp = Blueprint("nicu_beds", __name__)

ACUITY_LEVELS = {"LEVEL_2", "LEVEL_3", "LEVEL_4"}
OCCUPANCY_STATUSES = {"VACANT", "OCCUPIED", "OUT_OF_SERVICE"}
STAY_STATUSES = {"PENDING_BED", "ACTIVE", "STEPPED_DOWN", "CLOSED", "CANCELLED"}


def _get_bed(bed_id):
    b = db.nicu_beds.get(bed_id)
    if b is None:
        raise not_found("NICU bed not found.")
    return b


@bp.post("/nicu-beds")
def create_bed():
    require_roles("Neonatologist", "RegistrySupervisor")
    body = get_body()
    bed_label = require_field(body, "bed_label", str)
    acuity_level = require_field(body, "acuity_level", str)
    require_enum(acuity_level, "acuity_level", ACUITY_LEVELS)
    row = {
        "id": db.new_id(),
        "bed_label": bed_label,
        "acuity_level": acuity_level,
        "occupancy_status": "VACANT",
        "current_stay_id": None,
    }
    db.stamp_create(row)
    db.nicu_beds[row["id"]] = row
    return ok_object(db.public(row), 201)


@bp.get("/nicu-beds/<bed_id>")
def get_bed(bed_id):
    require_roles("Neonatologist", "RegistrySupervisor")
    return ok_object(db.public(_get_bed(bed_id)))


@bp.get("/nicu-beds")
def list_beds():
    require_roles("Neonatologist", "RegistrySupervisor")
    limit, offset = parse_pagination()
    occupancy_status = request.args.get("occupancy_status")
    rows = list(db.nicu_beds.values())
    if occupancy_status is not None:
        require_enum(occupancy_status, "occupancy_status", OCCUPANCY_STATUSES)
        rows = [r for r in rows if r["occupancy_status"] == occupancy_status]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array([db.public(r) for r in page], limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.get("/nicu-beds/<bed_id>/nicu-stays")
def list_bed_stays(bed_id):
    require_roles("Neonatologist", "RegistrySupervisor")
    _get_bed(bed_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    rows = [s for s in db.nicu_stays.values() if s["nicu_bed_id"] == bed_id]
    if status is not None:
        require_enum(status, "status", STAY_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array([db.public(r) for r in page], limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.post("/nicu-beds/<bed_id>/assign-stay")
def assign_stay(bed_id):
    require_roles("Neonatologist")
    bed = _get_bed(bed_id)
    body = get_body()
    nicu_stay_id = require_field(body, "nicu_stay_id", str)
    stay = db.nicu_stays.get(nicu_stay_id)
    if stay is None:
        raise not_found("nicu_stay_id does not resolve to a NICU stay.")

    # State (priority 5): stay must be PENDING_BED.
    if stay["status"] != "PENDING_BED":
        raise invalid_state("Only a PENDING_BED stay may be manually placed.")
    # Target bed must be VACANT with sufficient acuity.
    if bed["occupancy_status"] != "VACANT":
        raise invalid_state("Target bed is not VACANT.")
    if ACUITY_ORDER[bed["acuity_level"]] < ACUITY_ORDER[stay["required_level"]]:
        raise invalid_state("Bed acuity_level is below the stay's required_level.")

    # Interval-overlap (priority 17): half-open [admitted_at, discharged_at).
    # discharged_at None => open-ended (treat as +inf).
    new_start = db.parse_iso(stay["admitted_at"])
    new_end = db.parse_iso(stay["discharged_at"]) if stay["discharged_at"] else None
    for prior in db.nicu_stays.values():
        if prior["id"] == stay["id"]:
            continue
        if prior["nicu_bed_id"] != bed_id:
            continue
        p_start = db.parse_iso(prior["admitted_at"])
        p_end = db.parse_iso(prior["discharged_at"]) if prior["discharged_at"] else None
        if _intervals_overlap(new_start, new_end, p_start, p_end):
            raise APIError(ERR_BED_INTERVAL_OVERLAP,
                           "Stay interval overlaps a prior stay on this bed.", 409)

    actor = request.headers.get("X-User-Role")
    services.occupy_bed(bed, stay)
    services.append_audit("NICU_BED_ASSIGNED", actor, stay["newborn_id"],
                          {"nicu_stay_id": stay["id"], "nicu_bed_id": bed_id})
    return ok_object(db.public(stay))


def _intervals_overlap(a_start, a_end, b_start, b_end) -> bool:
    """Half-open [start, end) overlap. None end => open-ended (+inf).
    Overlap iff a_start < b_end AND b_start < a_end (shared interior time)."""
    cond1 = (b_end is None) or (a_start < b_end)
    cond2 = (a_end is None) or (b_start < a_end)
    return cond1 and cond2
