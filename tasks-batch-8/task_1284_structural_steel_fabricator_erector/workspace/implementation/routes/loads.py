"""Shipping load endpoints: create (laydown buffer), line add/remove
(capacity, STAGING<->LOADING), ship (readiness + AISC hold)."""

from flask import Blueprint

import domain
from envelope import ok_object
from errors import (
    ApiError,
    ERR_AISC_HOLD_ACTIVE,
    ERR_CROSS_JOB_REFERENCE,
    ERR_INVALID_STATE,
    ERR_LAYDOWN_SLOT_CONFLICT,
    ERR_LOAD_NUMBER_NOT_UNIQUE,
    ERR_LOAD_OVERWEIGHT,
    ERR_NOT_FOUND,
    ERR_PIECES_NOT_READY,
)
from store import new_record, store, touch, public
from validate import authenticate, get_body, req_date, req_pos_int, req_str, require_role
from . import list_response

bp = Blueprint("loads", __name__)

FOREMAN = {"FOREMAN"}
READERS = {"FABRICATOR_ADMIN", "DETAILER", "EOR", "FOREMAN", "WELDER", "QC_INSPECTOR", "GC_PM"}


def view(l):
    l["total_weight_lbs"] = domain.load_total_weight(l["id"])
    return public(l)


def piece_view(p):
    return public(p)


def get_load_or_404(lid):
    l = store.loads.get(lid)
    if l is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Shipping load not found.")
    return l


@bp.post("/shipping-loads")
def create_load():
    uid, role = authenticate()
    require_role(role, FOREMAN)
    body = get_body()
    # Rung 3: body FK existence
    job_id = body.get("job_id")
    if job_id is not None and job_id not in store.jobs:
        raise ApiError(ERR_NOT_FOUND, 404, "Job not found.")
    # Rung 4: shape
    job_id = req_str(body, "job_id")
    load_number = req_str(body, "load_number")
    laydown_slot = req_str(body, "laydown_slot")
    delivery_date = req_date(body, "delivery_date")
    trailer_capacity_lbs = req_pos_int(body, "trailer_capacity_lbs")
    # Rung 9: uniqueness first, then the buffered laydown conflict
    if any(
        l for l in store.loads.values() if l["job_id"] == job_id and l["load_number"] == load_number
    ):
        raise ApiError(ERR_LOAD_NUMBER_NOT_UNIQUE, 409, "load_number already exists within the job.")
    if domain.laydown_slot_conflict(laydown_slot, delivery_date):
        raise ApiError(
            ERR_LAYDOWN_SLOT_CONFLICT,
            409,
            "Another STAGING/LOADING load holds this laydown_slot within +/-2 days.",
        )
    l = new_record()
    l.update(
        {
            "job_id": job_id,
            "load_number": load_number,
            "laydown_slot": laydown_slot,
            "delivery_date": delivery_date.isoformat(),
            "trailer_capacity_lbs": trailer_capacity_lbs,
            "total_weight_lbs": 0,
            "status": "STAGING",
        }
    )
    store.loads[l["id"]] = l
    return ok_object(view(l), 201)


@bp.get("/shipping-loads")
def list_loads():
    uid, role = authenticate()
    require_role(role, READERS)
    return list_response(store.loads.values(), view, [("job_id", "job_id"), ("status", "status")])


@bp.get("/shipping-loads/<lid>")
def get_load(lid):
    uid, role = authenticate()
    require_role(role, READERS)
    return ok_object(view(get_load_or_404(lid)))


@bp.get("/shipping-loads/<lid>/lines")
def list_lines(lid):
    uid, role = authenticate()
    require_role(role, READERS)
    load = get_load_or_404(lid)
    return list_response(domain.load_lines(load["id"]), piece_view, [])


