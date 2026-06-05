"""Tax-roll endpoints and lifecycle (PRD §3.1)."""
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import err
from middleware import require_roles
from response import object_response, array_response
from services.common import (
    get_body, require_fields, lookup, parse_pagination, paginate, is_number,
    is_int,
)
from services.serialize import serialize, serialize_list

bp = Blueprint("tax_rolls", __name__)


@bp.post("/tax-rolls")
def create_tax_roll():
    require_roles(["Assessor"])
    body = get_body()
    require_fields(body, ["tax_year", "mill_rate", "growth_cap_pct"])

    tax_year = body["tax_year"]
    if not is_int(tax_year) or tax_year < 2000 or tax_year > 2100:
        raise err("ERR_INVALID_REQUEST", "tax_year must be an integer 2000..2100")
    # unique across TaxRoll
    for r in db.tax_rolls.values():
        if r["tax_year"] == tax_year:
            raise err("ERR_INVALID_REQUEST", "tax_year must be unique across tax rolls")

    mill_rate = body["mill_rate"]
    if not is_number(mill_rate) or mill_rate < 0:
        raise err("ERR_INVALID_REQUEST", "mill_rate must be >= 0")
    # at most four decimal places
    if Decimal(str(mill_rate)).as_tuple().exponent < -4:
        raise err("ERR_INVALID_REQUEST", "mill_rate may have at most 4 decimal places")

    growth_cap_pct = body["growth_cap_pct"]
    if not is_number(growth_cap_pct) or growth_cap_pct < 0 or growth_cap_pct > 1:
        raise err("ERR_INVALID_REQUEST", "growth_cap_pct must be between 0 and 1")

    prior_roll_id = body.get("prior_roll_id")
    if prior_roll_id is not None:
        if not isinstance(prior_roll_id, str):
            raise err("ERR_INVALID_REQUEST", "prior_roll_id must be a string")
        lookup(db.tax_rolls, prior_roll_id)  # existence check (ERR_NOT_FOUND)

    senior_age_threshold = body.get("senior_age_threshold", 65)
    if not is_int(senior_age_threshold) or senior_age_threshold < 0:
        raise err("ERR_INVALID_REQUEST", "senior_age_threshold must be a non-negative integer")

    record = {
        "tax_year": tax_year,
        "mill_rate": mill_rate,
        "growth_cap_pct": growth_cap_pct,
        "prior_roll_id": prior_roll_id,
        "senior_age_threshold": senior_age_threshold,
        "status": "DRAFT",
    }
    db.init_common(record)
    with db.LOCK:
        db.tax_rolls[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/tax-rolls")
def list_tax_rolls():
    require_roles(["Assessor", "Reviewer", "HearingOfficer"])
    limit, offset = parse_pagination()
    prior_roll_id = request.args.get("prior_roll_id")
    items = list(db.tax_rolls.values())
    if prior_roll_id is not None:
        items = [r for r in items if r["prior_roll_id"] == prior_roll_id]
    window, total = paginate(items, limit, offset)
    return array_response(serialize_list(window), limit, offset, total, 200)


@bp.get("/tax-rolls/<roll_id>")
def get_tax_roll(roll_id):
    require_roles(["Assessor", "Reviewer", "HearingOfficer"])
    return object_response(serialize(lookup(db.tax_rolls, roll_id)), 200)


@bp.post("/tax-rolls/<roll_id>/open")
def open_tax_roll(roll_id):
    require_roles(["Assessor"])
    with db.LOCK:
        roll = lookup(db.tax_rolls, roll_id)
        if roll["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Roll is not DRAFT")
        if roll["prior_roll_id"] is not None:
            prior = db.tax_rolls.get(roll["prior_roll_id"])
            if prior is None or prior["status"] != "CERTIFIED":
                raise err("ERR_PRIOR_ROLL_NOT_CERTIFIED", "Prior roll is not CERTIFIED")
        roll["status"] = "OPEN"
        db.touch(roll)
    return object_response(serialize(roll), 200)


@bp.post("/tax-rolls/<roll_id>/certify")
def certify_tax_roll(roll_id):
    require_roles(["Assessor"])
    with db.LOCK:
        roll = lookup(db.tax_rolls, roll_id)
        if roll["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Roll is not OPEN")
        roll_assessments = [a for a in db.assessments.values()
                            if a["tax_roll_id"] == roll_id]
        if any(a["status"] != "FINAL" for a in roll_assessments):
            raise err("ERR_ASSESSMENTS_NOT_FINAL", "Not every assessment is FINAL")
        # Side effect: copy each assessment.capped_base_value into its parcel's
        # last_certified_capped_base; bumps that parcel's updated_at + version.
        for a in roll_assessments:
            parcel = db.parcels.get(a["parcel_id"])
            if parcel is not None:
                parcel["last_certified_capped_base"] = a["capped_base_value"]
                db.touch(parcel)
        roll["status"] = "CERTIFIED"
        db.touch(roll)
    return object_response(serialize(roll), 200)


@bp.post("/tax-rolls/<roll_id>/close")
def close_tax_roll(roll_id):
    require_roles(["Assessor"])
    with db.LOCK:
        roll = lookup(db.tax_rolls, roll_id)
        if roll["status"] != "CERTIFIED":
            raise err("ERR_INVALID_STATE", "Roll is not CERTIFIED")
        successor = any(
            r["prior_roll_id"] == roll_id and r["status"] == "CERTIFIED"
            for r in db.tax_rolls.values()
        )
        if not successor:
            raise err("ERR_NO_CERTIFIED_SUCCESSOR", "No certified successor roll exists")
        roll["status"] = "CLOSED"
        db.touch(roll)
    return object_response(serialize(roll), 200)
