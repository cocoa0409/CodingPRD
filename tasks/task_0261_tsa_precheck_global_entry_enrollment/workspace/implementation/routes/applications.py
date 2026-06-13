"""Application core lifecycle: create, read, pay, submit, withdraw (PRD §3.2, §3.8).

Other Application transitions (vetting, adjudication, appointments, approval,
appeals) live in their topic-specific route modules but all bump the governing
Application.version via _helpers.touch().
"""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_APPLICANT_NOT_FOUND,
    ERR_ELIGIBILITY_CITIZENSHIP,
    ERR_INVALID_STATE,
    ERR_PERMANENTLY_DISQUALIFIED,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_RENEWAL_SOURCE_INVALID,
    ERR_RENEWAL_TOO_EARLY,
    ERR_STALE_VERSION,
)
from middleware import require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    optional_str,
    order_by_created,
    paginate,
    parse_pagination,
    require_enum,
    require_fields,
    require_int,
    require_str,
    serialize,
    serialize_list,
    stamp_create,
    touch,
)
from services.audit import write_audit
from services.calculations import compute_fee_due, compute_refund_due
from services.lookups import get_or_404, parse_iso_utc, program_by_code

bp = Blueprint("applications", __name__)

APP_READ_ROLES = ["SchedulingAdmin", "VettingOfficer", "EnrollmentOfficer", "AppealsOfficer", "Applicant"]
APP_LIST_ROLES = ["SchedulingAdmin", "VettingOfficer", "EnrollmentOfficer", "AppealsOfficer"]
FEE_LIST_ROLES = ["SchedulingAdmin", "Applicant", "VettingOfficer"]
WRITE_ROLES = ["Applicant", "SchedulingAdmin"]

WITHDRAWABLE = {"DRAFT", "SUBMITTED", "VETTING", "INTERVIEW_SCHEDULED", "DENIED", "APPEAL_PENDING"}


