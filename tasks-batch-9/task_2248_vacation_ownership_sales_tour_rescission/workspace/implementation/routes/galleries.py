"""Sales galleries, representative roster and derived posture (PRD 3.2)."""

from flask import Blueprint

import auth
import calc
import derive
import errors
import validators
from envelope import created, listing, ok
from errors import fail
from helpers import collect, get_gallery, get_rep, page
from store import db

bp = Blueprint("galleries", __name__)

REP_STATUSES = ("ACTIVE", "ON_TOUR", "RETRAINING", "SUSPENDED")


@bp.post("/sales-galleries")
def create_gallery():
    auth.require(auth.GALLERY_MANAGER)
    data = validators.body()
    name = validators.string(data, "name", 1, 120)
    site_code = validators.string(data, "site_code", 3, 8)
    if site_code != site_code.upper():
        fail(errors.ERR_INVALID_REQUEST, "site_code must be uppercase")
    capacity = validators.integer(data, "concurrent_tour_capacity", 1, 20)
    minutes = validators.integer(data, "presentation_minutes", 30, 480)
    buffer_minutes = validators.integer(
        data, "buffer_minutes", 0, 120, required=False, default=0
    )

    now = db.now()
    gallery = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "name": name,
        "site_code": site_code,
        "concurrent_tour_capacity": capacity,
        "presentation_minutes": minutes,
        "buffer_minutes": buffer_minutes,
        "status": "OPEN",
        "booked_slot_count": 0,
        "available_rep_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.galleries[gallery["id"]] = gallery
    return created(gallery)


@bp.post("/sales-galleries/<gallery_id>/set-status")
def set_gallery_status(gallery_id):
    auth.require(auth.GALLERY_MANAGER)
    data = validators.body()
    requested = validators.enum(data, "status", ("OPEN", "CLOSED"))
    gallery = get_gallery(gallery_id)
    if requested == "CLOSED":
        derive.setf(gallery, "status", "CLOSED")
    else:
        # An OPEN request is re-derived, never obeyed: no available
        # representatives lands the gallery on RESTRICTED.
        derive.setf(gallery, "available_rep_count", derive.gallery_available_reps(gallery["id"]))
        if gallery["available_rep_count"] >= 1:
            derive.setf(gallery, "status", "OPEN")
        else:
            derive.setf(gallery, "status", "RESTRICTED")
    return ok(gallery)


@bp.get("/sales-galleries/<gallery_id>")
def read_gallery(gallery_id):
    auth.require_any()
    return ok(get_gallery(gallery_id))


# --------------------------------------------------------- representatives
@bp.post("/sales-representatives")
def create_rep():
    auth.require(auth.GALLERY_MANAGER)
    data = validators.body()
    gallery_id = validators.identifier(data, "gallery_id")
    full_name = validators.string(data, "full_name", 1, 120)
    license_number = validators.string(data, "license_number", 4, 32)
    rotation_position = validators.integer(data, "rotation_position", 1, 99)

    gallery = get_gallery(gallery_id)

    for existing in db.reps.values():
        if (
            existing["gallery_id"] == gallery["id"]
            and existing["rotation_position"] == rotation_position
        ):
            fail(
                errors.ERR_ROTATION_POSITION_TAKEN,
                "rotation_position %d is taken in this gallery" % rotation_position,
            )

    now = db.now()
    rep = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "gallery_id": gallery["id"],
        "full_name": full_name,
        "license_number": license_number,
        "rotation_position": rotation_position,
        "status": "ACTIVE",
        "tours_taken_count": 0,
        "executed_agreement_count": 0,
        "rescinded_agreement_count": 0,
        "cancellation_rate": calc.rate4(0, 0),
        "compliance_strike_count": 0,
        "last_assigned_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.reps[rep["id"]] = rep
    derive.recompute_gallery_reps(gallery)
    return created(rep)


@bp.get("/sales-representatives/<rep_id>")
def read_rep(rep_id):
    auth.require_any()
    return ok(get_rep(rep_id))


@bp.get("/sales-representatives")
def list_reps():
    auth.require_any()
    limit, offset = page()
    rows = collect(
        db.reps, (("gallery_id", "gallery_id"), ("status", "status", REP_STATUSES))
    )
    return listing(rows, limit, offset)


@bp.get("/sales-representatives/<rep_id>/rescission-analysis")
def rep_rescission_analysis(rep_id):
    auth.require(auth.GALLERY_MANAGER, auth.COMPLIANCE_OFFICER, auth.PLATFORM_ADMIN)
    rep = get_rep(rep_id)
    analysis = calc.cancellation_analysis(db.agreements.values(), rep["id"], db.now())
    return ok(
        {
            "representative_id": rep["id"],
            "window_start_utc": analysis["window_start_utc"],
            "window_end_utc": analysis["window_end_utc"],
            "executed_count": analysis["executed_count"],
            "rescinded_count": analysis["rescinded_count"],
            "cancellation_rate": analysis["cancellation_rate"],
            "min_sample": analysis["min_sample"],
            "retraining_required": analysis["retraining_required"],
        }
    )
