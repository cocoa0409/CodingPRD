"""Attendee endpoints (PRD §3.6). Attendee carries only id + created_at."""
from flask import Blueprint, g, request

import db
import errors
import helpers
import middleware
import models
from errors import err
from response import object_response, array_response

bp = Blueprint("attendees", __name__)


@bp.post("/studio-ops/attendees")
def create_attendee():
    middleware.authenticate()
    middleware.require_roles("Customer", "FrontDesk", "StudioManager", "PlatformAdmin")
    body = helpers.get_json_body()
    reservation_id = helpers.as_str(body, "reservation_id")
    full_name = helpers.as_str(body, "full_name")
    age_years = helpers.as_int(body, "age_years", min_value=0)
    waiver_signed = helpers.as_bool(body, "waiver_signed", required=False, default=False)

    # Priority 5: reservation_id must exist.
    reservation = db.reservations.get(reservation_id)
    if not reservation:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "reservation_id does not exist")
    # Ownership: a Customer may only roster their own reservation.
    if middleware.is_customer() and g.user_id != reservation["customer_id"]:
        raise err(errors.ERR_FORBIDDEN, "Customer does not own this reservation")

    rec = models.make_attendee(reservation_id, full_name, age_years, waiver_signed)
    db.attendees[rec["id"]] = rec
    return object_response(models.serialize_attendee(rec), 201)


@bp.get("/studio-ops/attendees/<aid>")
def get_attendee(aid):
    middleware.authenticate()
    middleware.require_roles("Customer", "FrontDesk", "StudioManager", "PlatformAdmin")
    rec = db.attendees.get(aid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Attendee not found")
    if middleware.is_customer():
        reservation = db.reservations.get(rec["reservation_id"])
        if not reservation or g.user_id != reservation["customer_id"]:
            raise err(errors.ERR_FORBIDDEN, "Customer does not own this attendee")
    return object_response(models.serialize_attendee(rec), 200)


@bp.get("/studio-ops/attendees")
def list_attendees():
    middleware.authenticate()
    middleware.require_roles("Customer", "FrontDesk", "StudioManager", "PlatformAdmin")
    limit, offset = helpers.parse_pagination()
    reservation_id = request.args.get("reservation_id")
    rows = list(db.attendees.values())
    if reservation_id:
        rows = [r for r in rows if r["reservation_id"] == reservation_id]
    if middleware.is_customer():
        owned = {res["id"] for res in db.reservations.values()
                 if res["customer_id"] == g.user_id}
        rows = [r for r in rows if r["reservation_id"] in owned]
    page, total = helpers.sort_and_page(rows, limit, offset)
    return array_response([models.serialize_attendee(r) for r in page],
                          limit, offset, total, 200)
