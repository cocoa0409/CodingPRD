from datetime import timedelta

from flask import Blueprint, request

from db import db, iso_ms
from clock import clock, parse_iso
from middleware import require_role
from response import object_response, array_response
from errors import (
    err, ERR_INVALID_STATE, ERR_STALE_RACK_VERSION, ERR_COI_NOT_VERIFIED,
    ERR_RACK_NOT_AVAILABLE, ERR_OFFER_EXPIRED, ERR_VESSEL_ALREADY_STORED,
    ERR_NOT_FOUND, ERR_INVALID_REQUEST,
)
from services.common import (
    stamp_create, touch, get_json_body, require_fields, require_string,
    require_enum, require_bool, require_nonneg_int, parse_pagination, paginate,
)
from services.lookups import get_vessel, get_waitlist_entry, get_marina, check_vessel_owner
from services.serialize import waitlist_view
from services.calculations import compute_waitlist_priority

waitlist_bp = Blueprint("waitlist", __name__)

READ_ROLES = {"DockMaster", "BillingClerk", "BoatOwner"}
SIZE_CLASSES = {"SMALL", "MEDIUM", "LARGE"}

# PRD §3.4: offer TTL is "a fixed number of hours". No numeric value is given in
# PRD/scaffold; use a fixed 48-hour TTL.
OFFER_TTL_HOURS = 48


@waitlist_bp.route("/marina/waitlist", methods=["POST"])
def join_waitlist():
    user_id, role = require_role({"DockMaster", "BoatOwner"})
    body = get_json_body()
    require_fields(body, ["vessel_id", "requested_size_class"])
    require_string(body["vessel_id"], "vessel_id")
    require_enum(body["requested_size_class"], SIZE_CLASSES, "requested_size_class")
    deposit_paid = body.get("deposit_paid", False)
    if deposit_paid is None:
        deposit_paid = False
    require_bool(deposit_paid, "deposit_paid")
    with db.lock:
        vessel = get_vessel(body["vessel_id"])
        check_vessel_owner(vessel, user_id, role)
        rec = {
            "vessel_id": body["vessel_id"],
            "requested_size_class": body["requested_size_class"],
            "deposit_paid": deposit_paid,
            "joined_at": iso_ms(clock.now()),
            "status": "WAITING",
            "offered_rack_id": None,
            "offer_expires_at": None,
        }
        stamp_create(rec)
        db.waitlist[rec["id"]] = rec
    return object_response(waitlist_view(rec), 201)


@waitlist_bp.route("/marina/waitlist/<entry_id>", methods=["GET"])
def fetch_entry(entry_id):
    require_role(READ_ROLES)
    rec = get_waitlist_entry(entry_id)
    return object_response(waitlist_view(rec), 200)


@waitlist_bp.route("/marina/waitlist", methods=["GET"])
def list_waitlist():
    require_role(READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.waitlist.values())
    vessel_id = request.args.get("vessel_id")
    requested_size_class = request.args.get("requested_size_class")
    status = request.args.get("status")
    offered_rack_id = request.args.get("offered_rack_id")
    if vessel_id is not None:
        records = [r for r in records if r["vessel_id"] == vessel_id]
    if requested_size_class is not None:
        records = [r for r in records if r["requested_size_class"] == requested_size_class]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if offered_rack_id is not None:
        records = [r for r in records if r["offered_rack_id"] == offered_rack_id]
    # Ordered by priority_score desc, then joined_at asc (PRD §2.3/§3.4).
    now = clock.now()

    def score(r):
        return compute_waitlist_priority(r, now, parse_iso(r["joined_at"]))

    ordered = sorted(
        records,
        key=lambda r: (-score(r), parse_iso(r["joined_at"]), r["_seq"]),
    )
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return array_response([waitlist_view(r) for r in page], limit, offset, total)


