"""Travel leg and waiver endpoints."""
from flask import Blueprint

import db
import errors
from auth import require_account_owner, require_roles
from clock import clock
from respond import success
from services.domain import get_or_404
from validate import paginate

bp = Blueprint("misc", __name__)


@bp.get("/chair-massage/travel-legs/<lid>")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def get_travel_leg(lid):
    leg = get_or_404("travel_legs", lid, "TravelLeg")
    booking = db.get("bookings", leg["booking_id"])
    if booking:
        require_account_owner(booking["corporate_account_id"])
    return success(db.public(leg))


@bp.get("/chair-massage/waivers/<wid>")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def get_waiver(wid):
    waiver = get_or_404("waivers", wid, "Waiver")
    booking = db.get("bookings", waiver["booking_id"])
    if booking:
        require_account_owner(booking["corporate_account_id"])
    return success(db.public(waiver))


@bp.get("/chair-massage/waivers/<wid>/slot-claims")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def list_waiver_claims(wid):
    waiver = get_or_404("waivers", wid, "Waiver")
    booking = db.get("bookings", waiver["booking_id"])
    if booking:
        require_account_owner(booking["corporate_account_id"])
    items = [c for c in db.all_sorted("slot_claims") if c["waiver_id"] == wid]
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.post("/chair-massage/waivers/<wid>/revoke")
@require_roles("PlatformAdmin")
def revoke_waiver(wid):
    waiver = get_or_404("waivers", wid, "Waiver")
    if waiver["revoked_at"] is None:
        waiver["revoked_at"] = clock.iso()
        db.touch(waiver)
    return success(db.public(waiver))
