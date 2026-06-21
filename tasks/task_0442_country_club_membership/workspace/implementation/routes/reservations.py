"""Reservation booking + cyclic amend loop (PRD §3.4)."""
from flask import Blueprint, request

import db
import errors
import common
import services
from middleware import get_auth, require_roles
from response import success_object, success_array
from serializers import reservation_out
from timeutil import parse_iso

bp = Blueprint("reservations", __name__)

READ_ROLES = ["ClubManager", "BillingClerk", "Member"]


def _check_golf_and_fields(resource, membership, start_dt, end_dt, party_size):
    """Golf-allowed (priority 8) and field validity (priority 8 well-formed /
    semantic priority — golf 422, party_size/ends ERR_VALIDATION 422)."""
    # Golf gate first (PRD §3.4): tee-time from a non-golf category -> 422.
    if resource["kind"] == "TEE_TIME":
        category = db.categories.get(membership["category_id"])
        if not category or not category.get("allows_golf"):
            raise errors.golf_not_allowed()
    # Semantic field validity (PRD §3.4): party_size >= 1, ends_at > starts_at.
    if party_size < 1:
        raise errors.validation("party_size must be at least 1")
    if not (end_dt > start_dt):
        raise errors.validation("ends_at must be strictly after starts_at")


@bp.post("/reservations")
def create_reservation():
    role, user_id = get_auth()
    require_roles(role, ["Member"])
    body = common.get_body()
    common.require_fields(
        body,
        ["club_id", "resource_id", "membership_id", "starts_at", "ends_at", "expected_resource_version"],
    )
    club_id = common.require_string(body, "club_id")
    # Existence left-to-right: club, resource, membership (PRD §2.10).
    common.get_club(club_id)
    resource = common.get_resource(common.require_string(body, "resource_id"))
    membership = common.get_membership(common.require_string(body, "membership_id"))
    # Ownership: member may only book under own membership (priority 4).
    services.assert_owner(role, user_id, membership["id"])

    # OCC after existence/ownership; before business rules (PRD §2.11).
    expected = body.get("expected_resource_version")
    if expected != resource["version"]:
        raise errors.stale_version("expected_resource_version does not match")

    # Booking membership must be ACTIVE (priority 9).
    if membership["account_status"] != "ACTIVE":
        raise errors.membership_not_active()

    starts_at = body["starts_at"]
    ends_at = body["ends_at"]
    start_dt = parse_iso(starts_at, err=errors.validation)
    end_dt = parse_iso(ends_at, err=errors.validation)
    party_size = body.get("party_size", 1)
    if party_size is None:
        party_size = 1
    if isinstance(party_size, bool) or not isinstance(party_size, int):
        raise errors.validation("party_size must be an integer")

    _check_golf_and_fields(resource, membership, start_dt, end_dt, party_size)

    # Overlap / turnaround / seat-capacity (priority 10).
    services.check_resource_conflict(resource, start_dt, end_dt, party_size)

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "club_id": club_id,
            "resource_id": resource["id"],
            "membership_id": membership["id"],
            "starts_at": starts_at,
            "ends_at": ends_at,
            "party_size": party_size,
            "status": "CONFIRMED",
            "proposed_starts_at": None,
            "proposed_ends_at": None,
        }
    )
    db.reservations[rec["id"]] = rec
    # Holding the window changes the occupancy map -> bump resource version.
    db.touch(resource)
    return success_object(reservation_out(rec), status=201)


@bp.get("/reservations/<rid>")
def get_reservation(rid):
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    rec = common.get_reservation(rid)
    return success_object(reservation_out(rec), status=200)


@bp.get("/reservations")
def list_reservations():
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = common.pagination_params()
    records = list(db.reservations.values())
    resource_id = request.args.get("resource_id")
    membership_id = request.args.get("membership_id")
    club_id = request.args.get("club_id")
    if resource_id is not None:
        records = [r for r in records if r["resource_id"] == resource_id]
    if membership_id is not None:
        records = [r for r in records if r["membership_id"] == membership_id]
    if club_id is not None:
        records = [r for r in records if r["club_id"] == club_id]
    page, total = common.sort_and_page(records, limit, offset)
    data = [reservation_out(r) for r in page]
    return success_array(data, limit, offset, total)


