"""Guest profiles and the derived loyalty position."""

from flask import Blueprint

import calcs
import cascade
import shape
import store
from auth import actor
from envelope import created, list_response, object_response
from errors import ApiError

bp = Blueprint("guests", __name__)

READ_ROLES = ("RevenueManager", "ReservationAgent", "GroupSalesAgent", "Guest")


@bp.post("/guests")
def create_guest():
    actor("ReservationAgent")
    data = shape.body()

    full_name = shape.req_str(data, "full_name", max_len=96)
    email = shape.req_str(data, "email")
    prior_sailings_count = shape.opt_int(data, "prior_sailings_count", 0, minimum=0)

    # Tier 4 uniqueness: email is the guest's login identity.
    for other in store.guests.values():
        if other["email"] == email:
            raise ApiError("ERR_DUPLICATE_GUEST_EMAIL")

    tier, pct = calcs.loyalty(prior_sailings_count)
    row = store.stamp_new({})
    row.update({
        "full_name": full_name,
        "email": email,
        "prior_sailings_count": prior_sailings_count,
        "loyalty_tier": tier,
        "repeat_guest_offer_pct": pct,
        "bookings_count": 0,
    })
    store.guests[row["id"]] = row
    return created(row)


@bp.get("/guests/<guest_id>")
def read_guest(guest_id):
    actor(*READ_ROLES)
    return object_response(cascade.guest_or_404(guest_id))


@bp.get("/guests")
def list_guests():
    actor("RevenueManager", "ReservationAgent")
    limit, offset = shape.pagination()
    email = shape.filter_str("email")
    loyalty_tier = shape.filter_str("loyalty_tier")

    rows = []
    for row in store.guests.values():
        if email is not None and row["email"] != email:
            continue
        if loyalty_tier is not None and row["loyalty_tier"] != loyalty_tier:
            continue
        rows.append(row)
    rows.sort(key=lambda r: r["created_at"])
    return list_response(rows, limit, offset)
