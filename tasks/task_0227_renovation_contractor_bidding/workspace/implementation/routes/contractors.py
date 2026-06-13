"""Contractor routes & qualification state machine."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles
from services import common, lookups

bp = Blueprint("contractors", __name__)

TRADES = {"GENERAL", "ELECTRICAL", "PLUMBING", "HVAC", "ROOFING"}
MIN_INSURANCE_CENTS = 1000000


@bp.route("/contractors", methods=["POST"])
def create_contractor():
    # Anonymous (public).
    body = common.get_body()
    legal_name = common.as_str(common.require_field(body, "legal_name"), "legal_name")
    trade = common.as_enum(common.require_field(body, "trade"), "trade", TRADES)
    license_number = common.as_str(common.require_field(body, "license_number"), "license_number")
    license_expiry_raw = common.require_field(body, "license_expiry")
    license_expiry = common.parse_iso(license_expiry_raw, "license_expiry")
    insurance = common.as_int(
        common.require_field(body, "insurance_coverage_cents"), "insurance_coverage_cents")
    if insurance < 0:
        raise errors.invalid_request("insurance_coverage_cents must be >= 0.")

    rec = {
        "legal_name": legal_name,
        "trade": trade,
        "license_number": license_number,
        "license_expiry": license_expiry_raw,
        "_license_expiry_dt": license_expiry,
        "insurance_coverage_cents": insurance,
        "qualification_status": "PENDING",
        "rating_sum": 0,
        "rating_count": 0,
        "average_rating": 0,
    }
    common.stamp_new(rec)
    db.contractors[rec["id"]] = rec
    return response.success(common.public(rec), 201)


@bp.route("/contractors/<rid>", methods=["GET"])
def get_contractor(rid):
    require_roles("Contractor", "Homeowner", "PlatformAdmin")
    rec = lookups.get_contractor(rid)
    return response.success(common.public(rec), 200)


@bp.route("/contractors", methods=["GET"])
def list_contractors():
    require_roles("Homeowner", "PlatformAdmin")
    items = list(db.contractors.values())
    trade = request.args.get("trade")
    if trade is not None:
        items = [c for c in items if c["trade"] == trade]
    qs = request.args.get("qualification_status")
    if qs is not None:
        items = [c for c in items if c["qualification_status"] == qs]
    page, limit, offset, total = common.paginate(items)
    return response.success_list(page, limit, offset, total, 200)


@bp.route("/contractors/<rid>/qualify", methods=["POST"])
def qualify_contractor(rid):
    require_roles("PlatformAdmin")
    rec = lookups.get_contractor(rid)
    status = rec["qualification_status"]
    if status not in ("PENDING", "SUSPENDED"):
        raise errors.invalid_state("Contractor cannot be qualified from its current state.")
    # Preconditions (state-specific). For PENDING -> QUALIFIED also require non-empty license.
    if status == "PENDING":
        if not rec["license_number"]:
            raise errors.invalid_state("license_number must be non-empty to qualify.")
    if rec["_license_expiry_dt"] <= db.clock.now():
        raise errors.invalid_state("license_expiry must be in the future to qualify.")
    if rec["insurance_coverage_cents"] < MIN_INSURANCE_CENTS:
        raise errors.invalid_state("insurance_coverage_cents below minimum to qualify.")
    rec["qualification_status"] = "QUALIFIED"
    common.touch(rec)
    return response.success(common.public(rec), 200)


@bp.route("/contractors/<rid>/suspend", methods=["POST"])
def suspend_contractor(rid):
    require_roles("PlatformAdmin")
    rec = lookups.get_contractor(rid)
    if rec["qualification_status"] != "QUALIFIED":
        raise errors.invalid_state("Only a QUALIFIED contractor can be suspended.")
    rec["qualification_status"] = "SUSPENDED"
    common.touch(rec)
    return response.success(common.public(rec), 200)


@bp.route("/contractors/<rid>/revoke", methods=["POST"])
def revoke_contractor(rid):
    require_roles("PlatformAdmin")
    rec = lookups.get_contractor(rid)
    if rec["qualification_status"] != "SUSPENDED":
        raise errors.invalid_state("Only a SUSPENDED contractor can be revoked.")
    rec["qualification_status"] = "REVOKED"
    common.touch(rec)
    return response.success(common.public(rec), 200)