@waitlist_bp.route("/marina/waitlist/promote", methods=["POST"])
def promote():
    require_role({"DockMaster"})
    body = get_json_body()
    require_fields(body, ["marina_id", "requested_size_class"])
    require_string(body["marina_id"], "marina_id")
    require_enum(body["requested_size_class"], SIZE_CLASSES, "requested_size_class")
    with db.lock:
        get_marina(body["marina_id"])
        size_class = body["requested_size_class"]
        # Priority 11: an AVAILABLE rack of the requested size class must exist.
        candidate_racks = [
            r for r in db.racks.values()
            if r["marina_id"] == body["marina_id"]
            and r["size_class"] == size_class
            and r["status"] == "AVAILABLE"
        ]
        if not candidate_racks:
            raise err(ERR_RACK_NOT_AVAILABLE, "No AVAILABLE rack of the requested size class.")
        # Select the WAITING entry with max priority_score; tie-break joined_at asc
        # then created_at asc. days_waiting measured at sweep clock and frozen.
        now = clock.now()
        waiting = [
            e for e in db.waitlist.values()
            if e["status"] == "WAITING" and e["requested_size_class"] == size_class
        ]
        if not waiting:
            raise err(ERR_INVALID_STATE, "No WAITING entry to promote.")
        winner = sorted(
            waiting,
            key=lambda e: (
                -compute_waitlist_priority(e, now, parse_iso(e["joined_at"])),
                parse_iso(e["joined_at"]),
                e["_seq"],
            ),
        )[0]
        # Choose the rack (deterministic: earliest created available rack).
        rack = sorted(candidate_racks, key=lambda r: r["_seq"])[0]
        # Side effects.
        winner["status"] = "OFFERED"
        winner["offered_rack_id"] = rack["id"]
        winner["offer_expires_at"] = iso_ms(now + timedelta(hours=OFFER_TTL_HOURS))
        touch(winner)
        # Cascade hop 1: hold the rack (OCCUPIED, current_agreement_id stays null).
        rack["status"] = "OCCUPIED"
        touch(rack)
    return object_response(waitlist_view(winner), 200)


@waitlist_bp.route("/marina/waitlist/<entry_id>/accept", methods=["POST"])
def accept_offer(entry_id):
    user_id, role = require_role({"BoatOwner"})
    body = get_json_body()
    require_fields(body, ["expected_rack_version"])
    require_nonneg_int(body["expected_rack_version"], "expected_rack_version")
    with db.lock:
        entry = get_waitlist_entry(entry_id)
        vessel = get_vessel(entry["vessel_id"])
        check_vessel_owner(vessel, user_id, role)
        # Priority 6: state.
        if entry["status"] != "OFFERED":
            raise err(ERR_INVALID_STATE, "Entry must be OFFERED to accept.")
        rack = db.racks.get(entry["offered_rack_id"])
        if rack is None:
            raise err(ERR_NOT_FOUND, "Offered rack not found.")
        # Priority 7: OCC on rack version.
        if body["expected_rack_version"] != rack["version"]:
            raise err(ERR_STALE_RACK_VERSION, "expected_rack_version does not match rack version.")
        # Priority 8: COI gate.
        if vessel.get("active_policy_id") is None:
            raise err(ERR_COI_NOT_VERIFIED, "Vessel has no verified in-window insurance.")
        # Priority 15: offer expiry (clock >= offer_expires_at).
        if clock.now() >= parse_iso(entry["offer_expires_at"]):
            raise err(ERR_OFFER_EXPIRED, "Offer has expired.")
        # Priority 17: single-storage exclusivity.
        for a in db.agreements.values():
            if a["vessel_id"] == vessel["id"] and a["status"] in ("ACTIVE", "WINTERIZED"):
                raise err(ERR_VESSEL_ALREADY_STORED, "Vessel already has an ACTIVE/WINTERIZED agreement.")
        # Side effect: create a PENDING_COI agreement (CASCADE).
        rec = {
            "vessel_id": vessel["id"],
            "rack_id": rack["id"],
            "tier_size_class": None,
            "monthly_base_cents": 0,
            "oversize_surcharge_applied": False,
            "activated_at": None,
            "terminated_at": None,
            "status": "PENDING_COI",
        }
        stamp_create(rec)
        db.agreements[rec["id"]] = rec
        entry["status"] = "PLACED"
        touch(entry)
    return object_response(waitlist_view(entry), 200)


@waitlist_bp.route("/marina/waitlist/<entry_id>/lapse", methods=["POST"])
def lapse_offer(entry_id):
    require_role({"BillingClerk"})
    with db.lock:
        entry = get_waitlist_entry(entry_id)
        if entry["status"] != "OFFERED":
            raise err(ERR_INVALID_STATE, "Entry must be OFFERED to lapse.")
        if clock.now() < parse_iso(entry["offer_expires_at"]):
            raise err(ERR_INVALID_STATE, "Offer has not yet expired.")
        entry["status"] = "EXPIRED"
        # Compensation: release the held rack.
        rack = db.racks.get(entry["offered_rack_id"])
        if rack is not None:
            rack["status"] = "AVAILABLE"
            touch(rack)
        entry["offered_rack_id"] = None
        touch(entry)
    return object_response(waitlist_view(entry), 200)


@waitlist_bp.route("/marina/waitlist/<entry_id>/withdraw", methods=["POST"])
def withdraw(entry_id):
    user_id, role = require_role({"BoatOwner"})
    with db.lock:
        entry = get_waitlist_entry(entry_id)
        vessel = get_vessel(entry["vessel_id"])
        check_vessel_owner(vessel, user_id, role)
        if entry["status"] != "WAITING":
            raise err(ERR_INVALID_STATE, "Entry must be WAITING to withdraw.")
        entry["status"] = "WITHDRAWN"
        touch(entry)
    return object_response(waitlist_view(entry), 200)
