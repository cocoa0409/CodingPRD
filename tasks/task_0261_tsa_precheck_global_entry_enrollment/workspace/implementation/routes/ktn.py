"""Approval, KTN issuance, and the KTN lifecycle (PRD §3.6)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_KTN_COVERAGE_OVERLAP,
    ERR_KTN_NOT_EXPIRED,
    ERR_VETTING_NOT_CLEARED,
)
from middleware import require_auth
from response import ok_array, ok_object
from routes._helpers import (
    order_by_created,
    paginate,
    parse_pagination,
    serialize,
    serialize_list,
    stamp_create,
    touch,
)
from services.audit import write_audit
from services.calculations import compute_ktn_expiry
from services.lookups import get_or_404, parse_iso_utc, program_by_code

bp = Blueprint("ktn", __name__)

KTN_READ_ROLES = ["SchedulingAdmin", "VettingOfficer", "Applicant", "EnrollmentOfficer"]


# --- approve & issue KTN ------------------------------------------------------
@bp.route("/applications/<app_id>/approve", methods=["POST"])
def approve(app_id):
    require_auth(["EnrollmentOfficer"])
    app = get_or_404(db.applications, app_id, "Application")

    # State precondition (priority 7): INTERVIEW_COMPLETE.
    if app["status"] != "INTERVIEW_COMPLETE":
        raise APIError(ERR_INVALID_STATE, 409, "Application must be INTERVIEW_COMPLETE to approve")

    # Background check must be CLEARED (priority 16).
    bc = _the_check(app_id)
    if bc is None or bc["status"] != "CLEARED":
        raise APIError(ERR_VETTING_NOT_CLEARED, 409, "BackgroundCheck must be CLEARED to approve")

    program = program_by_code(app["program_code"])
    issued_at = db.clock.now()
    expires_at = compute_ktn_expiry(issued_at, program["validity_years"])

    # Coverage-overlap guard (priority 16.5): the closed [issued_at, expires_at]
    # interval must not overlap any ACTIVE KTN for the same applicant+program,
    # unless this application is a valid renewal of that KTN's application.
    applicant_id = app["applicant_id"]
    program_code = app["program_code"]
    prior_app_id = app.get("renews_from_application_id")

    superseded_target = None
    for k in db.known_traveler_numbers.values():
        if k.get("status") != "ACTIVE":
            continue
        if k.get("applicant_id") != applicant_id:
            continue
        k_app = db.applications.get(k.get("application_id"))
        if k_app is None or k_app.get("program_code") != program_code:
            continue
        k_start = parse_iso_utc(k["issued_at"])
        k_end = parse_iso_utc(k["expires_at"])
        # Closed-interval overlap: shared endpoints count.
        overlaps = (issued_at <= k_end) and (k_start <= expires_at)
        if not overlaps:
            continue
        # Permitted iff this is a valid renewal of that KTN's application.
        if prior_app_id is not None and k.get("application_id") == prior_app_id:
            superseded_target = k
        else:
            raise APIError(ERR_KTN_COVERAGE_OVERLAP, 409,
                           "New KTN coverage overlaps an existing ACTIVE KTN")

    # Issue the credential.
    ktn = {
        "application_id": app_id,
        "applicant_id": applicant_id,
        "ktn_value": db.new_ktn_value(),
        "issued_at": db.iso(issued_at),
        "expires_at": db.iso(expires_at),
        "renews_from_ktn_id": None,
        "status": "ACTIVE",
    }

    # Renewal: link to the prior KTN and supersede it.
    if prior_app_id is not None:
        prior_ktn = superseded_target or _active_ktn_for_application(prior_app_id)
        if prior_ktn is not None:
            ktn["renews_from_ktn_id"] = prior_ktn["id"]
            prior_ktn["status"] = "SUPERSEDED"
            touch(prior_ktn)
            write_audit(app_id, "KTN_SUPERSEDED", "Prior KTN superseded by renewal")

    stamp_create(ktn)
    db.known_traveler_numbers[ktn["id"]] = ktn

    app["status"] = "APPROVED"
    touch(app)
    write_audit(app_id, "KTN_ISSUED", "Application approved; KTN issued")
    return ok_object(serialize(app), 200)


# --- reads --------------------------------------------------------------------
@bp.route("/applications/<app_id>/known-traveler-numbers", methods=["GET"])
def list_application_ktns(app_id):
    require_auth(KTN_READ_ROLES)
    get_or_404(db.applications, app_id, "Application")
    limit, offset = parse_pagination()
    items = [k for k in db.known_traveler_numbers.values() if k.get("application_id") == app_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.route("/known-traveler-numbers/<kid>", methods=["GET"])
def get_ktn(kid):
    require_auth(KTN_READ_ROLES)
    rec = get_or_404(db.known_traveler_numbers, kid, "KnownTravelerNumber")
    return ok_object(serialize(rec), 200)


@bp.route("/known-traveler-numbers/<kid>/renewals", methods=["GET"])
def list_ktn_renewals(kid):
    require_auth(KTN_READ_ROLES)
    get_or_404(db.known_traveler_numbers, kid, "KnownTravelerNumber")
    limit, offset = parse_pagination()
    items = [k for k in db.known_traveler_numbers.values() if k.get("renews_from_ktn_id") == kid]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


# --- revoke / expire-sweep ----------------------------------------------------
@bp.route("/known-traveler-numbers/<kid>/revoke", methods=["POST"])
def revoke(kid):
    require_auth(["VettingOfficer"])
    ktn = get_or_404(db.known_traveler_numbers, kid, "KnownTravelerNumber")
    if ktn["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "KTN must be ACTIVE to revoke")
    ktn["status"] = "REVOKED"
    touch(ktn)
    write_audit(ktn["application_id"], "KTN_REVOKED", "KTN revoked")
    return ok_object(serialize(ktn), 200)


@bp.route("/known-traveler-numbers/<kid>/expire-sweep", methods=["POST"])
def expire_sweep(kid):
    require_auth(["SchedulingAdmin"])
    ktn = get_or_404(db.known_traveler_numbers, kid, "KnownTravelerNumber")
    if ktn["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "KTN must be ACTIVE to expire")
    expires = parse_iso_utc(ktn["expires_at"])
    if expires is not None and db.clock.now() < expires:
        raise APIError(ERR_KTN_NOT_EXPIRED, 409, "KTN has not yet expired")
    ktn["status"] = "EXPIRED"
    touch(ktn)
    write_audit(ktn["application_id"], "KTN_EXPIRED", "KTN expired via sweep")
    return ok_object(serialize(ktn), 200)


# --- helpers ------------------------------------------------------------------
def _the_check(app_id: str):
    for bc in db.background_checks.values():
        if bc.get("application_id") == app_id:
            return bc
    return None


def _active_ktn_for_application(application_id: str):
    for k in db.known_traveler_numbers.values():
        if k.get("application_id") == application_id and k.get("status") == "ACTIVE":
            return k
    return None
