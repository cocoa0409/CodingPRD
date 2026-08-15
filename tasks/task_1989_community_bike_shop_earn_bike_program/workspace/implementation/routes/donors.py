"""Donor registration, reads, and the annual donation receipt (PRD §3.1, §3.14)."""

from flask import Blueprint, request

from db import db, _parse_iso
from errors import ApiError
from middleware import require_roles, get_body, validate_payload
from response import success
from services.core import (make_common, paginate, sorted_by_created, fmv_bike_value,
                           FLAT_SCHEDULE_VALUE)

bp = Blueprint("donors", __name__)

RECEIPT_METHODS = ["FLAT_SCHEDULE", "FMV_COMPARABLE"]


def donor_view(d):
    return {
        "id": d["id"],
        "display_name": d["display_name"],
        "donor_type": d["donor_type"],
        "email": d["email"],
        "receipt_method": d["receipt_method"],
        "donated_bike_count": d["donated_bike_count"],
        "lifetime_receipt_value_cents": d["lifetime_receipt_value_cents"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


@bp.post("/donors")
def create_donor():
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "display_name": {"type": "string", "required": True},
        "donor_type": {"type": "string", "required": True, "enum": ["INDIVIDUAL", "ORGANIZATION"]},
        "email": {"type": "string", "required": True},
        "receipt_method": {"type": "string", "enum": RECEIPT_METHODS},
    })
    donor = make_common()
    donor.update({
        "display_name": body["display_name"],
        "donor_type": body["donor_type"],
        "email": body["email"],
        "receipt_method": body.get("receipt_method", "FLAT_SCHEDULE"),
        "donated_bike_count": 0,
        "lifetime_receipt_value_cents": 0,
    })
    db.donors[donor["id"]] = donor
    return success(donor_view(donor), status=201)


def _get_donor(donor_id):
    donor = db.donors.get(donor_id)
    if donor is None:
        raise ApiError("ERR_NOT_FOUND", f"Donor {donor_id} does not exist")
    return donor


@bp.get("/donors/<donor_id>")
def get_donor(donor_id):
    require_roles("ShopCoordinator", "ProgramDirector")
    return success(donor_view(_get_donor(donor_id)))


@bp.get("/donors")
def list_donors():
    require_roles("ShopCoordinator", "ProgramDirector")
    rows = list(db.donors.values())
    donor_type = request.args.get("donor_type")
    if donor_type is not None:
        rows = [d for d in rows if d["donor_type"] == donor_type]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([donor_view(d) for d in page], pagination=pg)


@bp.get("/donors/<donor_id>/receipt")
def donor_receipt(donor_id):
    require_roles("ShopCoordinator", "ProgramDirector")
    donor = _get_donor(donor_id)
    raw_year = request.args.get("year")
    if raw_year is None:
        year = db.now().year
    else:
        try:
            year = int(raw_year)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "year must be an integer")
    # Input set: donor's bikes created in the requested calendar year AND graded.
    bikes = [
        b for b in db.bikes.values()
        if b["donor_id"] == donor["id"]
        and b["condition_grade"] is not None
        and _parse_iso(b["created_at"]).year == year
    ]
    flat_total = sum(FLAT_SCHEDULE_VALUE[b["condition_grade"]] for b in bikes)
    fmv_total = sum(fmv_bike_value(b) for b in bikes)
    effective = flat_total if donor["receipt_method"] == "FLAT_SCHEDULE" else fmv_total
    return success({
        "donor_id": donor["id"],
        "year": year,
        "bike_count": len(bikes),
        "flat_total_cents": flat_total,
        "fmv_total_cents": fmv_total,
        "receipt_method": donor["receipt_method"],
        "effective_total_cents": effective,
    })
