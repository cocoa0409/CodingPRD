"""Therapist license endpoints."""
from datetime import date

from flask import Blueprint

import db
import errors
from auth import require_roles
from clock import clock
from respond import success
from services.domain import get_or_404, release_chair
from validate import apply_filters, json_body, opt_str, paginate, req_date, req_str

bp = Blueprint("licenses", __name__)


@bp.post("/chair-massage/therapist-licenses")
@require_roles("PlatformAdmin")
def create_license():
    body = json_body()
    therapist_id = req_str(body, "therapist_id")
    region_id = req_str(body, "region_id")
    number = req_str(body, "license_number")
    issued_on = req_date(body, "issued_on")
    expires_on = req_date(body, "expires_on")
    get_or_404("therapists", therapist_id, "Therapist")
    get_or_404("regions", region_id, "Region")
    if date.fromisoformat(expires_on) <= date.fromisoformat(issued_on):
        raise errors.invalid_request("expires_on must be strictly greater than issued_on")
    for existing in db.stores["therapist_licenses"].values():
        if (existing["therapist_id"] == therapist_id
                and existing["region_id"] == region_id
                and existing["license_number"] == number):
            raise errors.invalid_request(
                "license_number must be unique within (therapist_id, region_id)")
    lic = db.stamp_new({
        "id": db.new_id(),
        "therapist_id": therapist_id,
        "region_id": region_id,
        "license_number": number,
        "issued_on": issued_on,
        "expires_on": expires_on,
        "status": "ACTIVE",
        "suspension_reason": "",
    })
    db.insert("therapist_licenses", lic)
    return success(db.public(lic), status=201)


@bp.get("/chair-massage/therapist-licenses")
@require_roles("PlatformAdmin", "Organizer")
def list_licenses():
    items = db.all_sorted("therapist_licenses")
    items = apply_filters(items, {
        "therapist_id": (lambda e: e["therapist_id"], "str"),
        "region_id": (lambda e: e["region_id"], "str"),
        "status": (lambda e: e["status"], "str"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/therapist-licenses/<lid>")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def get_license(lid):
    lic = get_or_404("therapist_licenses", lid, "TherapistLicense")
    return success(db.public(lic))


@bp.post("/chair-massage/therapist-licenses/<lid>/suspend")
@require_roles("PlatformAdmin")
def suspend_license(lid):
    lic = get_or_404("therapist_licenses", lid, "TherapistLicense")
    if lic["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE license can be suspended")
    body = json_body()
    reason = opt_str(body, "reason") or ""
    lic["status"] = "SUSPENDED"
    lic["suspension_reason"] = reason
    db.touch(lic)
    return success(db.public(lic))


@bp.post("/chair-massage/therapist-licenses/<lid>/reinstate")
@require_roles("PlatformAdmin")
def reinstate_license(lid):
    lic = get_or_404("therapist_licenses", lid, "TherapistLicense")
    if lic["status"] != "SUSPENDED":
        raise errors.invalid_state("Only a SUSPENDED license can be reinstated")
    if lic["expires_on"] < clock.today():
        raise errors.invalid_state("Cannot reinstate a license whose expiry has passed")
    lic["status"] = "ACTIVE"
    lic["suspension_reason"] = ""
    db.touch(lic)
    return success(db.public(lic))


@bp.post("/chair-massage/therapist-licenses/<lid>/revoke")
@require_roles("PlatformAdmin")
def revoke_license(lid):
    lic = get_or_404("therapist_licenses", lid, "TherapistLicense")
    if lic["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE license can be revoked")
    lic["status"] = "REVOKED"
    db.touch(lic)
    today = clock.today()
    for chair in db.all_sorted("chair_slots"):
        if chair["status"] != "ASSIGNED" or chair["therapist_id"] != lic["therapist_id"]:
            continue
        booking = db.get("bookings", chair["booking_id"])
        if (booking and booking["region_id"] == lic["region_id"]
                and booking["event_date"] >= today):
            release_chair(chair, booking)
            db.touch(booking)
    return success(db.public(lic))
