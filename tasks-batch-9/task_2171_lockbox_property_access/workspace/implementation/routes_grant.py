"""Temporary access grants: request, approval gates and revocation (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint

import calc
import serialize
from cascades import create_charge
from core import (
    ADMIN, MEMBER, READ_ROLES, access_code, authenticate, body, db,
    end_of_day, fail, is_int, is_str, lookup, new_common, ok, ordered,
    paginate, parse_date, parse_dt, present, qfilter, touch,
)
from ladder import (
    assert_not_terminal, assert_owner, assert_transition, assert_version,
    require_action, require_version_field,
)

bp = Blueprint("grant", __name__)

GRANT_TYPES = ("ONE_DAY_MEMBER", "CONTRACTOR_WINDOW", "INSPECTOR")
GRANT_TRANSITIONS = {
    "APPROVE": ("REQUESTED",),
    "DENY": ("REQUESTED",),
    "REVOKE": ("REQUESTED", "APPROVED"),
}
ADMIN_ONLY_ACTIONS = ("APPROVE", "DENY")
MAX_SHORT_WINDOW = timedelta(hours=24)
MAX_CONTRACTOR_WINDOW = timedelta(days=7)


@bp.post("/access-grants")
def request_grant():
    user_id, role = authenticate([ADMIN, MEMBER])
    payload = body()

    # Rung 4 — body foreign keys, in declared input order.
    listing = None
    lockbox = None
    contractor = None
    supersedes = None
    if present(payload, "listing_id"):
        listing = lookup("listings", payload["listing_id"])
    if present(payload, "lockbox_id"):
        lockbox = lookup("lockboxes", payload["lockbox_id"])
    if present(payload, "contractor_id"):
        contractor = lookup("contractors", payload["contractor_id"])
    if present(payload, "supersedes_grant_id"):
        supersedes = lookup("grants", payload["supersedes_grant_id"])

    # Rung 5 — request shape.
    if listing is None:
        fail("ERR_INVALID_REQUEST", "listing_id is required.")
    if lockbox is None:
        fail("ERR_INVALID_REQUEST", "lockbox_id is required.")
    if not present(payload, "grant_type") or payload["grant_type"] not in GRANT_TYPES:
        fail("ERR_INVALID_REQUEST", "grant_type must be one of %s." % ", ".join(GRANT_TYPES))
    grant_type = payload["grant_type"]
    if not present(payload, "window_start") or not present(payload, "window_end"):
        fail("ERR_INVALID_REQUEST", "window_start and window_end are required.")
    window_start = parse_dt(payload["window_start"])
    window_end = parse_dt(payload["window_end"])
    if window_start is None or window_end is None:
        fail("ERR_INVALID_REQUEST", "window_start and window_end must be ISO 8601 instants.")
    if grant_type == "CONTRACTOR_WINDOW":
        if contractor is None:
            fail("ERR_INVALID_REQUEST", "contractor_id is required for a CONTRACTOR_WINDOW grant.")
    elif contractor is not None:
        fail("ERR_INVALID_REQUEST", "contractor_id is only accepted for a CONTRACTOR_WINDOW grant.")
    max_uses = 1
    if present(payload, "max_uses"):
        max_uses = payload["max_uses"]
        if not is_int(max_uses) or max_uses < 1:
            fail("ERR_INVALID_REQUEST", "max_uses must be an integer >= 1.")
    expected = require_version_field(payload, "expected_listing_version")

    # Rung 6 — Member ownership of the listing.
    assert_owner(role, user_id, listing["listing_agent_id"])

    # Rung 8 — optimistic concurrency on the listing.
    assert_version(expected, listing)

    # Rung 12 — physical-safety gate.
    if lockbox["status"] == "MISSING":
        fail("ERR_LOCKBOX_MISSING", "The lockbox is reported missing.")

    # Rung 13 — association posture gate.
    association = db.associations.get(listing["association_id"])
    posture = calc.association_posture(listing["association_id"])
    if posture == "FROZEN":
        fail("ERR_ASSOCIATION_FROZEN", "The association posture is FROZEN.")
    if posture == "RESTRICTED" and grant_type == "CONTRACTOR_WINDOW":
        fail("ERR_ASSOCIATION_RESTRICTED", "The association posture is RESTRICTED.")

    # Rung 14 — window geometry.
    if not (window_start < window_end):
        fail("ERR_INVALID_WINDOW", "window_start must be earlier than window_end.")
    span = window_end - window_start
    if grant_type == "CONTRACTOR_WINDOW":
        if span > MAX_CONTRACTOR_WINDOW:
            fail("ERR_GRANT_WINDOW_TOO_LONG", "A contractor window may span at most seven days.")
    elif span > MAX_SHORT_WINDOW:
        fail("ERR_GRANT_WINDOW_TOO_LONG", "This grant may span at most twenty-four hours.")

    issued_by = user_id if role == MEMBER else listing["listing_agent_id"]

    # Rung 15 — the daily temporary-code quota (Members only).
    overage = False
    if grant_type == "ONE_DAY_MEMBER" and association is not None:
        limit = association["temp_code_daily_limit"]
        issued_today = calc.temp_codes_issued_today(issued_by)
        if issued_today >= limit:
            if role == MEMBER:
                fail("ERR_TEMP_CODE_LIMIT_REACHED", "The daily temporary-code limit is reached.")
            overage = True

    # Rung 16 — linkage integrity.
    on_listing = any(
        p["lockbox_id"] == lockbox["id"]
        and p["listing_id"] == listing["id"]
        and p["placement_status"] == "PLACED"
        for p in db.placements.values()
    )
    if not on_listing:
        fail("ERR_LOCKBOX_NOT_ON_LISTING", "The lockbox is not placed on that listing.")

    rec = new_common()
    rec.update({
        "listing_id": listing["id"],
        "lockbox_id": lockbox["id"],
        "issued_by_member_id": issued_by,
        "contractor_id": contractor["id"] if contractor else None,
        "supersedes_grant_id": supersedes["id"] if supersedes else None,
        "grant_type": grant_type,
        "window_start": payload["window_start"],
        "window_end": payload["window_end"],
        "max_uses": max_uses,
        "access_code": None,
        "status": "REQUESTED",
    })
    db.grants[rec["id"]] = rec
    touch(listing)

    if overage:
        create_charge(
            member_id=issued_by,
            charge_type="TEMP_CODE_OVERAGE",
            amount_cents=association["temp_code_overage_fee_cents"],
            variant_applied="NOT_APPLICABLE",
            basis="overage_fee=%d" % association["temp_code_overage_fee_cents"],
            lockbox_id=None,
        )

    return ok(serialize.grant(rec), 201)


@bp.get("/access-grants/<grant_id>")
def read_grant(grant_id):
    authenticate(READ_ROLES)
    return ok(serialize.grant(lookup("grants", grant_id)))


@bp.get("/access-grants")
def list_grants():
    authenticate(READ_ROLES)
    rows = ordered(db.grants)
    rows = qfilter(rows, "listing_id")
    rows = qfilter(rows, "lockbox_id")
    rows = qfilter(rows, "issued_by_member_id")
    rows = qfilter(rows, "contractor_id")
    rows = qfilter(rows, "supersedes_grant_id")
    rows = qfilter(rows, "grant_type")
    rows = qfilter(rows, "status")
    return paginate(rows, serialize.grant)


@bp.post("/access-grants/<grant_id>/state")
def grant_state(grant_id):
    user_id, role = authenticate([ADMIN, MEMBER])
    payload = body()
    raw_action = payload.get("action")
    if is_str(raw_action) and raw_action in ADMIN_ONLY_ACTIONS and role != ADMIN:
        fail("ERR_FORBIDDEN_ROLE", "Only an AssociationAdmin may perform %s." % raw_action)

    grant = lookup("grants", grant_id)
    action = require_action(payload, tuple(GRANT_TRANSITIONS))
    expected = require_version_field(payload, "expected_grant_version")

    assert_owner(role, user_id, grant.get("issued_by_member_id"))
    assert_version(expected, grant)
    assert_not_terminal("grant", grant["status"])
    assert_transition(grant["status"], GRANT_TRANSITIONS, action)

    listing = db.listings.get(grant["listing_id"])

    if action == "APPROVE":
        # Rung 12 — vendor gate.
        if grant["grant_type"] == "CONTRACTOR_WINDOW":
            contractor = db.contractors.get(grant.get("contractor_id"))
            window_end = parse_dt(grant["window_end"])
            expires_on = parse_date(contractor["insurance_expires_on"]) if contractor else None
            if (contractor is None or contractor["status"] != "ACTIVE"
                    or expires_on is None or end_of_day(expires_on) < window_end):
                fail("ERR_CONTRACTOR_INSURANCE_EXPIRED",
                     "The vendor is suspended or its insurance lapses before the window ends.")
        # Rung 13 — posture gate.
        if listing is not None:
            posture = calc.association_posture(listing["association_id"])
            if posture == "FROZEN":
                fail("ERR_ASSOCIATION_FROZEN", "The association posture is FROZEN.")
            if posture == "RESTRICTED" and grant["grant_type"] == "CONTRACTOR_WINDOW":
                fail("ERR_ASSOCIATION_RESTRICTED", "The association posture is RESTRICTED.")
        # Rung 14 — half-open buffered lockbox occupation.
        buffer_minutes = 15
        if listing is not None:
            association = db.associations.get(listing["association_id"])
            if association is not None:
                buffer_minutes = association["grant_buffer_minutes"]
        superseded_id = grant.get("supersedes_grant_id")
        for other in ordered(db.grants):
            if other["id"] == grant["id"] or other["id"] == superseded_id:
                continue
            if other["lockbox_id"] != grant["lockbox_id"] or other["status"] != "APPROVED":
                continue
            if calc.grants_conflict(grant, other, buffer_minutes):
                fail("ERR_GRANT_WINDOW_CONFLICT",
                     "Another approved grant already occupies this lockbox.")

        grant["status"] = "APPROVED"
        grant["access_code"] = access_code()
        if superseded_id:
            target = db.grants.get(superseded_id)
            if target is not None and target["status"] == "APPROVED":
                target["status"] = "REVOKED"
                touch(target)
        if listing is not None:
            touch(listing)

    elif action == "DENY":
        grant["status"] = "DENIED"

    elif action == "REVOKE":
        grant["status"] = "REVOKED"
        if listing is not None:
            touch(listing)

    touch(grant)
    return ok(serialize.grant(grant))
