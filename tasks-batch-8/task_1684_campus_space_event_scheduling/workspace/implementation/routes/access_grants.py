"""Access grants (PRD 3.7): key/card provisioning, deposits, forfeiture, and
physical key inventory."""

from datetime import timedelta

import db
import serializers
from clock import clock, render_server
from constants import (
    DEPOSIT_BY_GRANT_TYPE,
    GRANT_OUTSTANDING_STATUSES,
    GRANT_TYPES,
    RETURN_DEADLINE_HOURS,
)
from errors import ApiError
from middleware import endpoint
from routes.common import list_response, one
from services import invoices as invoice_service
from services.derive import room_keys_issued, room_keys_lost_total
from services.pricing import late_return_forfeit_cents
from validate import get_event_masked, get_grant_masked, req_enum, req_str

READ_ROLES = ["FacilitiesManager", "Scheduler", "OrgRequester"]


@endpoint("POST", "/campus/access-grants", roles=["OrgRequester", "FacilitiesManager"], code=201)
def create_grant(ctx):
    body = ctx.body
    event_id = req_str(body, "event_id")
    event = get_event_masked(ctx, event_id)  # body FK + ownership masking (rung 3)
    grant_type = req_enum(body, "grant_type", GRANT_TYPES)
    return_deadline = event["_end"] + timedelta(hours=RETURN_DEADLINE_HOURS)
    row = db.new_row(
        db.access_grants,
        event_id=event["id"],
        room_id=event.get("room_id"),  # copied from the event at creation
        grant_type=grant_type,
        status="REQUESTED",
        key_slot=None,
        deposit_cents=0,
        deposit_forfeit_cents=0,
        return_deadline=render_server(return_deadline),
        returned_at=None,
        _return_deadline=return_deadline,
    )
    return one(serializers.access_grant(row), status=201)


@endpoint("GET", "/campus/access-grants/{id}", roles=READ_ROLES, code=200)
def get_grant_detail(ctx):
    return one(serializers.access_grant(get_grant_masked(ctx, ctx.id)))


@endpoint("GET", "/campus/access-grants", roles=READ_ROLES, code=200)
def list_grants(ctx):
    rows = db.all_of(db.access_grants)
    if ctx.is_org_requester:
        rows = [
            r
            for r in rows
            if (db.event_reservations.get(r.get("event_id")) or {}).get("requester_org_id") == ctx.user_id
        ]
    return list_response(
        rows,
        ctx.args,
        serializers.access_grant,
        mapping={
            "event_id": lambda r: r.get("event_id"),
            "room_id": lambda r: r.get("room_id"),
            "status": lambda r: r.get("status"),
        },
    )


def _lowest_free_slot(room):
    """Lowest free slot in the room's live key namespace.  The namespace spans
    1..(key_count + keys_lost_total); slots retired by LOST grants are never
    reused."""
    taken = set()
    retired = set()
    for grant in db.access_grants.values():
        if grant.get("room_id") != room["id"] or grant.get("grant_type") != "PHYSICAL_KEY":
            continue
        if grant.get("status") in GRANT_OUTSTANDING_STATUSES and grant.get("key_slot") is not None:
            taken.add(grant["key_slot"])
        if grant.get("status") == "LOST" and grant.get("key_slot") is not None:
            retired.add(grant["key_slot"])
    upper = room.get("key_count", 0) + room_keys_lost_total(room)
    for slot in range(1, upper + 1):
        if slot not in taken and slot not in retired:
            return slot
    return None


@endpoint("POST", "/campus/access-grants/{id}/issue", roles=["FacilitiesManager"], code=200)
def issue_grant(ctx):
    grant = get_grant_masked(ctx, ctx.id)
    if grant["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED grant can be issued.")
    event = db.event_reservations.get(grant["event_id"])
    if event is None or event["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Access may be issued only for a CONFIRMED event.")
    grant["deposit_cents"] = DEPOSIT_BY_GRANT_TYPE[grant["grant_type"]]
    if grant["grant_type"] == "PHYSICAL_KEY":
        room = db.rooms.get(grant.get("room_id"))
        if room is None or room_keys_issued(room) >= room.get("key_count", 0):
            raise ApiError("ERR_NO_KEYS_AVAILABLE", "No physical key slots remain for the room.")
        grant["key_slot"] = _lowest_free_slot(room)
    grant["status"] = "ISSUED"
    db.touch(grant)
    return one(serializers.access_grant(grant))


@endpoint("POST", "/campus/access-grants/{id}/return", roles=["FacilitiesManager"], code=200)
def return_grant(ctx):
    grant = get_grant_masked(ctx, ctx.id)
    if grant["status"] not in GRANT_OUTSTANDING_STATUSES:
        raise ApiError("ERR_INVALID_STATE", "Only an issued or overdue grant can be returned.")
    now = clock.now
    # On-time (now <= return_deadline) forfeits nothing; a late return forfeits
    # half the deposit, rounded half-up.
    forfeit = 0 if now <= grant["_return_deadline"] else late_return_forfeit_cents(grant["deposit_cents"])
    grant["deposit_forfeit_cents"] = forfeit
    grant["returned_at"] = render_server(now)
    grant["status"] = "RETURNED"
    if grant["grant_type"] == "PHYSICAL_KEY":
        grant["key_slot"] = None  # the slot is freed
    db.touch(grant)
    event = db.event_reservations.get(grant["event_id"])
    if event is not None:
        # The forfeit lands in the event invoice's deposit_charge_cents with
        # totals recomputed - even on an already-FINALIZED invoice.
        invoice_service.add_deposit_forfeit(event, forfeit)
    return one(serializers.access_grant(grant))


@endpoint("POST", "/campus/access-grants/{id}/mark-lost", roles=["FacilitiesManager"], code=200)
def mark_lost_grant(ctx):
    grant = get_grant_masked(ctx, ctx.id)
    if grant["status"] not in GRANT_OUTSTANDING_STATUSES:
        raise ApiError("ERR_INVALID_STATE", "Only an issued or overdue grant can be marked lost.")
    # A lost grant forfeits the entire deposit.
    grant["deposit_forfeit_cents"] = grant["deposit_cents"]
    grant["status"] = "LOST"
    db.touch(grant)
    if grant["grant_type"] == "PHYSICAL_KEY":
        room = db.rooms.get(grant.get("room_id"))
        if room is not None:
            # The retired key_slot (kept on the grant) is never reused;
            # key_count + keys_lost_total stays invariant.
            room["key_count"] = room.get("key_count", 0) - 1
            db.touch(room)
    event = db.event_reservations.get(grant["event_id"])
    if event is not None:
        invoice_service.add_deposit_forfeit(event, grant["deposit_forfeit_cents"])
    return one(serializers.access_grant(grant))
