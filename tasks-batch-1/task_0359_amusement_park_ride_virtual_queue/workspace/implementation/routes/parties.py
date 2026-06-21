"""Parties, memberships, and group booking (PRD §3.5)."""
from flask import Blueprint, request

import booking
import db
import domain
import errors
import lookups
import response
import serialize
import validate_input as vi
from middleware import get_principal, require_roles

bp = Blueprint("parties", __name__)


def _check_party_owner(party, user_id):
    """GuestApp ownership: X-User-ID must be the party's leader_guest_id (PRD §2.1)."""
    if party["leader_guest_id"] != user_id:
        errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Acting guest does not lead this party")


# ---------------------------------------------------------------------------
# Party create / read / list
# ---------------------------------------------------------------------------
@bp.post("/parks/<pid>/parties")
def create_party(pid):
    user_id, role = get_principal()
    require_roles(role, {"GuestApp"})
    park = lookups.get_park(pid)
    body = vi.get_body()
    leader_guest_id = vi.require_str(body, "leader_guest_id")
    leader = lookups.get_guest(leader_guest_id)

    # Ownership: GuestApp may only create a party it leads (PRD §2.1).
    if leader["id"] != user_id:
        errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Acting guest is not the party leader")

    if leader["park_id"] != park["id"]:
        errors.err(errors.ERR_GUEST_PARK_MISMATCH, "Leader belongs to a different park")

    party = db.stamp_new({
        "park_id": park["id"],
        "leader_guest_id": leader["id"],
        "member_count": 1,
        "party_status": "FORMING",
    })
    db.parties[party["id"]] = party

    membership = db.stamp_new({
        "party_id": party["id"],
        "guest_id": leader["id"],
        "membership_status": "LINKED",
    })
    db.party_memberships[membership["id"]] = membership

    leader["party_id"] = party["id"]
    db.touch(leader)

    return response.object_response(serialize.view("party", party), 201)


@bp.get("/parks/<pid>/parties")
def list_park_parties(pid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "GuestApp"})
    park = lookups.get_park(pid)
    leader_guest_id = request.args.get("leader_guest_id")
    records = [p for p in db.parties.values() if p["park_id"] == park["id"]]
    if leader_guest_id is not None:
        records = [p for p in records if p["leader_guest_id"] == leader_guest_id]
    return lookups.paginate_and_respond("party", records, response)


@bp.get("/parties/<party_id>")
def read_party(party_id):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "GuestApp"})
    party = lookups.get_party(party_id)
    return response.object_response(serialize.view("party", party), 200)


@bp.get("/parties")
def list_parties():
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "GuestApp"})
    park_id = request.args.get("park_id")
    leader_guest_id = request.args.get("leader_guest_id")
    records = list(db.parties.values())
    if park_id is not None:
        records = [p for p in records if p["park_id"] == park_id]
    if leader_guest_id is not None:
        records = [p for p in records if p["leader_guest_id"] == leader_guest_id]
    return lookups.paginate_and_respond("party", records, response)


# ---------------------------------------------------------------------------
# Membership link / read / list / unlink
# ---------------------------------------------------------------------------
@bp.post("/parties/<party_id>/members")
def add_member(party_id):
    user_id, role = get_principal()
    require_roles(role, {"GuestApp"})
    party = lookups.get_party(party_id)
    body = vi.get_body()
    guest_id = vi.require_str(body, "guest_id")
    guest = lookups.get_guest(guest_id)

    _check_party_owner(party, user_id)

    if party["party_status"] != "FORMING":
        errors.err(errors.ERR_INVALID_STATE, "Party is not FORMING")

    if guest["park_id"] != party["park_id"]:
        errors.err(errors.ERR_GUEST_PARK_MISMATCH, "Guest belongs to a different park")

    membership = db.stamp_new({
        "party_id": party["id"],
        "guest_id": guest["id"],
        "membership_status": "LINKED",
    })
    db.party_memberships[membership["id"]] = membership

    party["member_count"] += 1
    db.touch(party)

    guest["party_id"] = party["id"]
    db.touch(guest)

    # Linking a member advances Party.version (PRD §3.5). The membership and its
    # parent Party advance in lockstep, so the membership response's version equals
    # the party's new version — this is what a subsequent party-book echoes as
    # expected_party_version (PRD §2.7).
    membership["version"] = party["version"]
    membership["updated_at"] = party["updated_at"]

    return response.object_response(serialize.view("party_membership", membership), 201)