# --- create / read ------------------------------------------------------------
@bp.route("/applications", methods=["POST"])
def create_application():
    require_auth(WRITE_ROLES)
    body = get_body()
    require_fields(body, ["applicant_id", "program_code"])
    applicant_id = require_str(body, "applicant_id")
    program_code = require_enum(body, "program_code", ["PRECHECK", "GLOBAL_ENTRY"])
    renews_from = optional_str(body, "renews_from_application_id", default=None)

    # Body-FK existence (priority 4). Application creation has the specialization
    # that a missing applicant_id yields ERR_APPLICANT_NOT_FOUND (PRD §2.5).
    if applicant_id not in db.applicants:
        raise APIError(ERR_APPLICANT_NOT_FOUND, 404, "Applicant does not exist")
    if renews_from is not None and renews_from not in db.applications:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 404,
                       "renews_from_application_id does not exist")

    rec = {
        "applicant_id": applicant_id,
        "program_code": program_code,
        "renews_from_application_id": renews_from,
        "fee_due_cents": 0,
        "fee_paid_cents": 0,
        "adverse_reason": None,
        "appeal_count": 0,
        "status": "DRAFT",
    }
    stamp_create(rec)
    db.applications[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/applications", methods=["GET"])
def list_applications():
    require_auth(APP_LIST_ROLES)
    limit, offset = parse_pagination()
    items = list(db.applications.values())
    for key in ("applicant_id", "program_code", "status", "renews_from_application_id"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a.get(key) == val]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.route("/applications/<app_id>", methods=["GET"])
def get_application(app_id):
    require_auth(APP_READ_ROLES)
    rec = get_or_404(db.applications, app_id, "Application")
    return ok_object(serialize(rec), 200)


# --- payments -----------------------------------------------------------------
@bp.route("/applications/<app_id>/pay", methods=["POST"])
def pay(app_id):
    require_auth(WRITE_ROLES)
    app = get_or_404(db.applications, app_id, "Application")
    body = get_body()
    require_fields(body, ["amount_cents"])
    amount = require_int(body, "amount_cents", minimum=1)
    reason = optional_str(body, "reason", default=None)

    txn = {
        "application_id": app_id,
        "kind": "PAYMENT",
        "amount_cents": amount,
        "reason": reason,
    }
    stamp_create(txn, full=False)
    db.fee_transactions[txn["id"]] = txn

    app["fee_paid_cents"] += amount
    touch(app)
    return ok_object(serialize(txn), 201)


@bp.route("/applications/<app_id>/fee-transactions", methods=["GET"])
def list_fee_transactions(app_id):
    require_auth(FEE_LIST_ROLES)
    get_or_404(db.applications, app_id, "Application")
    limit, offset = parse_pagination()
    items = [t for t in db.fee_transactions.values() if t.get("application_id") == app_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


# --- submit -------------------------------------------------------------------
@bp.route("/applications/<app_id>/submit", methods=["POST"])
def submit(app_id):
    require_auth(WRITE_ROLES)
    app = get_or_404(db.applications, app_id, "Application")

    # State precondition (priority 7).
    if app["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Application must be in DRAFT to submit")

    # Referenced applicant exists (PRD §3.2 — submit re-checks applicant).
    applicant = db.applicants.get(app["applicant_id"])
    if applicant is None:
        raise APIError(ERR_APPLICANT_NOT_FOUND, 404, "Applicant does not exist")

    # Business-safety: permanently disqualified (priority 8).
    if applicant.get("disqualifying_flag"):
        raise APIError(ERR_PERMANENTLY_DISQUALIFIED, 403,
                       "Applicant self-declared a permanently disqualifying conviction")

    # Eligibility: GLOBAL_ENTRY citizenship (priority 9).
    if app["program_code"] == "GLOBAL_ENTRY":
        if applicant.get("citizenship") not in ("US_CITIZEN", "LPR"):
            raise APIError(ERR_ELIGIBILITY_CITIZENSHIP, 422,
                           "GLOBAL_ENTRY requires US_CITIZEN or LPR")

    program = program_by_code(app["program_code"])

    # Renewal source validity (priority 10) + too-early (priority 11).
    is_renewal = app.get("renews_from_application_id") is not None
    if is_renewal:
        prior = db.applications.get(app["renews_from_application_id"])
        if (prior is None
                or prior.get("status") != "APPROVED"
                or prior.get("applicant_id") != app["applicant_id"]
                or prior.get("program_code") != app["program_code"]):
            raise APIError(ERR_RENEWAL_SOURCE_INVALID, 409,
                           "renews_from_application_id must reference an APPROVED application "
                           "sharing applicant_id and program_code")
        # Too-early: must be submitted no sooner than prior KTN.expires_at minus
        # renewal_window_days. The prior KTN is the ACTIVE KTN issued from the
        # prior application.
        prior_ktn = _active_ktn_for_application(prior["id"])
        if prior_ktn is not None and program is not None:
            expires_dt = parse_iso_utc(prior_ktn["expires_at"])
            if expires_dt is not None:
                window_days = program.get("renewal_window_days", 180)
                earliest = expires_dt - _timedelta_days(window_days)
                if db.clock.now() < earliest:
                    raise APIError(ERR_RENEWAL_TOO_EARLY, 409,
                                   "Renewal submitted before the renewal window opens")

    # Compute fee due (PRD §3.2).
    base = program["base_fee_cents"] if program is not None else 0
    app["fee_due_cents"] = compute_fee_due(base, is_renewal)
    app["status"] = "SUBMITTED"
    touch(app)
    write_audit(app_id, "APPLICATION_SUBMITTED", "Application submitted")
    return ok_object(serialize(app), 200)


# --- withdraw -----------------------------------------------------------------
@bp.route("/applications/<app_id>/withdraw", methods=["POST"])
def withdraw(app_id):
    require_auth(WRITE_ROLES)
    app = get_or_404(db.applications, app_id, "Application")
    body = get_body()
    require_fields(body, ["expected_application_version"])
    expected = require_int(body, "expected_application_version")

    # OCC (priority 6) is checked before the state precondition (PRD §2.9).
    if expected != app["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "expected_application_version mismatch")

    # State precondition (priority 7).
    if app["status"] not in WITHDRAWABLE:
        raise APIError(ERR_INVALID_STATE, 409, "Application cannot be withdrawn from its current state")

    status_at_withdraw = app["status"]

    # Refund (computed against the status at withdrawal time).
    refund = compute_refund_due(app["fee_paid_cents"], status_at_withdraw)
    if refund > 0:
        txn = {
            "application_id": app_id,
            "kind": "REFUND",
            "amount_cents": refund,
            "reason": "withdrawal refund",
        }
        stamp_create(txn, full=False)
        db.fee_transactions[txn["id"]] = txn
        app["fee_paid_cents"] -= refund

    # Cascade: any CONFIRMED appointment -> CANCELLED, free its slot.
    for appt in db.appointments.values():
        if appt.get("application_id") == app_id and appt.get("status") == "CONFIRMED":
            appt["status"] = "CANCELLED"
            touch(appt)
            slot = db.appointment_slots.get(appt.get("slot_id"))
            if slot is not None and slot.get("status") == "BOOKED":
                slot["status"] = "AVAILABLE"
                slot["held_by_appointment_id"] = None
                touch(slot)

    # Cascade: any OPEN appeal -> DECIDED(UPHELD).
    for appeal in db.appeals.values():
        if appeal.get("application_id") == app_id and appeal.get("status") == "OPEN":
            appeal["status"] = "DECIDED"
            appeal["outcome"] = "UPHELD"
            touch(appeal)

    app["status"] = "WITHDRAWN"
    touch(app)
    write_audit(app_id, "APPLICATION_WITHDRAWN", "Application withdrawn")
    return ok_object(serialize(app), 200)


# --- helpers ------------------------------------------------------------------
def _active_ktn_for_application(application_id: str):
    for k in db.known_traveler_numbers.values():
        if k.get("application_id") == application_id and k.get("status") == "ACTIVE":
            return k
    return None


def _timedelta_days(days: int):
    from datetime import timedelta
    return timedelta(days=days)
