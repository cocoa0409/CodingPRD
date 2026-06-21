"""Guest profiles and day tickets (PRD §3.2)."""
from flask import Blueprint, request

import db
import errors
import lookups
import response
import serialize
import validate_input as vi
from middleware import get_principal, require_roles

bp = Blueprint("guests", __name__)


# ---------------------------------------------------------------------------
# Guest create / read / list
# ---------------------------------------------------------------------------
@bp.post("/parks/<pid>/guests")
def create_guest(pid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "GuestApp"})
    park = lookups.get_park(pid)
    body = vi.get_body()

    full_name = vi.require_str(body, "full_name")
    height_cm = vi.require_int(body, "height_cm", min_val=30)
    uses_wheelchair = vi.opt_bool(body, "uses_wheelchair", default=False)

    guest = db.stamp_new({
        "park_id": park["id"],
        "full_name": full_name,
        "height_cm": height_cm,
        "uses_wheelchair": uses_wheelchair,
        "party_id": None,
    })
    db.guests[guest["id"]] = guest
    return response.object_response(serialize.view("guest", guest), 201)


@bp.get("/parks/<pid>/guests")
def list_park_guests(pid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "GuestApp"})
    park = lookups.get_park(pid)
    records = [g for g in db.guests.values() if g["park_id"] == park["id"]]
    return lookups.paginate_and_respond("guest", records, response)


@bp.get("/guests/<gid>")
def read_guest(gid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "RideOperator", "GuestApp"})
    guest = lookups.get_guest(gid)
    return response.object_response(serialize.view("guest", guest), 200)


@bp.get("/guests")
def list_guests():
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "GuestApp"})
    park_id = request.args.get("park_id")
    party_id = request.args.get("party_id")
    records = list(db.guests.values())
    if park_id is not None:
        records = [g for g in records if g["park_id"] == park_id]
    if party_id is not None:
        records = [g for g in records if g["party_id"] == party_id]
    return lookups.paginate_and_respond("guest", records, response)


# ---------------------------------------------------------------------------
# GuestDayTicket issue / read / list
# ---------------------------------------------------------------------------
@bp.post("/parks/<pid>/day-tickets")
def create_day_ticket(pid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin"})
    park = lookups.get_park(pid)
    body = vi.get_body()
    guest_id = vi.require_str(body, "guest_id")
    ticket_date = vi.require_str(body, "ticket_date")
    guest = lookups.get_guest(guest_id)

    if guest["park_id"] != park["id"]:
        errors.err(errors.ERR_GUEST_PARK_MISMATCH, "Guest belongs to a different park")

    ticket = db.stamp_new({
        "park_id": park["id"],
        "guest_id": guest["id"],
        "ticket_date": ticket_date,
        "admission_status": "ISSUED",
    })
    db.guest_day_tickets[ticket["id"]] = ticket
    return response.object_response(serialize.view("guest_day_ticket", ticket), 201)


@bp.get("/parks/<pid>/day-tickets")
def list_park_day_tickets(pid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin"})
    park = lookups.get_park(pid)
    guest_id = request.args.get("guest_id")
    records = [t for t in db.guest_day_tickets.values() if t["park_id"] == park["id"]]
    if guest_id is not None:
        records = [t for t in records if t["guest_id"] == guest_id]
    return lookups.paginate_and_respond("guest_day_ticket", records, response)


@bp.get("/day-tickets/<tid>")
def read_day_ticket(tid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin"})
    ticket = lookups.get_ticket(tid)
    return response.object_response(serialize.view("guest_day_ticket", ticket), 200)


@bp.get("/day-tickets")
def list_day_tickets():
    _, role = get_principal()
    require_roles(role, {"ParkAdmin"})
    park_id = request.args.get("park_id")
    guest_id = request.args.get("guest_id")
    records = list(db.guest_day_tickets.values())
    if park_id is not None:
        records = [t for t in records if t["park_id"] == park_id]
    if guest_id is not None:
        records = [t for t in records if t["guest_id"] == guest_id]
    return lookups.paginate_and_respond("guest_day_ticket", records, response)
