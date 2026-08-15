"""Rain-checks: read-only resources issued by excursion cancellations and
consumed (or expired) via booking confirms and the clock sweep."""
from flask import Blueprint, request

import db
from auth import ALL_ROLES, require_roles
from db import public
from envelope import success_list, success_obj
from errors import ApiError, ERR_NOT_FOUND
from validators import paginate, pagination

bp = Blueprint("rain_checks", __name__)


@bp.get("/railroad/rain-checks/<rid>")
def get_rain_check(rid):
    require_roles(*ALL_ROLES)
    rc = db.rain_checks.get(rid)
    if rc is None:
        raise ApiError(ERR_NOT_FOUND, "Rain-check not found", 404)
    return success_obj(public(rc), 200)


@bp.get("/railroad/rain-checks")
def list_rain_checks():
    require_roles(*ALL_ROLES)
    items = list(db.rain_checks.values())
    booking_id = request.args.get("booking_id")
    redeemed_booking_id = request.args.get("redeemed_booking_id")
    customer_email = request.args.get("customer_email")
    status = request.args.get("status")
    if booking_id is not None:
        items = [r for r in items if r["booking_id"] == booking_id]
    if redeemed_booking_id is not None:
        items = [r for r in items if r["redeemed_booking_id"] == redeemed_booking_id]
    if customer_email is not None:
        items = [r for r in items if r["customer_email"] == customer_email]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)
