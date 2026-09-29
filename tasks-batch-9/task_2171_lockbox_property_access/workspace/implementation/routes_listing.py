"""Listing creation, reads and the listing state machine (PRD §3.4)."""
from datetime import timedelta

from flask import Blueprint

import calc
import serialize
from cascades import listing_close_cascade
from core import (
    ADMIN, MEMBER, READ_ROLES, authenticate, body, db, fail, is_int, lookup,
    new_common, now, ok, ordered, paginate, parse_date, present, qfilter,
    start_of_day, touch,
)
from ladder import (
    assert_not_terminal, assert_owner, assert_transition, assert_version,
    require_action, require_str, require_version_field,
)

bp = Blueprint("listing", __name__)

LISTING_TRANSITIONS = {
    "MARK_UNDER_CONTRACT": ("ACTIVE",),
    "REACTIVATE": ("UNDER_CONTRACT",),
    "CLOSE": ("UNDER_CONTRACT",),
    "WITHDRAW": ("ACTIVE", "UNDER_CONTRACT"),
}


@bp.post("/listings")
def create_listing():
    user_id, role = authenticate([ADMIN, MEMBER])
    payload = body()

    # Rung 4 — body foreign keys, in declared input order.
    association = None
    agent = None
    if present(payload, "association_id"):
        association = lookup("associations", payload["association_id"])
    if present(payload, "listing_agent_id"):
        agent = lookup("members", payload["listing_agent_id"])

    # Rung 5 — request shape.
    if association is None:
        fail("ERR_INVALID_REQUEST", "association_id is required.")
    if agent is None:
        fail("ERR_INVALID_REQUEST", "listing_agent_id is required.")
    require_str(payload, "address_line")
    require_str(payload, "mls_number")
    limit = 1
    if present(payload, "concurrent_showing_limit"):
        limit = payload["concurrent_showing_limit"]
        if not is_int(limit) or limit < 1:
            fail("ERR_INVALID_REQUEST", "concurrent_showing_limit must be an integer >= 1.")

    # Rung 6 — Member ownership.
    assert_owner(role, user_id, agent["id"])

    # Rung 15 — uniqueness within the association.
    for existing in db.listings.values():
        if (existing["association_id"] == association["id"]
                and existing["mls_number"] == payload["mls_number"]):
            fail("ERR_DUPLICATE_MLS_NUMBER", "mls_number already exists in this association.")

    rec = new_common()
    rec.update({
        "association_id": association["id"],
        "listing_agent_id": agent["id"],
        "address_line": payload["address_line"],
        "mls_number": payload["mls_number"],
        "concurrent_showing_limit": limit,
        "status": "ACTIVE",
        "close_date": None,
    })
    db.listings[rec["id"]] = rec
    return ok(serialize.listing(rec), 201)


@bp.get("/listings/<listing_id>")
def read_listing(listing_id):
    authenticate(READ_ROLES)
    return ok(serialize.listing(lookup("listings", listing_id)))


@bp.get("/listings")
def list_listings():
    authenticate(READ_ROLES)
    rows = ordered(db.listings)
    rows = qfilter(rows, "association_id")
    rows = qfilter(rows, "listing_agent_id")
    rows = qfilter(rows, "status")
    return paginate(rows, serialize.listing)


@bp.post("/listings/<listing_id>/state")
def listing_state(listing_id):
    user_id, role = authenticate([ADMIN, MEMBER])
    listing = lookup("listings", listing_id)
    payload = body()

    action = require_action(payload, tuple(LISTING_TRANSITIONS))
    expected = require_version_field(payload, "expected_listing_version")
    close_date = None
    if action == "CLOSE":
        require_str(payload, "close_date")
        close_date = parse_date(payload["close_date"])
        if close_date is None:
            fail("ERR_INVALID_REQUEST", "close_date must be an ISO date (YYYY-MM-DD).")

    assert_owner(role, user_id, listing["listing_agent_id"])
    assert_version(expected, listing)
    assert_not_terminal("listing", listing["status"])
    assert_transition(listing["status"], LISTING_TRANSITIONS, action)

    association = db.associations.get(listing["association_id"])
    grace_days = association["removal_grace_days"] if association else 0

    if action == "MARK_UNDER_CONTRACT":
        listing["status"] = "UNDER_CONTRACT"
    elif action == "REACTIVATE":
        listing["status"] = "ACTIVE"
    elif action == "CLOSE":
        listing["close_date"] = payload["close_date"]
        listing["status"] = "CLOSED"
        deadline = start_of_day(close_date) + timedelta(days=grace_days)
        listing_close_cascade(listing, deadline)
        if association is not None:
            calc.recompute_recovery_rate(association)
    elif action == "WITHDRAW":
        listing["status"] = "WITHDRAWN"
        deadline = start_of_day(now().date()) + timedelta(days=grace_days)
        listing_close_cascade(listing, deadline)
        if association is not None:
            calc.recompute_recovery_rate(association)

    touch(listing)
    return ok(serialize.listing(listing))
