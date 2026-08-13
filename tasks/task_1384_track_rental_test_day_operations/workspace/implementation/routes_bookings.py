"""Bookings, drivers, waivers, safety inspections."""

import uuid
from datetime import timedelta

from flask import Blueprint

import db
import errors
import helpers as h
import response

bp = Blueprint("bookings", __name__)

ALL_ROLES = ("TrackOps", "SafetyOfficer", "Coach", "Organizer")

CERT_RANK = {"BASIC": 0, "INTERMEDIATE": 1, "RACE": 2}


def _cert_sufficient(cert_level, run_group_class):
    if run_group_class == "NOVICE":
        return CERT_RANK[cert_level] >= CERT_RANK["INTERMEDIATE"]
    if run_group_class == "RACE":
        return cert_level == "RACE"
    return True


def _check_coach_attachable(track, day, booking, coach):
    """Qualification rules applied whenever a coach is attached to a booking (PRD §3.1)."""
    if not coach["active"]:
        raise errors.invalid_request("coach is not active and cannot be assigned")
    if not _cert_sufficient(coach["cert_level"], booking["run_group_class"]):
        raise errors.coach_cert_insufficient()
    if h.coach_load_on_day(coach["id"], day["id"]) >= h.MAX_BOOKINGS_PER_COACH:
        raise errors.coach_overloaded()


def _cancel_policy_snapshot():
    return {
        "full_refund_hours": h.FULL_REFUND_HOURS,
        "half_refund_hours": h.HALF_REFUND_HOURS,
        "weather_facility_fee_cents": h.WEATHER_FACILITY_FEE_CENTS,
        "fee_per_driver_cents": h.FEE_PER_DRIVER_CENTS,
    }


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------
@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>/bookings", methods=["POST"])
def create_booking(tid, tdid, rbid):
    h.require_roles("Organizer")
    track, day, block = h.resolve_rental_block(tid, tdid, rbid)
    data = h.body()
    organizer_user_id = h.req_string(data, "organizer_user_id")
    group_name = h.req_string(data, "group_name")
    run_group_class = h.req_enum(data, "run_group_class", h.RUN_GROUP_CLASSES)
    driver_count = h.req_int(data, "driver_count")
    if "insurance_policy_ref" in data and data["insurance_policy_ref"] is not None:
        if not isinstance(data["insurance_policy_ref"], str):
            raise errors.invalid_request("field 'insurance_policy_ref' must be a string")
        insurance_policy_ref = data["insurance_policy_ref"]
    else:
        insurance_policy_ref = None
    coach_id = h.opt_string(data, "coach_id")
    coach = None
    if coach_id is not None:
        coach = db.coaches.get(coach_id)
        if coach is None or coach["track_id"] != track["id"]:
            raise errors.not_found("coach %s not found" % coach_id)
    # Track-day liveness (priority 6)
    if day["status"] in ("CANCELLED", "CLOSED"):
        raise errors.track_day_not_live()
    # Block state (priority 7)
    if block["status"] == "CLOSED":
        raise errors.invalid_state("rental block is CLOSED")
    # Driver-count bounds (priority 17)
    if driver_count < 1 or driver_count > block["max_group_size"]:
        raise errors.invalid_driver_count()
    # Seat availability (priority 18): block FULL rejects new submissions
    if block["status"] == "FULL":
        raise errors.block_full()
    # Coach attachment qualification rules (PRD §3.1)
    if coach is not None:
        _check_coach_attachable(track, day, {"run_group_class": run_group_class}, coach)
    booking = {
        "id": str(uuid.uuid4()),
        "rental_block_id": block["id"],
        "organizer_user_id": organizer_user_id,
        "group_name": group_name,
        "run_group_class": run_group_class,
        "driver_count": driver_count,
        "insurance_policy_ref": insurance_policy_ref,
        "approval_status": "PENDING",
        "payment_status": "UNPAID",
        "cancel_policy_snapshot": None,
        "refund_cents": 0,
        "coach_id": coach_id,
        "created_at": h.now_str(),
        "updated_at": h.now_str(),
        "version": 1,
    }
    db.bookings[booking["id"]] = booking
    return response.success(h.serialize_booking(booking), 201)