@bp.get("/parties/<party_id>/members")
def list_members(party_id):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "GuestApp"})
    party = lookups.get_party(party_id)
    guest_id = request.args.get("guest_id")
    records = [m for m in db.party_memberships.values() if m["party_id"] == party["id"]]
    if guest_id is not None:
        records = [m for m in records if m["guest_id"] == guest_id]
    return lookups.paginate_and_respond("party_membership", records, response)


@bp.get("/party-memberships/<mid>")
def read_membership(mid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "GuestApp"})
    membership = lookups.get_membership(mid)
    return response.object_response(serialize.view("party_membership", membership), 200)


@bp.get("/party-memberships")
def list_memberships():
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "GuestApp"})
    party_id = request.args.get("party_id")
    guest_id = request.args.get("guest_id")
    records = list(db.party_memberships.values())
    if party_id is not None:
        records = [m for m in records if m["party_id"] == party_id]
    if guest_id is not None:
        records = [m for m in records if m["guest_id"] == guest_id]
    return lookups.paginate_and_respond("party_membership", records, response)


@bp.delete("/parties/<party_id>/members/<guest_id>")
def remove_member(party_id, guest_id):
    user_id, role = get_principal()
    require_roles(role, {"GuestApp"})
    party = lookups.get_party(party_id)
    guest = lookups.get_guest(guest_id)

    _check_party_owner(party, user_id)

    # The leader may not be unlinked from its own party (PRD §3.5).
    if party["leader_guest_id"] == guest["id"]:
        errors.err(errors.ERR_LEADER_REMOVAL_FORBIDDEN, "Cannot remove the party leader")

    membership = None
    for m in db.party_memberships.values():
        if (m["party_id"] == party["id"] and m["guest_id"] == guest["id"]
                and m["membership_status"] == "LINKED"):
            membership = m
            break
    if membership is None:
        errors.err(errors.ERR_NOT_FOUND, "No active membership for this guest in the party")

    membership["membership_status"] = "REMOVED"
    db.touch(membership)

    party["member_count"] -= 1
    db.touch(party)

    guest["party_id"] = None
    db.touch(guest)

    return response.object_response(serialize.view("party_membership", membership), 200)


