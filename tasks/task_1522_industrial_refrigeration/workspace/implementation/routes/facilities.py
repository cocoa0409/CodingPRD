"""Facility master data and the charge-summary computed read (PRD 3.1, 3.2)."""
from decimal import Decimal

from flask import Blueprint

import calc
import envelope
from guards import (
    ALL_ROLES,
    endpoint,
    opt_number,
    path_row,
    req_string,
)
from serialize import facility_out
from store import db

bp = Blueprint("facilities", __name__)

CREATE_SCHEMA = (frozenset(["name", "threshold_lbs"]), frozenset(["name"]))


@bp.post("/psm/facilities")
@endpoint(["FacilityAdmin"], schema=CREATE_SCHEMA)
def create_facility(ctx):
    name = req_string(ctx.body, "name")
    threshold = opt_number(ctx.body, "threshold_lbs", Decimal("10000.0"))
    row = db.create(
        "facilities",
        {
            "name": name,
            "threshold_lbs": threshold,
            "psm_program_status": "NOT_REQUIRED",
        },
    )
    return envelope.created(facility_out(row))


@bp.get("/psm/facilities/<facility_id>")
@endpoint(ALL_ROLES)
def get_facility(ctx, facility_id):
    return envelope.ok(facility_out(path_row("facilities", facility_id)))


@bp.get("/psm/facilities/<facility_id>/charge-summary")
@endpoint(ALL_ROLES)
def charge_summary(ctx, facility_id):
    facility = path_row("facilities", facility_id)
    book = calc.book_total(facility["id"])
    gauge = calc.gauge_total(facility["id"])
    return envelope.ok(
        {
            "facility_id": facility["id"],
            "threshold_lbs": facility["threshold_lbs"],
            "book_charge_lbs": book,
            "gauge_charge_lbs": gauge,
            "delta_lbs": book - gauge,
            "charge_posture": calc.charge_posture(book, facility["threshold_lbs"]),
        }
    )