@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>/bookings/<bid>", methods=["GET"])
def get_booking(tid, tdid, rbid, bid):
    h.require_roles(*ALL_ROLES)
    _, _, _, booking = h.resolve_booking(tid, tdid, rbid, bid)
    return response.success(h.serialize_booking(booking), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>/bookings", methods=["GET"])
def list_bookings(tid, tdid, rbid):
    h.require_roles(*ALL_ROLES)
    _, _, block = h.resolve_rental_block(tid, tdid, rbid)
    approval_status = h.query_enum("approval_status", h.BOOKING_APPROVAL_STATUSES)
    run_group_class = h.query_enum("run_group_class", h.RUN_GROUP_CLASSES)
    limit, offset = h.pagination()
    items = [b for b in db.bookings.values() if b["rental_block_id"] == block["id"]]
    if approval_status is not None:
        items = [b for b in items if b["approval_status"] == approval_status]
    if run_group_class is not None:
        items = [b for b in items if b["run_group_class"] == run_group_class]
    items.sort(key=lambda b: b["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([h.serialize_booking(b) for b in page], total, limit, offset)


@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>/bookings/<bid>/approve", methods=["POST"])
def approve_booking(tid, tdid, rbid, bid):
    h.require_roles("TrackOps")
    track, day, block, booking = h.resolve_booking(tid, tdid, rbid, bid)
    data = h.body()
    expected = h.req_int(data, "expected_rental_block_version")
    # OCC (priority 5)
    if expected != block["version"]:
        raise errors.stale_version("expected_rental_block_version does not match the block's current version")
    # Liveness (priority 6)
    if day["status"] in ("CANCELLED", "CLOSED"):
        raise errors.track_day_not_live()
    # State gate (priority 7)
    if booking["approval_status"] != "PENDING":
        raise errors.invalid_state("booking must be PENDING to approve")
    if block["status"] == "CLOSED":
        raise errors.invalid_state("rental block is CLOSED")
    if day["status"] not in ("OPEN", "RUNNING"):
        raise errors.invalid_state("track day must be OPEN or RUNNING to approve a booking")
    if booking["run_group_class"] == "NOVICE" and booking["coach_id"] is None:
        raise errors.invalid_state("a NOVICE booking requires a coach to be attached before approval")
    # Posture (priority 8)
    if day["posture"] == "SUSPENDED":
        raise errors.track_suspended()
    # Seating (priority 18)
    h.recompute_block_seats(block)
    if booking["driver_count"] > block["seats_available"]:
        raise errors.block_full()
    # Insurance (priority 19)
    if not booking["insurance_policy_ref"]:
        raise errors.insurance_missing()
    booking["approval_status"] = "APPROVED"
    booking["cancel_policy_snapshot"] = _cancel_policy_snapshot()
    booking["updated_at"] = h.now_str()
    booking["version"] += 1
    h.recompute_block_seats(block)
    block["updated_at"] = h.now_str()
    block["version"] += 1
    for driver in db.drivers.values():
        if driver["booking_id"] == booking["id"]:
            h.recompute_driver_cleared(driver)
    return response.success(h.serialize_booking(booking), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>/bookings/<bid>/reject", methods=["POST"])
def reject_booking(tid, tdid, rbid, bid):
    h.require_roles("TrackOps")
    _, _, _, booking = h.resolve_booking(tid, tdid, rbid, bid)
    h.body()
    if booking["approval_status"] != "PENDING":
        raise errors.invalid_state("booking must be PENDING to reject")
    booking["approval_status"] = "REJECTED"
    booking["updated_at"] = h.now_str()
    booking["version"] += 1
    return response.success(h.serialize_booking(booking), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(tid, tdid, rbid, bid):
    role = h.require_roles("TrackOps", "Organizer")
    _, day, block, booking = h.resolve_booking(tid, tdid, rbid, bid)
    data = h.body()
    reason = None
    if "reason" in data and data["reason"] is not None:
        reason = h.req_enum(data, "reason", h.CANCEL_REASONS)
    # Ownership: an Organizer may cancel only their own bookings (PRD §2.1, §3.9).
    if role == "Organizer" and h.caller_id() != booking["organizer_user_id"]:
        raise errors.forbidden_role("an organizer may cancel only their own bookings")
    if booking["approval_status"] != "APPROVED":
        raise errors.invalid_state("only an APPROVED booking can be cancelled")
    effective_reason = reason if reason is not None else "CUSTOMER"
    h.cancel_booking_effects(booking, block, effective_reason, day)
    block["updated_at"] = h.now_str()
    block["version"] += 1
    return response.success(h.serialize_booking(booking), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>/bookings/<bid>/assign_coach", methods=["POST"])
def assign_coach(tid, tdid, rbid, bid):
    h.require_roles("TrackOps")
    track, day, block, booking = h.resolve_booking(tid, tdid, rbid, bid)
    data = h.body()
    coach_id = h.req_string(data, "coach_id")
    coach = db.coaches.get(coach_id)
    if coach is None or coach["track_id"] != track["id"]:
        raise errors.not_found("coach %s not found" % coach_id)
    # Posture (priority 8)
    if day["posture"] == "SUSPENDED":
        raise errors.track_suspended()
    # Active / certificate sufficiency (priority 11) / load (priority 12)
    _check_coach_attachable(track, day, booking, coach)
    booking["coach_id"] = coach["id"]
    booking["updated_at"] = h.now_str()
    booking["version"] += 1
    return response.success(h.serialize_booking(booking), 200)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>/bookings/<bid>/drivers", methods=["POST"])
def create_driver(tid, tdid, rbid, bid):
    h.require_roles("Organizer")
    _, _, _, booking = h.resolve_booking(tid, tdid, rbid, bid)
    data = h.body()
    driver = {
        "id": str(uuid.uuid4()),
        "booking_id": booking["id"],
        "full_name": h.req_string(data, "full_name"),
        "license_class": h.req_enum(data, "license_class", h.LICENSE_CLASSES),
        "waiver_status": "PENDING",
        "safety_status": "NOT_INSPECTED",
        "cleared_to_run": False,
        "created_at": h.now_str(),
        "updated_at": h.now_str(),
        "version": 1,
    }
    db.drivers[driver["id"]] = driver
    h.recompute_driver_cleared(driver)
    return response.success(h.serialize_driver(driver), 201)


@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>/bookings/<bid>/drivers/<did>", methods=["GET"])
def get_driver(tid, tdid, rbid, bid, did):
    h.require_roles(*ALL_ROLES)
    _, _, _, _, driver = h.resolve_driver(tid, tdid, rbid, bid, did)
    return response.success(h.serialize_driver(driver), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>/bookings/<bid>/drivers", methods=["GET"])
def list_drivers(tid, tdid, rbid, bid):
    h.require_roles(*ALL_ROLES)
    _, _, _, booking = h.resolve_booking(tid, tdid, rbid, bid)
    limit, offset = h.pagination()
    items = [d for d in db.drivers.values() if d["booking_id"] == booking["id"]]
    items.sort(key=lambda d: d["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([h.serialize_driver(d) for d in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Waiver
# ---------------------------------------------------------------------------
@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>/bookings/<bid>/drivers/<did>/waiver", methods=["POST"])
def submit_waiver(tid, tdid, rbid, bid, did):
    h.require_roles("Organizer", "TrackOps")
    _, _, _, _, driver = h.resolve_driver(tid, tdid, rbid, bid, did)
    data = h.body()
    if "signed_at_utc" not in data:
        raise errors.invalid_request("field 'signed_at_utc' is required")
    signed_dt = h.parse_dt(data["signed_at_utc"])
    signature_payload_hash = h.req_string(data, "signature_payload_hash")
    expires_dt = signed_dt + timedelta(hours=h.WAIVER_TTL_HOURS)
    waiver = {
        "id": str(uuid.uuid4()),
        "driver_id": driver["id"],
        "signed_at_utc": h.fmt_dt(signed_dt),
        "expires_at_utc": h.fmt_dt(expires_dt),
        "signature_payload_hash": signature_payload_hash,
        "created_at": h.now_str(),
    }
    db.waivers[waiver["id"]] = waiver
    driver["waiver_status"] = "SIGNED"
    driver["updated_at"] = h.now_str()
    driver["version"] += 1
    h.recompute_driver_cleared(driver)
    return response.success(h.serialize_waiver(waiver), 201)


@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>/bookings/<bid>/drivers/<did>/waivers", methods=["GET"])
def list_waivers(tid, tdid, rbid, bid, did):
    h.require_roles(*ALL_ROLES)
    _, _, _, _, driver = h.resolve_driver(tid, tdid, rbid, bid, did)
    limit, offset = h.pagination()
    items = [w for w in db.waivers.values() if w["driver_id"] == driver["id"]]
    items.sort(key=lambda w: w["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([h.serialize_waiver(w) for w in page], total, limit, offset)


# ---------------------------------------------------------------------------
# SafetyInspection
# ---------------------------------------------------------------------------
@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>/bookings/<bid>/drivers/<did>/inspect", methods=["POST"])
def inspect_driver(tid, tdid, rbid, bid, did):
    h.require_roles("SafetyOfficer")
    _, _, _, booking, driver = h.resolve_driver(tid, tdid, rbid, bid, did)
    data = h.body()
    inspector_user_id = h.req_string(data, "inspector_user_id")
    helmet_ok = h.req_bool(data, "helmet_ok")
    harness_ok = h.req_bool(data, "harness_ok")
    # State check (priority 7) fires before segregation of duties (priority 9).
    if driver["safety_status"] not in ("NOT_INSPECTED", "FAILED"):
        raise errors.invalid_state("driver in safety_status %s cannot be inspected" % driver["safety_status"])
    if inspector_user_id == booking["organizer_user_id"]:
        raise errors.segregation_of_duties("inspector_user_id must differ from the booking's organizer_user_id")
    result = "PASSED" if (helmet_ok and harness_ok) else "FAILED"
    inspection = {
        "id": str(uuid.uuid4()),
        "driver_id": driver["id"],
        "inspector_user_id": inspector_user_id,
        "helmet_ok": helmet_ok,
        "harness_ok": harness_ok,
        "result": result,
        "inspected_at_utc": h.now_str(),
        "created_at": h.now_str(),
    }
    db.inspections[inspection["id"]] = inspection
    driver["safety_status"] = result
    driver["updated_at"] = h.now_str()
    driver["version"] += 1
    h.recompute_driver_cleared(driver)
    return response.success(h.serialize_inspection(inspection), 201)


@bp.route("/tracks/<tid>/track-days/<tdid>/rental-blocks/<rbid>/bookings/<bid>/drivers/<did>/inspections", methods=["GET"])
def list_inspections(tid, tdid, rbid, bid, did):
    h.require_roles(*ALL_ROLES)
    _, _, _, _, driver = h.resolve_driver(tid, tdid, rbid, bid, did)
    limit, offset = h.pagination()
    items = [i for i in db.inspections.values() if i["driver_id"] == driver["id"]]
    items.sort(key=lambda i: i["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([h.serialize_inspection(i) for i in page], total, limit, offset)