@bp.post("/shipping-loads/<lid>/lines")
def add_line(lid):
    uid, role = authenticate()
    require_role(role, FOREMAN)
    load = get_load_or_404(lid)
    body = get_body()
    piece_id = body.get("piece_id")
    if piece_id is not None and piece_id not in store.pieces:
        raise ApiError(ERR_NOT_FOUND, 404, "Piece not found.")
    piece_id = req_str(body, "piece_id")
    piece = store.pieces[piece_id]
    # Rung 6: line edits only while STAGING or LOADING; the candidate piece
    # must be READY_TO_SHIP and not already on a load
    if load["status"] not in ("STAGING", "LOADING"):
        raise ApiError(ERR_INVALID_STATE, 409, "Line edits require load STAGING or LOADING.")
    if piece["status"] != "READY_TO_SHIP":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a READY_TO_SHIP piece can be added to a load.")
    if piece["load_id"] is not None:
        raise ApiError(ERR_INVALID_STATE, 409, "Piece is already on a load.")
    # Rung 8: same-job consistency
    if piece["job_id"] != load["job_id"]:
        raise ApiError(ERR_CROSS_JOB_REFERENCE, 409, "piece_id belongs to a different job.")
    # Rung 9: trailer capacity gate; landing exactly on capacity is accepted
    current_total = domain.load_total_weight(load["id"])
    if current_total + piece["weight_lbs"] > load["trailer_capacity_lbs"]:
        raise ApiError(ERR_LOAD_OVERWEIGHT, 409, "Load total plus candidate exceeds trailer capacity.")
    piece["load_id"] = load["id"]
    touch(piece)
    load["total_weight_lbs"] = domain.load_total_weight(load["id"])
    if load["status"] == "STAGING":
        load["status"] = "LOADING"  # first line flips STAGING -> LOADING
    touch(load)
    return ok_object(view(load), 201)


@bp.delete("/shipping-loads/<lid>/lines/<piece_id>")
def remove_line(lid, piece_id):
    uid, role = authenticate()
    require_role(role, FOREMAN)
    # Path ids resolve left to right: load first, then piece
    load = get_load_or_404(lid)
    piece = store.pieces.get(piece_id)
    if piece is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Piece not found.")
    if piece["load_id"] != load["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, "Piece is not a line of this load.")
    if load["status"] not in ("STAGING", "LOADING"):
        raise ApiError(ERR_INVALID_STATE, 409, "Line edits require load STAGING or LOADING.")
    piece["load_id"] = None
    touch(piece)
    domain.recompute_load(load)  # total recomputed; empty LOADING -> STAGING
    return ok_object(view(load))


@bp.post("/shipping-loads/<lid>/ship")
def ship_load(lid):
    uid, role = authenticate()
    require_role(role, FOREMAN)
    load = get_load_or_404(lid)
    # Rung 6
    if load["status"] != "LOADING":
        raise ApiError(ERR_INVALID_STATE, 409, "Load must be LOADING to ship.")
    # Rung 7: AISC audit hold
    job = store.jobs.get(load["job_id"])
    if job is not None and job["requires_aisc_hold"]:
        held = any(
            i
            for i in store.inspections.values()
            if i["job_id"] == job["id"] and i["kind"] == "AISC_AUDIT" and i["status"] == "PASSED"
        )
        if not held:
            raise ApiError(
                ERR_AISC_HOLD_ACTIVE,
                409,
                "Job requires a PASSED, non-VOIDED AISC_AUDIT inspection before shipping.",
            )
    # Rung 8: at least one line; every line piece READY_TO_SHIP and not stale
    lines = domain.load_lines(load["id"])
    if not lines or any(p["status"] != "READY_TO_SHIP" or p["stale_revision"] for p in lines):
        raise ApiError(
            ERR_PIECES_NOT_READY,
            409,
            "Load is empty, or a line piece is not READY_TO_SHIP, or a line piece is stale.",
        )
    for p in lines:
        p["status"] = "SHIPPED"
        touch(p)
    load["status"] = "SHIPPED"
    touch(load)
    return ok_object(view(load))
