"""Itinerary changes: frozen compensation terms, published as an additive grant."""

from flask import Blueprint

import calcs
import cascade
import shape
import store
from auth import actor
from envelope import created, list_response, object_response
from errors import ApiError

bp = Blueprint("itinerary", __name__)

READ_ROLES = ("RevenueManager", "PortOpsCoordinator", "ReservationAgent", "Guest")
LIST_ROLES = ("RevenueManager", "PortOpsCoordinator", "ReservationAgent")
KINDS = ("PORT_CANCELLED", "PORT_SUBSTITUTED", "ITINERARY_SHORTENED")
POLICIES = ("OBC_ONLY", "OBC_PLUS_REFUND_PCT")
PUBLISHABLE_SAILING_STATUSES = ("OPEN_FOR_SALE", "SALES_SUSPENDED", "INVENTORY_CLOSED")
COMPENSATED = ("OPTION", "CONFIRMED")


@bp.post("/itinerary-changes")
def create_itinerary_change():
    actor("PortOpsCoordinator")
    data = shape.body()

    sailing_id = shape.req_str(data, "sailing_id")
    kind = shape.req_enum(data, "kind", KINDS)
    affected_port_code = shape.req_str(data, "affected_port_code", max_len=8)
    compensation_policy = shape.req_enum(data, "compensation_policy", POLICIES)

    # Tier 6.
    sailing = cascade.sailing_or_404(sailing_id)

    # The terms are frozen at draft time and never re-derived on publication.
    obc, refund_pct = calcs.compensation_terms(kind, compensation_policy)

    row = store.stamp_new({})
    row.update({
        "sailing_id": sailing["id"],
        "kind": kind,
        "affected_port_code": affected_port_code,
        "compensation_policy": compensation_policy,
        "obc_per_guest_cents": obc,
        "refund_pct": refund_pct,
        "status": "DRAFT",
        "published_at": None,
        "affected_bookings_count": 0,
        "total_obc_granted_cents": 0,
        "total_refund_granted_cents": 0,
    })
    store.itinerary_changes[row["id"]] = row
    return created(row)


@bp.get("/itinerary-changes/<change_id>")
def read_itinerary_change(change_id):
    actor(*READ_ROLES)
    return object_response(cascade.change_or_404(change_id))


@bp.get("/itinerary-changes")
def list_itinerary_changes():
    actor(*LIST_ROLES)
    limit, offset = shape.pagination()
    sailing_id = shape.filter_str("sailing_id")
    status = shape.filter_str("status")
    kind = shape.filter_str("kind")

    rows = []
    for row in store.itinerary_changes.values():
        if sailing_id is not None and row["sailing_id"] != sailing_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if kind is not None and row["kind"] != kind:
            continue
        rows.append(row)
    rows.sort(key=lambda r: r["created_at"])
    return list_response(rows, limit, offset)


@bp.post("/itinerary-changes/<change_id>/publish")
def publish_itinerary_change(change_id):
    actor("PortOpsCoordinator")
    shape.body()
    change = cascade.change_or_404(change_id)

    # Tier 10: PUBLISHED is terminal.
    if change["status"] != "DRAFT":
        raise ApiError("ERR_ITINERARY_CHANGE_NOT_DRAFT")

    # Tier 11: a departed (or not-yet-selling) voyage compensates nobody.
    sailing = store.sailings.get(change["sailing_id"])
    if sailing is None or sailing["status"] not in PUBLISHABLE_SAILING_STATUSES:
        raise ApiError("ERR_SAILING_ALREADY_SAILED")

    obc_per_guest = change["obc_per_guest_cents"]
    refund_pct = change["refund_pct"]
    affected = 0
    total_obc = 0
    total_refund = 0

    # Grants are additive: a second publication stacks onto the same booking fields.
    for booking in cascade.bookings_of_sailing(sailing["id"]):
        if booking["booking_status"] not in COMPENSATED:
            continue
        obc_grant = obc_per_guest * booking["guest_count"]
        refund_grant = calcs.refund_grant(booking["net_ticket_cents"], refund_pct)
        booking["itinerary_compensation_obc_cents"] = \
            booking["itinerary_compensation_obc_cents"] + obc_grant
        booking["itinerary_refund_cents"] = \
            booking["itinerary_refund_cents"] + refund_grant
        # Granted credit is spend the guest no longer pays for out of pocket.
        cascade.recompute_onboard(booking, sailing)
        cascade.recompute_booking_money(booking)
        store.touch(booking)
        affected += 1
        total_obc += obc_grant
        total_refund += refund_grant

    change["status"] = "PUBLISHED"
    change["published_at"] = store.now_iso()
    change["affected_bookings_count"] = affected
    change["total_obc_granted_cents"] = total_obc
    change["total_refund_granted_cents"] = total_refund
    store.touch(change)

    cascade.recompute_sailing(sailing, bump=True)
    return object_response(change)
