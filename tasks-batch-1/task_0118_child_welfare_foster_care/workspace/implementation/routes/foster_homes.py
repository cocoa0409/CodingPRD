"""Foster home routes (PRD §3.4 licensing, §3.7 suspension/expiry cascades)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import errors
import helpers
import middleware
import response
from services import compute, serialize

bp = Blueprint("foster_homes", __name__)

MALTREATMENT_TYPES = {"PHYSICAL_ABUSE", "SEXUAL_ABUSE", "NEGLECT", "EMOTIONAL_ABUSE"}


def _screenings_of(home_id):
    return [s for s in db.caregiver_screenings.values() if s["foster_home_id"] == home_id]


def _has_flagged(home_id):
    return any(s["status"] == "FLAGGED" for s in _screenings_of(home_id))


def _has_pending(home_id):
    return any(s["status"] == "PENDING" for s in _screenings_of(home_id))


def _disrupt_all_active(home):
    """Cascade: disrupt every ACTIVE placement in this home; each child -> REMOVED."""
    now_iso = clock.iso(clock.now())
    for p in db.placements.values():
        if p["foster_home_id"] == home["id"] and p["status"] == "ACTIVE":
            p["status"] = "DISRUPTED"
            p["end_at"] = now_iso
            db.bump(p)
            child = db.children.get(p["child_id"])
            if child is not None:
                child["status"] = "REMOVED"
                child["current_placement_id"] = None
                db.bump(child)
    # active_placement_count is computed (counts ACTIVE) -> automatically 0 now.


@bp.route("/foster-homes", methods=["POST"])
def create_foster_home():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"LicensingWorker"})
    body = helpers.get_body()
    licensing_worker_id = helpers.require_str(body, "licensing_worker_id")
    home_name = helpers.require_str(body, "home_name")
    bed_capacity = helpers.require_int(body, "bed_capacity")
    max_age_years = helpers.require_int(body, "max_age_years")
    accepts = helpers.require_enum_array(body, "accepts_maltreatment", MALTREATMENT_TYPES, optional=False)

    worker = db.caseworkers.get(licensing_worker_id)
    if worker is None:
        raise errors.not_found("Licensing worker (caseworker) not found.")

    if bed_capacity < 1:
        raise errors.validation_limit("bed_capacity must be at least 1.")
    if max_age_years < 0 or max_age_years > 21:
        raise errors.validation_limit("max_age_years must be between 0 and 21.")

    record = {
        "licensing_worker_id": licensing_worker_id,
        "home_name": home_name,
        "bed_capacity": bed_capacity,
        "license_status": "PENDING",
        "license_expires_at": None,
        "max_age_years": max_age_years,
        "accepts_maltreatment": accepts,
    }
    db.stamp_create(record)
    db.foster_homes[record["id"]] = record
    return response.success(serialize.foster_home(record), 201)


@bp.route("/foster-homes/<hid>", methods=["GET"])
def get_foster_home(hid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "LicensingWorker", "Caseworker"})
    record = db.foster_homes.get(hid)
    if record is None:
        raise errors.not_found("Foster home not found.")
    return response.success(serialize.foster_home(record), 200)


@bp.route("/foster-homes", methods=["GET"])
def list_foster_homes():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "LicensingWorker", "Caseworker"})
    limit, offset = helpers.pagination()
    license_status = request.args.get("license_status")
    licensing_worker_id = request.args.get("licensing_worker_id")
    records = list(db.foster_homes.values())
    if license_status is not None:
        records = [r for r in records if r["license_status"] == license_status]
    if licensing_worker_id is not None:
        records = [r for r in records if r["licensing_worker_id"] == licensing_worker_id]
    page, total = helpers.paginate(records, limit, offset)
    return response.list_success([serialize.foster_home(r) for r in page], limit, offset, total)


@bp.route("/foster-homes/<hid>/license", methods=["POST"])
def license_home(hid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"LicensingWorker"})
    record = db.foster_homes.get(hid)
    if record is None:
        raise errors.not_found("Foster home not found.")
    body = helpers.get_body()
    expected = helpers.require_int(body, "expected_foster_home_version")

    # State guard: full license is from PENDING or PROVISIONAL.
    if record["license_status"] not in ("PENDING", "PROVISIONAL"):
        raise errors.invalid_state("Home is not PENDING or PROVISIONAL.")
    # Clearance gates: FLAGGED -> ERR_CLEARANCE_FLAGGED; else any PENDING -> ERR_CLEARANCES_INCOMPLETE.
    if _has_flagged(hid):
        raise errors.clearance_flagged()
    if _has_pending(hid):
        raise errors.clearances_incomplete()
    # OCC guard.
    if expected != record["version"]:
        raise errors.stale_version()

    record["license_status"] = "LICENSED"
    record["license_expires_at"] = clock.iso(clock.now() + timedelta(days=compute.LICENSE_TERM_DAYS))
    db.bump(record)
    return response.success(serialize.foster_home(record), 200)


@bp.route("/foster-homes/<hid>/license-provisional", methods=["POST"])
def license_provisional(hid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"LicensingWorker"})
    record = db.foster_homes.get(hid)
    if record is None:
        raise errors.not_found("Foster home not found.")
    # Provisional is only from PENDING.
    if record["license_status"] != "PENDING":
        raise errors.invalid_state("Home is not PENDING.")
    # A FLAGGED screening blocks even a provisional license.
    if _has_flagged(hid):
        raise errors.clearance_flagged()
    # Permitted only when at least one CaregiverScreening is still PENDING.
    if not _has_pending(hid):
        raise errors.invalid_state("Provisional license requires at least one PENDING screening.")
    record["license_status"] = "PROVISIONAL"
    record["license_expires_at"] = clock.iso(clock.now() + timedelta(days=compute.PROVISIONAL_TERM_DAYS))
    db.bump(record)
    return response.success(serialize.foster_home(record), 200)


@bp.route("/foster-homes/<hid>/suspend", methods=["POST"])
def suspend_home(hid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"LicensingWorker"})
    record = db.foster_homes.get(hid)
    if record is None:
        raise errors.not_found("Foster home not found.")
    if record["license_status"] != "LICENSED":
        raise errors.invalid_state("Home is not LICENSED.")
    record["license_status"] = "SUSPENDED"
    _disrupt_all_active(record)
    db.bump(record)
    return response.success(serialize.foster_home(record), 200)


@bp.route("/foster-homes/<hid>/reinstate", methods=["POST"])
def reinstate_home(hid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"LicensingWorker"})
    record = db.foster_homes.get(hid)
    if record is None:
        raise errors.not_found("Foster home not found.")
    if record["license_status"] != "SUSPENDED":
        raise errors.invalid_state("Home is not SUSPENDED.")
    # Reinstatement requires clearances complete; a FLAGGED screening blocks it.
    if _has_flagged(hid):
        raise errors.clearance_flagged()
    if _has_pending(hid):
        raise errors.clearances_incomplete()
    record["license_status"] = "LICENSED"
    record["license_expires_at"] = clock.iso(clock.now() + timedelta(days=compute.LICENSE_TERM_DAYS))
    db.bump(record)
    return response.success(serialize.foster_home(record), 200)


@bp.route("/foster-homes/<hid>/expire-check", methods=["POST"])
def expire_check(hid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin"})
    record = db.foster_homes.get(hid)
    if record is None:
        raise errors.not_found("Foster home not found.")
    if record["license_status"] not in ("LICENSED", "PROVISIONAL"):
        raise errors.invalid_state("Home is not LICENSED or PROVISIONAL.")
    expires = record.get("license_expires_at")
    if expires is None:
        raise errors.invalid_state("Home has no license expiry.")
    expires_dt = helpers.parse_dt(expires, "license_expires_at")
    if clock.now() <= expires_dt:
        raise errors.invalid_state("License has not yet expired.")
    record["license_status"] = "EXPIRED"
    _disrupt_all_active(record)
    db.bump(record)
    return response.success(serialize.foster_home(record), 200)
