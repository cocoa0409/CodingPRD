"""RenewalApplication endpoints."""

import uuid
from datetime import timedelta
from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_PERMIT_NOT_FOUND,
    ERR_RENEWAL_NOT_FOUND,
    ERR_RENEWAL_WINDOW_CLOSED,
    ERR_RENEWAL_ALREADY_PENDING,
    ERR_RENEWAL_NOT_SUBMITTED,
    ERR_RENEWAL_NOT_UNDER_REVIEW,
    ERR_RENEWAL_NOT_INFO_REQUESTED,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from response import success, list_success
from util import get_body, require_fields, parse_iso
from services.core import (
    base_entity,
    touch,
    append_audit,
    serialize_renewal_application,
    paginate,
)

bp = Blueprint("renewals", __name__)

RENEWAL_WINDOW_DAYS = 180
OPEN_STATUSES = {"SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED"}


@bp.route("/npdes/renewal-applications", methods=["POST"])
def create_renewal():
    user_id, role = require_roles(["EnvironmentalManager"])
    body = get_body()
    require_fields(body, ["permit_id", "proposed_expiration_date"])
    permit = db.permits.get(body["permit_id"])
    if permit is None:
        raise err(ERR_PERMIT_NOT_FOUND, 404, "Permit not found")
    proposed = parse_iso(body["proposed_expiration_date"], "proposed_expiration_date")

    now = db.clock.now()
    window_start = permit["expiration_date"] - timedelta(days=RENEWAL_WINDOW_DAYS)
    if not (window_start <= now < permit["expiration_date"]):
        raise err(ERR_RENEWAL_WINDOW_CLOSED, 409, "Clock is outside the renewal window")

    for r in db.renewal_applications.values():
        if r["permit_id"] == permit["id"] and r["status"] in OPEN_STATUSES:
            raise err(ERR_RENEWAL_ALREADY_PENDING, 409, "An open renewal application already exists")

    app = base_entity("RenewalApplication")
    app["id"] = str(uuid.uuid4())
    app.update(
        {
            "permit_id": permit["id"],
            "proposed_expiration_date": proposed,
            "status": "SUBMITTED",
            "submitted_at": now,
            "info_request_note": None,
            "decision_reason": None,
            "resulting_permit_id": None,
        }
    )
    db.renewal_applications[app["id"]] = app
    append_audit("RenewalApplication", app["id"], "RENEWAL_SUBMITTED", user_id, role)
    return success(serialize_renewal_application(app), 201)


@bp.route("/npdes/renewal-applications", methods=["GET"])
def list_renewals():
    require_roles(["Any"])
    items = list(db.renewal_applications.values())
    for param in ("permit_id", "status", "resulting_permit_id"):
        v = request.args.get(param)
        if v:
            items = [r for r in items if (r.get(param) or "") == v]
    page, total, limit, offset = paginate(items, request.args)
    return list_success([serialize_renewal_application(r) for r in page], total, limit, offset)


@bp.route("/npdes/renewal-applications/<rid>", methods=["GET"])
def get_renewal(rid):
    require_roles(["Any"])
    app = db.renewal_applications.get(rid)
    if app is None:
        raise err(ERR_RENEWAL_NOT_FOUND, 404, "RenewalApplication not found")
    return success(serialize_renewal_application(app), 200)


@bp.route("/npdes/renewal-applications/<rid>/start-review", methods=["POST"])
def start_review(rid):
    user_id, role = require_roles(["Regulator"])
    app = db.renewal_applications.get(rid)
    if app is None:
        raise err(ERR_RENEWAL_NOT_FOUND, 404, "RenewalApplication not found")
    if app["status"] != "SUBMITTED":
        raise err(ERR_RENEWAL_NOT_SUBMITTED, 409, "Renewal application is not SUBMITTED")
    app["status"] = "UNDER_REVIEW"
    touch(app)
    append_audit("RenewalApplication", app["id"], "RENEWAL_UNDER_REVIEW", user_id, role)
    return success(serialize_renewal_application(app), 200)


@bp.route("/npdes/renewal-applications/<rid>/request-info", methods=["POST"])
def request_info(rid):
    user_id, role = require_roles(["Regulator"])
    app = db.renewal_applications.get(rid)
    if app is None:
        raise err(ERR_RENEWAL_NOT_FOUND, 404, "RenewalApplication not found")
    if app["status"] != "UNDER_REVIEW":
        raise err(ERR_RENEWAL_NOT_UNDER_REVIEW, 409, "Renewal application is not UNDER_REVIEW")
    body = get_body()
    require_fields(body, ["info_request_note"])
    app["info_request_note"] = body["info_request_note"]
    app["status"] = "INFO_REQUESTED"
    touch(app)
    append_audit("RenewalApplication", app["id"], "RENEWAL_INFO_REQUESTED", user_id, role)
    return success(serialize_renewal_application(app), 200)


