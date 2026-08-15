"""Donor endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db, new_record, touch
from errors import ApiError, ERR_INVALID_REQUEST, not_found
from middleware import require_roles, get_body, ALL_ROLES
from response import success_object

bp = Blueprint("donors", __name__)


def donor_view(d):
    return dict(d)


@bp.route("/api/donors", methods=["POST"])
def create_donor():
    require_roles(["IntakeAttendant"])
    payload = get_body(
        required=[("full_name", "string")],
        optional=[("email", "string"), ("address_line", "string"),
                  ("city", "string"), ("state", "string"), ("postal_code", "string")],
    )
    rec = new_record()
    rec.update({
        "full_name": payload["full_name"],
        "email": payload.get("email"),
        "address_line": payload.get("address_line"),
        "city": payload.get("city"),
        "state": payload.get("state"),
        "postal_code": payload.get("postal_code"),
        "status": "ACTIVE",
        "lifetime_donation_count": 0,
        "tier": "STANDARD",
    })
    db.donors[rec["id"]] = rec
    return success_object(donor_view(rec), status=201)


@bp.route("/api/donors/<donor_id>", methods=["GET"])
def get_donor(donor_id):
    require_roles(ALL_ROLES)
    d = db.donors.get(donor_id)
    if d is None:
        raise not_found("donor")
    return success_object(donor_view(d))


@bp.route("/api/donors/<donor_id>", methods=["PATCH"])
def patch_donor(donor_id):
    require_roles(["IntakeAttendant"])
    payload = get_body(
        optional=[("status", "string"), ("address_line", "string"),
                  ("city", "string"), ("state", "string"),
                  ("postal_code", "string"), ("email", "string")],
        enums={"status": ["ACTIVE", "INACTIVE"]},
    )
    d = db.donors.get(donor_id)
    if d is None:
        raise not_found("donor")
    for f in ("status", "address_line", "city", "state", "postal_code", "email"):
        if f in payload:
            d[f] = payload[f]
    touch(d)
    return success_object(donor_view(d))
