"""HarvestTicket endpoints: request, get, list, approve/complete/cancel.

Windows are half-open [window_start, window_end); the overlap check runs at
creation and is re-checked at approval. The clock expiry sweep (routes/misc.py)
moves REQUESTED tickets whose window_start has passed to EXPIRED.
"""
from flask import Blueprint

from db import store, new_common, touch
from errors import ApiError
from middleware import authenticate, require_roles, forbidden, ANY_ROLE
from response import ok, created, paginate
from services import scheduling
from validation import get_body, req_string, req_datetime, req_enum

bp = Blueprint("tickets", __name__)

METHODS = {"WET", "DRY"}
TICKET_STATUSES = {"REQUESTED", "APPROVED", "COMPLETED", "CANCELLED", "EXPIRED"}

# (from, to, grower_owner_allowed, field_officer_allowed)
TICKET_TRANSITIONS = [
    ("REQUESTED", "APPROVED", False, True),
    ("APPROVED", "COMPLETED", False, True),
    ("REQUESTED", "CANCELLED", True, True),
    ("APPROVED", "CANCELLED", True, True),
]


def get_ticket_or_404(ticket_id):
    ticket = store.tickets.get(ticket_id)
    if ticket is None:
        raise ApiError("ERR_NOT_FOUND", 404, "HarvestTicket not found")
    return ticket


@bp.post("/coop/harvest-tickets")
def create_ticket():
    body = get_body()
    bog_id = req_string(body, "bog_id")
    season_id = req_string(body, "season_id")
    method = req_enum(body, "method", METHODS)
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")

    uid, role = authenticate()
    require_roles(role, {"GrowerMember"})

    bog = store.bogs.get(bog_id)
    if bog is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Bog not found")
    if bog["member_id"] != uid:
        forbidden("GrowerMember may only request tickets for their own bogs")
    season = store.seasons.get(season_id)
    if season is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Season not found")

    # Band 7: window sanity and season alignment.
    scheduling.check_window_sanity(window_start, window_end)
    scheduling.check_window_within_season(season, window_start, window_end)
    # Band 8: occupation conflicts.
    scheduling.check_harvest_overlap(bog_id, window_start, window_end)
    # Band 9: referenced-entity state compatibility (season first, then bog).
    if season["status"] not in ("SETUP", "OPEN"):
        raise ApiError("ERR_SEASON_NOT_OPEN", 409,
                       "Season must be SETUP or OPEN for ticket creation")
    if bog["status"] != "ACTIVE":
        raise ApiError("ERR_BOG_NOT_ACTIVE", 409, "Bog is not ACTIVE")

    ticket = new_common({
        "bog_id": bog_id,
        "season_id": season_id,
        "member_id": bog["member_id"],
        "method": method,
        "window_start": window_start,
        "window_end": window_end,
        "status": "REQUESTED",
    })
    store.tickets[ticket["id"]] = ticket
    return created(ticket)


@bp.get("/coop/harvest-tickets/<ticket_id>")
def get_ticket(ticket_id):
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    return ok(get_ticket_or_404(ticket_id))


@bp.get("/coop/harvest-tickets")
def list_tickets():
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    rows = list(store.tickets.values())
    rows = paginate.filter(rows, "bog_id")
    rows = paginate.filter(rows, "season_id")
    rows = paginate.filter(rows, "member_id")
    rows = paginate.filter(rows, "status")
    rows = paginate.filter(rows, "method")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.post("/coop/harvest-tickets/<ticket_id>/transition")
def transition_ticket(ticket_id):
    body = get_body()
    to = req_enum(body, "to", TICKET_STATUSES)

    uid, role = authenticate()
    require_roles(role, {"GrowerMember", "FieldOfficer"})

    # Band-3 transition-target role split (before existence).
    target_rows = [t for t in TICKET_TRANSITIONS if t[1] == to]
    if target_rows:
        if role == "GrowerMember" and not any(t[2] for t in target_rows):
            forbidden("Transition to %s is FieldOfficer-only" % to)
        if role == "FieldOfficer" and not any(t[3] for t in target_rows):
            forbidden("Transition to %s is not permitted for FieldOfficer" % to)

    ticket = get_ticket_or_404(ticket_id)

    if role == "GrowerMember" and ticket["member_id"] != uid:
        forbidden("GrowerMember may only act on their own tickets")

    row = next((t for t in TICKET_TRANSITIONS
                if t[0] == ticket["status"] and t[1] == to), None)
    if row is None:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Ticket transition %s -> %s is not defined" % (ticket["status"], to))
    if role == "GrowerMember" and not row[2]:
        forbidden("Transition to %s is FieldOfficer-only" % to)
    if role == "FieldOfficer" and not row[3]:
        forbidden("Transition to %s is not permitted for FieldOfficer" % to)

    if to == "APPROVED":
        # Approval re-checks the overlap (band 8), then bog state (band 9).
        scheduling.check_harvest_overlap(ticket["bog_id"], ticket["window_start"],
                                         ticket["window_end"], exclude_id=ticket["id"])
        bog = store.bogs.get(ticket["bog_id"])
        if bog is None or bog["status"] != "ACTIVE":
            raise ApiError("ERR_BOG_NOT_ACTIVE", 409, "Bog is not ACTIVE")

    ticket["status"] = to
    touch(ticket)
    return ok(ticket)