@bp.route("/npdes/renewal-applications/<rid>/resume-review", methods=["POST"])
def resume_review(rid):
    user_id, role = require_roles(["Regulator"])
    app = db.renewal_applications.get(rid)
    if app is None:
        raise err(ERR_RENEWAL_NOT_FOUND, 404, "RenewalApplication not found")
    if app["status"] != "INFO_REQUESTED":
        raise err(ERR_RENEWAL_NOT_INFO_REQUESTED, 409, "Renewal application is not INFO_REQUESTED")
    app["status"] = "UNDER_REVIEW"
    touch(app)
    append_audit("RenewalApplication", app["id"], "RENEWAL_REVIEW_RESUMED", user_id, role)
    return success(serialize_renewal_application(app), 200)


@bp.route("/npdes/renewal-applications/<rid>/approve", methods=["POST"])
def approve_renewal(rid):
    user_id, role = require_roles(["Regulator"])
    app = db.renewal_applications.get(rid)
    if app is None:
        raise err(ERR_RENEWAL_NOT_FOUND, 404, "RenewalApplication not found")
    body = get_body()
    require_fields(
        body,
        ["expected_permit_version", "new_permit_number", "new_effective_date", "new_expiration_date"],
    )
    expected = body["expected_permit_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(ERR_INVALID_REQUEST, 400, "expected_permit_version must be an integer")
    new_permit_number = body["new_permit_number"]
    if not isinstance(new_permit_number, str) or not new_permit_number:
        raise err(ERR_INVALID_REQUEST, 400, "new_permit_number must be a non-empty string")
    new_effective = parse_iso(body["new_effective_date"], "new_effective_date")
    new_expiration = parse_iso(body["new_expiration_date"], "new_expiration_date")
    if new_expiration <= new_effective:
        raise err(ERR_INVALID_REQUEST, 400, "new_expiration_date must be strictly after new_effective_date")

    permit = db.permits.get(app["permit_id"])
    if permit is None:
        raise err(ERR_PERMIT_NOT_FOUND, 404, "Permit not found")

    # OCC guard before state guard
    if expected != permit["version"]:
        raise err(ERR_STALE_VERSION, 412, "expected_permit_version does not match Permit.version")

    if app["status"] != "UNDER_REVIEW":
        raise err(ERR_RENEWAL_NOT_UNDER_REVIEW, 409, "Renewal application is not UNDER_REVIEW")

    # Link 1: create successor permit in ACTIVE
    successor = base_entity("Permit")
    successor["id"] = str(uuid.uuid4())
    successor.update(
        {
            "permit_number": new_permit_number,
            "facility_name": permit["facility_name"],
            "receiving_water_body": permit["receiving_water_body"],
            "effective_date": new_effective,
            "expiration_date": new_expiration,
            "status": "ACTIVE",
            "superseded_by_permit_id": None,
            "compliance_posture": "GOOD_STANDING",
            "open_corrective_action_count": 0,
            "open_exceedance_count": 0,
        }
    )
    db.permits[successor["id"]] = successor

    app["status"] = "APPROVED"
    app["resulting_permit_id"] = successor["id"]
    touch(app)
    append_audit("RenewalApplication", app["id"], "RENEWAL_APPROVED", user_id, role)

    # Link 2: old permit -> SUPERSEDED
    old_permit = permit
    old_permit["status"] = "SUPERSEDED"
    old_permit["superseded_by_permit_id"] = successor["id"]
    touch(old_permit)
    append_audit("Permit", old_permit["id"], "PERMIT_SUPERSEDED", "system", "system")

    # Link 3 & 4: old outfalls -> INACTIVE; their SCHEDULED samples -> CANCELLED
    for outfall in db.outfalls.values():
        if outfall["permit_id"] == old_permit["id"] and outfall["status"] == "ACTIVE":
            outfall["status"] = "INACTIVE"
            touch(outfall)
            append_audit("Outfall", outfall["id"], "OUTFALL_DEACTIVATED", "system", "system")
            for ev in db.sampling_events.values():
                if ev["outfall_id"] == outfall["id"] and ev["schedule_status"] == "SCHEDULED":
                    ev["schedule_status"] = "CANCELLED"
                    touch(ev)
                    append_audit("SamplingEvent", ev["id"], "SAMPLE_CANCELLED", "system", "system")

    return success(serialize_renewal_application(app), 200)


@bp.route("/npdes/renewal-applications/<rid>/deny", methods=["POST"])
def deny_renewal(rid):
    user_id, role = require_roles(["Regulator"])
    app = db.renewal_applications.get(rid)
    if app is None:
        raise err(ERR_RENEWAL_NOT_FOUND, 404, "RenewalApplication not found")
    if app["status"] != "UNDER_REVIEW":
        raise err(ERR_RENEWAL_NOT_UNDER_REVIEW, 409, "Renewal application is not UNDER_REVIEW")
    body = get_body()
    require_fields(body, ["reason"])
    app["decision_reason"] = body["reason"]
    app["status"] = "DENIED"
    touch(app)
    append_audit("RenewalApplication", app["id"], "RENEWAL_DENIED", user_id, role)
    return success(serialize_renewal_application(app), 200)
