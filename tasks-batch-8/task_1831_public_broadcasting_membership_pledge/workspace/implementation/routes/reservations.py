"""Premium reservations: top-level reads and manual release."""

from flask import Blueprint, request

import db
import response
import validators as v
from errors import ApiError, ERR_INVALID_STATE
from middleware import require_roles
from services import core

bp = Blueprint("reservations", __name__)


@bp.route("/station/premium-reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    require_roles("StationAdmin", "MembershipCoordinator")
    ent = db.reservations.get(rid)
    if ent is None:
        v.not_found(f"PremiumReservation '{rid}' not found")
    return response.success_object(ent)


@bp.route("/station/premium-reservations", methods=["GET"])
def list_reservations():
    require_roles("StationAdmin", "MembershipCoordinator")
    limit, offset = v.parse_pagination(request.args)
    items = list(db.reservations.values())
    for field in ("pledge_id", "premium_id", "lot_id", "status"):
        q = request.args.get(field)
        if q is not None:
            items = [r for r in items if r.get(field) == q]
    items = v.sort_created(items)
    page, total = v.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.route("/station/premium-reservations/<rid>/release", methods=["POST"])
def release_reservation(rid):
    v.get_json_body(required=False)
    require_roles("MembershipCoordinator")
    reservation = db.reservations.get(rid)
    if reservation is None:
        v.not_found(f"PremiumReservation '{rid}' not found")
    if reservation["status"] != "HELD":
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Reservation status is {reservation['status']}, must be HELD",
                       ERR_INVALID_STATE[1])

    lot = db.lots.get(reservation["lot_id"])
    reservation["status"] = "RELEASED"
    db.touch(reservation)
    if lot is not None:
        lot["reserved_qty"] -= reservation["quantity"]
        lot["available_qty"] += reservation["quantity"]
        db.touch(lot)

    # Parent pledge drops back to AWAITING_RESERVATION
    pledge = db.pledges.get(reservation["pledge_id"])
    if pledge is not None and pledge["fulfillment_status"] == "RESERVED":
        pledge["fulfillment_status"] = "AWAITING_RESERVATION"
        db.touch(pledge)
        core.resync_pledge_net(pledge)

    return response.success_object(reservation)