# ---------------------------------------------------------------------------
# Party transitions: party-book, release-lock, disband
# ---------------------------------------------------------------------------
@bp.post("/parties/<party_id>/party-book")
def party_book(party_id):
    user_id, role = get_principal()
    require_roles(role, {"GuestApp"})
    party = lookups.get_party(party_id)
    body = vi.get_body()

    ride_id = vi.require_str(body, "ride_id")
    return_window_id = vi.require_str(body, "return_window_id")
    expected_party_version = vi.require_int(body, "expected_party_version")

    ride = lookups.get_ride(ride_id)
    window = lookups.get_window(return_window_id)

    # ownership (priority 4)
    _check_party_owner(party, user_id)

    # state (priority 5): party FORMING with member_count >= 1
    if party["party_status"] != "FORMING":
        errors.err(errors.ERR_INVALID_STATE, "Party is not FORMING")
    if party["member_count"] < 1:
        errors.err(errors.ERR_INVALID_STATE, "Party has no members")

    # OCC (priority 6): expected_party_version vs Party.version
    if expected_party_version != party["version"]:
        errors.err(errors.ERR_STALE_VERSION, "Party version is stale")

    # park scope consistency
    park = db.parks.get(party["park_id"])
    if ride["park_id"] != party["park_id"]:
        errors.err(errors.ERR_GUEST_PARK_MISMATCH, "Ride belongs to a different park")
    if window["ride_id"] != ride["id"]:
        errors.err(errors.ERR_GUEST_PARK_MISMATCH, "Window does not belong to the ride")

    # The booking also clears the temporal window gate (priority 9): the chosen
    # window must not already have elapsed (PRD §3.3/§3.5 — same gates as a single
    # reservation).
    now = domain.park_now(park)
    end = domain.parse_dt(window["window_end_utc"], "window_end_utc")
    if now is not None and now >= end:
        errors.err(errors.ERR_WINDOW_NOT_REDEEMABLE, "Return window has already elapsed")

    # Iterate LINKED members in creation order for determinism.
    members = sorted(
        (m for m in db.party_memberships.values()
         if m["party_id"] == party["id"] and m["membership_status"] == "LINKED"),
        key=lambda m: m["_seq"],
    )

    # Phase 1 (validate): partition members. Height/accessibility failures are
    # skipped rather than failing the whole booking (PRD §3.5). The remaining
    # per-guest gates apply just as to a single reservation and fail the booking;
    # validate them all before committing any reservation (atomicity).
    skipped_guest_ids = []
    eligible = []
    for m in members:
        guest = db.guests.get(m["guest_id"])
        if guest is None:
            skipped_guest_ids.append(m["guest_id"])
            continue
        if guest["height_cm"] < ride["min_height_cm"]:
            skipped_guest_ids.append(guest["id"])
            continue
        if guest["uses_wheelchair"] and ride["wheelchair_transfer_required"]:
            skipped_guest_ids.append(guest["id"])
            continue
        eligible.append(guest)

    for guest in eligible:
        if park["day_phase"] == "PEAK" and not domain.guest_has_active_multipass(park["id"], guest["id"]):
            errors.err(errors.ERR_PEAK_GATE_BLOCKED, "Peak phase requires an active MULTI_PASS hold")
        if domain.active_vq_reservation_count(guest["id"]) >= domain.VQ_MAX_PER_GUEST:
            errors.err(errors.ERR_VQ_LIMIT_REACHED, "Guest at the per-guest virtual-queue ceiling")

    # Window capacity must accommodate every eligible member's slot (priority 13).
    free_slots = window["slot_capacity"] - window["reserved_count"]
    if len(eligible) > free_slots:
        errors.err(errors.ERR_WINDOW_EXHAUSTED, "Return window cannot accommodate the party")

    # Phase 2 (commit): lock the party (FORMING -> LOCKED, advances version) and
    # create one HELD VIRTUAL_QUEUE reservation per eligible member.
    party["party_status"] = "LOCKED"
    db.touch(party)

    created_reservation_ids = []
    for guest in eligible:
        res = booking.create_vq_reservation(ride, guest, window, park, party_id=party["id"])
        created_reservation_ids.append(res["id"])

    return response.object_response({
        "party_id": party["id"],
        "created_reservation_ids": created_reservation_ids,
        "skipped_guest_ids": skipped_guest_ids,
    }, 201)


@bp.post("/parties/<party_id>/release-lock")
def release_lock(party_id):
    user_id, role = get_principal()
    require_roles(role, {"GuestApp"})
    party = lookups.get_party(party_id)
    _check_party_owner(party, user_id)

    if party["party_status"] != "LOCKED":
        errors.err(errors.ERR_INVALID_STATE, "Party is not LOCKED")

    party["party_status"] = "FORMING"
    db.touch(party)
    return response.object_response(serialize.view("party", party), 200)


@bp.post("/parties/<party_id>/disband")
def disband(party_id):
    user_id, role = get_principal()
    require_roles(role, {"GuestApp"})
    party = lookups.get_party(party_id)
    _check_party_owner(party, user_id)

    if party["party_status"] != "FORMING":
        errors.err(errors.ERR_INVALID_STATE, "Party is not FORMING")

    party["party_status"] = "DISBANDED"
    db.touch(party)

    for m in db.party_memberships.values():
        if m["party_id"] == party["id"] and m["membership_status"] == "LINKED":
            m["membership_status"] = "REMOVED"
            db.touch(m)
            guest = db.guests.get(m["guest_id"])
            if guest is not None:
                guest["party_id"] = None
                db.touch(guest)

    return response.object_response(serialize.view("party", party), 200)