@bp.post("/reservations/<rid>/propose-amend")
def propose_amend(rid):
    role, user_id = get_auth()
    require_roles(role, ["Member"])
    rec = common.get_reservation(rid)
    services.assert_owner(role, user_id, rec["membership_id"])
    if rec["status"] != "CONFIRMED":
        raise errors.invalid_state("Reservation is not CONFIRMED")
    body = common.get_body()
    common.require_fields(body, ["proposed_starts_at", "proposed_ends_at"])
    resource = db.resources[rec["resource_id"]]
    membership = db.memberships[rec["membership_id"]]
    start_dt = parse_iso(body["proposed_starts_at"], err=errors.validation)
    end_dt = parse_iso(body["proposed_ends_at"], err=errors.validation)
    party_size = rec.get("party_size", 1)

    _check_golf_and_fields(resource, membership, start_dt, end_dt, party_size)
    # Overlap check excludes this reservation's own current window (PRD §3.4).
    services.check_resource_conflict(
        resource, start_dt, end_dt, party_size, exclude_reservation_id=rec["id"]
    )

    rec["status"] = "AMEND_PENDING"
    rec["proposed_starts_at"] = body["proposed_starts_at"]
    rec["proposed_ends_at"] = body["proposed_ends_at"]
    db.touch(rec)
    return success_object(reservation_out(rec), status=200)


@bp.post("/reservations/<rid>/confirm-amend")
def confirm_amend(rid):
    role, user_id = get_auth()
    require_roles(role, ["Member"])
    rec = common.get_reservation(rid)
    services.assert_owner(role, user_id, rec["membership_id"])
    if rec["status"] != "AMEND_PENDING":
        raise errors.invalid_state("Reservation is not AMEND_PENDING")
    resource = db.resources[rec["resource_id"]]
    start_dt = parse_iso(rec["proposed_starts_at"], err=errors.validation)
    end_dt = parse_iso(rec["proposed_ends_at"], err=errors.validation)
    party_size = rec.get("party_size", 1)
    # Re-check overlap against live occupancy, excluding own current window.
    services.check_resource_conflict(
        resource, start_dt, end_dt, party_size, exclude_reservation_id=rec["id"]
    )
    rec["starts_at"] = rec["proposed_starts_at"]
    rec["ends_at"] = rec["proposed_ends_at"]
    rec["proposed_starts_at"] = None
    rec["proposed_ends_at"] = None
    rec["status"] = "CONFIRMED"
    db.touch(rec)
    return success_object(reservation_out(rec), status=200)


@bp.post("/reservations/<rid>/abandon-amend")
def abandon_amend(rid):
    role, user_id = get_auth()
    require_roles(role, ["Member"])
    rec = common.get_reservation(rid)
    services.assert_owner(role, user_id, rec["membership_id"])
    if rec["status"] != "AMEND_PENDING":
        raise errors.invalid_state("Reservation is not AMEND_PENDING")
    rec["proposed_starts_at"] = None
    rec["proposed_ends_at"] = None
    rec["status"] = "CONFIRMED"
    db.touch(rec)
    return success_object(reservation_out(rec), status=200)


@bp.post("/reservations/<rid>/cancel")
def cancel(rid):
    role, user_id = get_auth()
    require_roles(role, ["Member"])
    rec = common.get_reservation(rid)
    services.assert_owner(role, user_id, rec["membership_id"])
    if rec["status"] != "CONFIRMED":
        raise errors.invalid_state("Reservation is not CONFIRMED")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    # Freeing the window changes occupancy -> bump resource version (PRD §3.4).
    resource = db.resources.get(rec["resource_id"])
    if resource:
        db.touch(resource)
    return success_object(reservation_out(rec), status=200)


@bp.post("/reservations/<rid>/complete")
def complete(rid):
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    rec = common.get_reservation(rid)
    if rec["status"] != "CONFIRMED":
        raise errors.invalid_state("Reservation is not CONFIRMED")
    # Logical clock must be at/after ends_at (PRD §3.4 / §3.8).
    now = parse_iso(db.LOGICAL_CLOCK[0])
    end_dt = parse_iso(rec["ends_at"])
    if now < end_dt:
        raise errors.invalid_state("Logical clock has not reached ends_at")
    rec["status"] = "COMPLETED"
    db.touch(rec)
    return success_object(reservation_out(rec), status=200)
