"""Private Adoption Agency API — Flask entry point.

All routes, the global error handler, and request-level locking live here. The
store (db.py) starts EMPTY on every boot: no seeding, no preload, no hardcoded
entities.

Validation precedence per PRD §3.9 (applied per endpoint, in this order):
  user-context -> role -> pagination -> path-not-found -> body-FK-not-found ->
  invalid-request -> invalid-state -> SoD -> prerequisite -> home-study-expired
  -> consent-too-early -> revocation-window -> visit-window -> visits-incomplete
  -> overlap/buffer -> icpc-applicability -> insufficient-escrow -> stale-version
"""
import os

from flask import Flask, request

import db
import errors
import helpers
import middleware
import models
from calculations import agency_fee_total
from response import success, error
from timeutil import parse_iso, format_iso, add_days, add_hours, business_days_deadline
from validation import (
    get_body,
    require_string,
    require_int,
    require_enum,
    require_datetime,
    optional_string,
)

app = Flask(__name__)


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error(errors.ERR_NOT_FOUND, "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error(errors.ERR_NOT_FOUND, "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return error(e.error_id, e.message, e.http_status)
    return error(errors.ERR_INVALID_REQUEST, "Unexpected error: %s" % str(e), 400)


# Serialize all request handling through the global store lock so that cascades
# and OCC checks are atomic.
@app.before_request
def _acquire_lock():
    db.lock.acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        db.lock.release()
    except RuntimeError:
        pass


# --------------------------------------------------------------------------
# Constants reused below
# --------------------------------------------------------------------------
PARENT_ROLES = {"BIRTH_MOTHER", "BIRTH_FATHER", "LEGAL_GUARDIAN"}
EXPENSE_CATEGORIES = {"MEDICAL", "LEGAL", "LIVING", "COUNSELING", "TRAVEL", "OTHER"}
REVOCATION_BASES = {"CALENDAR_DAYS", "BUSINESS_DAYS"}
TXN_TYPES = {"DEPOSIT", "DISBURSEMENT", "REFUND"}

ALL_ROLES = ["AgencyAdmin", "Supervisor", "Caseworker", "FinanceOfficer", "CompactAdministrator"]


def _check_state(rec, allowed_states):
    """Priority 7: ERR_INVALID_STATE if the resource isn't in an allowed state."""
    if rec["status"] not in allowed_states:
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Resource is not in a state from which this transition is defined.")


# ==========================================================================
# Agency
# ==========================================================================
@app.route("/agencies", methods=["POST"])
def create_agency():
    _, role = middleware.require_user()
    middleware.require_role(role, ["AgencyAdmin"])
    body = get_body(request)
    name = require_string(body, "name")
    licensed_state = require_string(body, "licensed_state")
    fee_schedule_cents = require_int(body, "fee_schedule_cents", minimum=0)

    rec = models.base_fields()
    rec["name"] = name
    rec["licensed_state"] = licensed_state
    rec["fee_schedule_cents"] = fee_schedule_cents
    rec["_current_utc"] = parse_iso(rec["created_at"])
    db.agencies[rec["id"]] = rec
    return success(models.serialize_agency(rec), status=201)


@app.route("/agencies/<rid>", methods=["GET"])
def get_agency(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ALL_ROLES)
    rec = helpers.get_path(db.agencies, rid)
    return success(models.serialize_agency(rec))


@app.route("/agencies", methods=["GET"])
def list_agencies():
    _, role = middleware.require_user()
    middleware.require_role(role, ["AgencyAdmin"])
    limit, offset = helpers.parse_pagination()
    page, pg = helpers.paginate(list(db.agencies.values()), limit, offset)
    return success([models.serialize_agency(a) for a in page], pagination=pg)


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = middleware.require_user()
    middleware.require_role(role, ["AgencyAdmin"])
    body = get_body(request)
    agency_id = require_string(body, "agency_id")
    to_iso = require_datetime(body, "to_iso8601")
    agency = helpers.get_path(db.agencies, agency_id)
    agency["_current_utc"] = to_iso
    models.touch(agency)
    return success(models.serialize_agency(agency))


# ==========================================================================
# AdoptionCase
# ==========================================================================
@app.route("/cases", methods=["POST"])
def create_case():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor"])
    body = get_body(request)
    agency_id = require_string(body, "agency_id")
    case_label = require_string(body, "case_label")
    child_state = require_string(body, "child_state")
    family_state = require_string(body, "family_state")
    helpers.resolve_fk(db.agencies, agency_id)

    rec = models.base_fields()
    rec["agency_id"] = agency_id
    rec["case_label"] = case_label
    rec["child_state"] = child_state
    rec["family_state"] = family_state
    rec["interstate"] = child_state != family_state
    rec["phase"] = "INTAKE"
    rec["escrow_balance_cents"] = 0
    rec["reimbursable_expense_cents"] = 0
    db.cases[rec["id"]] = rec
    return success(models.serialize_case(rec), status=201)


@app.route("/cases/<rid>", methods=["GET"])
def get_case(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker", "FinanceOfficer", "CompactAdministrator"])
    rec = helpers.get_path(db.cases, rid)
    return success(models.serialize_case(rec))


@app.route("/cases", methods=["GET"])
def list_cases():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker", "FinanceOfficer"])
    limit, offset = helpers.parse_pagination()
    rows = list(db.cases.values())
    agency_id = request.args.get("agency_id")
    if agency_id is not None:
        rows = [c for c in rows if c["agency_id"] == agency_id]
    page, pg = helpers.paginate(rows, limit, offset)
    return success([models.serialize_case(c) for c in page], pagination=pg)


# ==========================================================================
# AdoptiveFamily
# ==========================================================================
@app.route("/families", methods=["POST"])
def create_family():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    body = get_body(request)
    case_id = require_string(body, "case_id")
    primary_applicant_name = require_string(body, "primary_applicant_name")
    residence_state = require_string(body, "residence_state")
    household_size = require_int(body, "household_size", minimum=1)
    annual_income_cents = require_int(body, "annual_income_cents", minimum=0)
    helpers.resolve_fk(db.cases, case_id)

    rec = models.base_fields()
    rec["case_id"] = case_id
    rec["primary_applicant_name"] = primary_applicant_name
    rec["residence_state"] = residence_state
    rec["household_size"] = household_size
    rec["annual_income_cents"] = annual_income_cents
    db.families[rec["id"]] = rec
    return success(models.serialize_family(rec), status=201)


@app.route("/families/<rid>", methods=["GET"])
def get_family(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker", "FinanceOfficer"])
    rec = helpers.get_path(db.families, rid)
    return success(models.serialize_family(rec))


@app.route("/families", methods=["GET"])
def list_families():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker"])
    limit, offset = helpers.parse_pagination()
    rows = list(db.families.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        rows = [f for f in rows if f["case_id"] == case_id]
    page, pg = helpers.paginate(rows, limit, offset)
    return success([models.serialize_family(f) for f in page], pagination=pg)


# ==========================================================================
# HomeStudy
# ==========================================================================
@app.route("/home-studies", methods=["POST"])
def create_home_study():
    user_id, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    body = get_body(request)
    case_id = require_string(body, "case_id")
    family_id = require_string(body, "family_id")
    helpers.resolve_fk(db.cases, case_id)
    helpers.resolve_fk(db.families, family_id)

    rec = models.base_fields()
    rec["case_id"] = case_id
    rec["family_id"] = family_id
    rec["authoring_caseworker_id"] = user_id
    rec["approving_supervisor_id"] = None
    rec["_completed_at"] = None
    rec["_expires_at"] = None
    rec["revision_count"] = 0
    rec["status"] = "DRAFT"
    db.home_studies[rec["id"]] = rec
    return success(models.serialize_home_study(rec), status=201)


@app.route("/home-studies/<rid>", methods=["GET"])
def get_home_study(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker"])
    rec = helpers.get_path(db.home_studies, rid)
    return success(models.serialize_home_study(rec))


@app.route("/home-studies", methods=["GET"])
def list_home_studies():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker"])
    limit, offset = helpers.parse_pagination()
    rows = list(db.home_studies.values())
    case_id = request.args.get("case_id")
    family_id = request.args.get("family_id")
    if case_id is not None:
        rows = [h for h in rows if h["case_id"] == case_id]
    if family_id is not None:
        rows = [h for h in rows if h["family_id"] == family_id]
    page, pg = helpers.paginate(rows, limit, offset)
    return success([models.serialize_home_study(h) for h in page], pagination=pg)


@app.route("/home-studies/<rid>/submit", methods=["POST"])
def submit_home_study(rid):
    user_id, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    rec = helpers.get_path(db.home_studies, rid)
    _check_state(rec, ["DRAFT", "RESUBMITTED"])
    # author check is part of the defined transition (acting == authoring)
    if user_id != rec["authoring_caseworker_id"]:
        raise errors.err(errors.ERR_UNAUTHORIZED, "Only the authoring caseworker may submit.")
    rec["status"] = "UNDER_REVIEW"
    models.touch(rec)
    return success(models.serialize_home_study(rec))


@app.route("/home-studies/<rid>/approve", methods=["POST"])
def approve_home_study(rid):
    user_id, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor"])
    rec = helpers.get_path(db.home_studies, rid)
    _check_state(rec, ["UNDER_REVIEW"])
    if user_id == rec["authoring_caseworker_id"]:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES,
                         "Approver must differ from the authoring caseworker.")
    case = db.cases.get(rec["case_id"])
    clock = models.agency_clock_for_case(case) if case else None
    rec["status"] = "APPROVED"
    rec["approving_supervisor_id"] = user_id
    rec["_completed_at"] = clock
    rec["_expires_at"] = add_days(clock, models.HOME_STUDY_VALIDITY_DAYS) if clock else None
    models.touch(rec)
    if case is not None:
        models.reconcile_case_mut(case)
    return success(models.serialize_home_study(rec))


@app.route("/home-studies/<rid>/return", methods=["POST"])
def return_home_study(rid):
    user_id, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor"])
    rec = helpers.get_path(db.home_studies, rid)
    _check_state(rec, ["UNDER_REVIEW"])
    if user_id == rec["authoring_caseworker_id"]:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES,
                         "Returner must differ from the authoring caseworker.")
    rec["status"] = "DEFICIENT"
    rec["revision_count"] += 1
    models.touch(rec)
    return success(models.serialize_home_study(rec))


@app.route("/home-studies/<rid>/resubmit", methods=["POST"])
def resubmit_home_study(rid):
    user_id, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    rec = helpers.get_path(db.home_studies, rid)
    _check_state(rec, ["DEFICIENT"])
    if user_id != rec["authoring_caseworker_id"]:
        raise errors.err(errors.ERR_UNAUTHORIZED, "Only the authoring caseworker may resubmit.")
    rec["status"] = "RESUBMITTED"
    models.touch(rec)
    return success(models.serialize_home_study(rec))


@app.route("/home-studies/<rid>/check-expiry", methods=["POST"])
def check_expiry_home_study(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["AgencyAdmin"])
    rec = helpers.get_path(db.home_studies, rid)
    _check_state(rec, ["APPROVED"])
    case = db.cases.get(rec["case_id"])
    clock = models.agency_clock_for_case(case) if case else None
    # precondition: agency.current_utc >= expires_at
    if clock is None or rec["_expires_at"] is None or clock < rec["_expires_at"]:
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Home study has not yet reached its expiry instant.")
    rec["status"] = "EXPIRED"
    models.touch(rec)
    if case is not None:
        models.reconcile_case_mut(case)
    return success(models.serialize_home_study(rec))


# ==========================================================================
# BirthParent
# ==========================================================================
@app.route("/birth-parents", methods=["POST"])
def create_birth_parent():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    body = get_body(request)
    agency_id = require_string(body, "agency_id")
    legal_name = require_string(body, "legal_name")
    birth_state = require_string(body, "birth_state")
    parent_role = require_enum(body, "parent_role", PARENT_ROLES)
    helpers.resolve_fk(db.agencies, agency_id)

    rec = models.base_fields()
    rec["agency_id"] = agency_id
    rec["legal_name"] = legal_name
    rec["birth_state"] = birth_state
    rec["parent_role"] = parent_role
    db.birth_parents[rec["id"]] = rec
    return success(models.serialize_birth_parent(rec), status=201)


@app.route("/birth-parents/<rid>", methods=["GET"])
def get_birth_parent(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker"])
    rec = helpers.get_path(db.birth_parents, rid)
    return success(models.serialize_birth_parent(rec))


@app.route("/birth-parents", methods=["GET"])
def list_birth_parents():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker"])
    limit, offset = helpers.parse_pagination()
    rows = list(db.birth_parents.values())
    agency_id = request.args.get("agency_id")
    if agency_id is not None:
        rows = [b for b in rows if b["agency_id"] == agency_id]
    page, pg = helpers.paginate(rows, limit, offset)
    return success([models.serialize_birth_parent(b) for b in page], pagination=pg)


# ==========================================================================
# CounselingSession
# ==========================================================================
@app.route("/counseling-sessions", methods=["POST"])
def create_counseling_session():
    user_id, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    body = get_body(request)
    birth_parent_id = require_string(body, "birth_parent_id")
    case_id = require_string(body, "case_id")
    start_at = require_datetime(body, "start_at")
    end_at = require_datetime(body, "end_at")
    helpers.resolve_fk(db.birth_parents, birth_parent_id)
    helpers.resolve_fk(db.cases, case_id)

    # ordering + buffered-closed overlap (priority 16: ERR_SESSION_BUFFER_CONFLICT)
    if not (start_at < end_at):
        raise errors.err(errors.ERR_SESSION_BUFFER_CONFLICT,
                         "start_at must be strictly before end_at.")
    buffer = models.COUNSELING_BUFFER_MINUTES
    for s in db.counseling_sessions.values():
        if s["birth_parent_id"] != birth_parent_id:
            continue
        if s["status"] == "CANCELLED":
            continue
        e_start = s["_start_at"]
        e_end = s["_end_at"]
        # conflict iff C.start < E.end + BUFFER AND E.start < C.end + BUFFER
        if start_at < add_minutes(e_end, buffer) and e_start < add_minutes(end_at, buffer):
            raise errors.err(errors.ERR_SESSION_BUFFER_CONFLICT,
                             "Session falls within the buffer of an existing session.")

    rec = models.base_fields()
    rec["birth_parent_id"] = birth_parent_id
    rec["case_id"] = case_id
    rec["counselor_id"] = user_id
    rec["_start_at"] = start_at
    rec["_end_at"] = end_at
    rec["status"] = "BOOKED"
    db.counseling_sessions[rec["id"]] = rec
    return success(models.serialize_counseling_session(rec), status=201)


def add_minutes(dt, minutes):
    from datetime import timedelta
    return dt + timedelta(minutes=minutes)


@app.route("/counseling-sessions/<rid>", methods=["GET"])
def get_counseling_session(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker"])
    rec = helpers.get_path(db.counseling_sessions, rid)
    return success(models.serialize_counseling_session(rec))


@app.route("/counseling-sessions", methods=["GET"])
def list_counseling_sessions():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker"])
    limit, offset = helpers.parse_pagination()
    rows = list(db.counseling_sessions.values())
    bp = request.args.get("birth_parent_id")
    case_id = request.args.get("case_id")
    if bp is not None:
        rows = [s for s in rows if s["birth_parent_id"] == bp]
    if case_id is not None:
        rows = [s for s in rows if s["case_id"] == case_id]
    page, pg = helpers.paginate(rows, limit, offset)
    return success([models.serialize_counseling_session(s) for s in page], pagination=pg)


@app.route("/counseling-sessions/<rid>/hold", methods=["POST"])
def hold_counseling_session(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    rec = helpers.get_path(db.counseling_sessions, rid)
    _check_state(rec, ["BOOKED"])
    case = db.cases.get(rec["case_id"])
    clock = models.agency_clock_for_case(case) if case else None
    if clock is None or clock < rec["_start_at"]:
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Session cannot be held before its start instant.")
    rec["status"] = "HELD"
    models.touch(rec)
    return success(models.serialize_counseling_session(rec))


@app.route("/counseling-sessions/<rid>/cancel", methods=["POST"])
def cancel_counseling_session(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    rec = helpers.get_path(db.counseling_sessions, rid)
    _check_state(rec, ["BOOKED"])
    rec["status"] = "CANCELLED"
    models.touch(rec)
    return success(models.serialize_counseling_session(rec))


# ==========================================================================
# Match
# ==========================================================================
@app.route("/matches", methods=["POST"])
def create_match():
    user_id, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    body = get_body(request)
    case_id = require_string(body, "case_id")
    family_id = require_string(body, "family_id")
    birth_parent_id = require_string(body, "birth_parent_id")
    helpers.resolve_fk(db.cases, case_id)
    helpers.resolve_fk(db.families, family_id)
    helpers.resolve_fk(db.birth_parents, birth_parent_id)

    rec = models.base_fields()
    rec["case_id"] = case_id
    rec["family_id"] = family_id
    rec["birth_parent_id"] = birth_parent_id
    rec["proposed_by_caseworker_id"] = user_id
    rec["status"] = "PROPOSED"
    db.matches[rec["id"]] = rec
    return success(models.serialize_match(rec), status=201)


@app.route("/matches/<rid>", methods=["GET"])
def get_match(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker"])
    rec = helpers.get_path(db.matches, rid)
    return success(models.serialize_match(rec))


@app.route("/matches", methods=["GET"])
def list_matches():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker"])
    limit, offset = helpers.parse_pagination()
    rows = list(db.matches.values())
    case_id = request.args.get("case_id")
    bp = request.args.get("birth_parent_id")
    family_id = request.args.get("family_id")
    if case_id is not None:
        rows = [m for m in rows if m["case_id"] == case_id]
    if bp is not None:
        rows = [m for m in rows if m["birth_parent_id"] == bp]
    if family_id is not None:
        rows = [m for m in rows if m["family_id"] == family_id]
    page, pg = helpers.paginate(rows, limit, offset)
    return success([models.serialize_match(m) for m in page], pagination=pg)


def _case_approved_homestudy_check(case):
    """Cross-entity gate for match-accept / placement-activate (priorities 9, 10).

    Order: APPROVED-state prerequisite first (ERR_PREREQUISITE_NOT_MET), then the
    expiry check (ERR_HOME_STUDY_EXPIRED).
    """
    studies = models.case_home_studies(case["id"])
    approved = [h for h in studies if h["status"] == "APPROVED"]
    if not approved:
        raise errors.err(errors.ERR_PREREQUISITE_NOT_MET,
                         "Case requires an APPROVED home study.")
    clock = models.agency_clock_for_case(case)
    # usable iff clock < expires_at; if every approved study is expired -> EXPIRED
    usable = [h for h in approved
              if h["_expires_at"] is not None and clock is not None and clock < h["_expires_at"]]
    if not usable:
        raise errors.err(errors.ERR_HOME_STUDY_EXPIRED,
                         "The approved home study has expired.")


@app.route("/matches/<rid>/accept", methods=["POST"])
def accept_match(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor"])
    rec = helpers.get_path(db.matches, rid)
    _check_state(rec, ["PROPOSED"])
    case = db.cases.get(rec["case_id"])
    _case_approved_homestudy_check(case)
    rec["status"] = "ACCEPTED"
    models.touch(rec)
    if case is not None:
        models.reconcile_case_mut(case)
    return success(models.serialize_match(rec))


@app.route("/matches/<rid>/decline", methods=["POST"])
def decline_match(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor"])
    rec = helpers.get_path(db.matches, rid)
    _check_state(rec, ["PROPOSED"])
    rec["status"] = "DECLINED"
    models.touch(rec)
    return success(models.serialize_match(rec))


@app.route("/matches/<rid>/dissolve", methods=["POST"])
def dissolve_match(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor"])
    rec = helpers.get_path(db.matches, rid)
    _check_state(rec, ["ACCEPTED"])
    case = db.cases.get(rec["case_id"])
    if case is not None and any(c["status"] == "IRREVOCABLE"
                                for c in models.case_consents(case["id"])):
        raise errors.err(errors.ERR_PREREQUISITE_NOT_MET,
                         "Cannot dissolve a match with an IRREVOCABLE consent on the case.")
    rec["status"] = "DISSOLVED"
    models.touch(rec)
    if case is not None:
        models.reconcile_case_mut(case)
    return success(models.serialize_match(rec))


# ==========================================================================
# ConsentRecord
# ==========================================================================
@app.route("/consent-records", methods=["POST"])
def create_consent_record():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    body = get_body(request)
    case_id = require_string(body, "case_id")
    birth_parent_id = require_string(body, "birth_parent_id")
    child_dob = require_datetime(body, "child_dob")
    revocation_basis = require_enum(body, "revocation_basis", REVOCATION_BASES)
    expected_case_version = require_int(body, "expected_case_version")
    supersedes_consent_id = optional_string(body, "supersedes_consent_id")

    case = helpers.resolve_fk(db.cases, case_id)
    helpers.resolve_fk(db.birth_parents, birth_parent_id)
    if supersedes_consent_id is not None:
        helpers.resolve_fk(db.consent_records, supersedes_consent_id)

    # OCC check (priority 19) — last, after structural validation.
    if expected_case_version != case["version"]:
        raise errors.err(errors.ERR_STALE_CASE_VERSION,
                         "expected_case_version does not match the case's current version.")

    rec = models.base_fields()
    rec["case_id"] = case_id
    rec["birth_parent_id"] = birth_parent_id
    rec["supersedes_consent_id"] = supersedes_consent_id
    rec["_child_dob"] = child_dob
    rec["_signed_at"] = None
    rec["_revocation_deadline"] = None
    rec["revocation_basis"] = revocation_basis
    rec["status"] = "PENDING"
    db.consent_records[rec["id"]] = rec

    # successful create bumps the case version
    models.reconcile_case_mut(case)
    return success(models.serialize_consent(rec), status=201)


@app.route("/consent-records/<rid>", methods=["GET"])
def get_consent_record(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker"])
    rec = helpers.get_path(db.consent_records, rid)
    return success(models.serialize_consent(rec))


@app.route("/consent-records", methods=["GET"])
def list_consent_records():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker"])
    limit, offset = helpers.parse_pagination()
    rows = list(db.consent_records.values())
    case_id = request.args.get("case_id")
    bp = request.args.get("birth_parent_id")
    sup = request.args.get("supersedes_consent_id")
    if case_id is not None:
        rows = [c for c in rows if c["case_id"] == case_id]
    if bp is not None:
        rows = [c for c in rows if c["birth_parent_id"] == bp]
    if sup is not None:
        rows = [c for c in rows if c["supersedes_consent_id"] == sup]
    page, pg = helpers.paginate(rows, limit, offset)
    return success([models.serialize_consent(c) for c in page], pagination=pg)


@app.route("/consent-records/<rid>/sign", methods=["POST"])
def sign_consent(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    rec = helpers.get_path(db.consent_records, rid)
    _check_state(rec, ["PENDING"])
    case = db.cases.get(rec["case_id"])
    # prerequisite: case has an ACCEPTED match (priority 9)
    if case is None or not any(m["status"] == "ACCEPTED" for m in models.case_matches(case["id"])):
        raise errors.err(errors.ERR_PREREQUISITE_NOT_MET,
                         "Signing requires an ACCEPTED match on the case.")
    # consent-too-early (priority 11): clock >= child_dob + MIN_HOURS_AFTER_BIRTH
    clock = models.agency_clock_for_case(case)
    earliest = add_hours(rec["_child_dob"], models.MIN_HOURS_AFTER_BIRTH)
    if clock is None or clock < earliest:
        raise errors.err(errors.ERR_CONSENT_TOO_EARLY,
                         "Consent cannot be signed before 72 hours after birth.")
    rec["status"] = "SIGNED"
    rec["_signed_at"] = clock
    rec["_revocation_deadline"] = _compute_revocation_deadline(clock, rec["revocation_basis"])
    models.touch(rec)
    return success(models.serialize_consent(rec))


def _compute_revocation_deadline(signed_at, basis):
    if basis == "CALENDAR_DAYS":
        return add_days(signed_at, models.CALENDAR_WINDOW_DAYS)
    # BUSINESS_DAYS
    return business_days_deadline(signed_at, models.BUSINESS_WINDOW_DAYS)


@app.route("/consent-records/<rid>/revoke", methods=["POST"])
def revoke_consent(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    rec = helpers.get_path(db.consent_records, rid)
    _check_state(rec, ["SIGNED"])
    case = db.cases.get(rec["case_id"])
    clock = models.agency_clock_for_case(case) if case else None
    # revocation-window (priority 12): clock <= deadline is OK; strictly after -> closed
    if clock is None or rec["_revocation_deadline"] is None or clock > rec["_revocation_deadline"]:
        raise errors.err(errors.ERR_REVOCATION_WINDOW_CLOSED,
                         "Revocation window has closed.")
    rec["status"] = "REVOKED"
    models.touch(rec)
    # cascade hop 1: disrupt any PENDING/ACTIVE placement for the case
    if case is not None:
        for p in models.case_placements(case["id"]):
            if p["status"] in ("PENDING", "ACTIVE"):
                p["status"] = "DISRUPTED"
                models.touch(p)
                # cascade hop 2: SCHEDULED visits -> MISSED
                for v in models.placement_visits(p["id"]):
                    if v["status"] == "SCHEDULED":
                        v["status"] = "MISSED"
                        models.touch(v)
        models.reconcile_case_mut(case)
    return success(models.serialize_consent(rec))


@app.route("/consent-records/<rid>/finalize-consent", methods=["POST"])
def finalize_consent(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["AgencyAdmin"])
    rec = helpers.get_path(db.consent_records, rid)
    _check_state(rec, ["SIGNED"])
    case = db.cases.get(rec["case_id"])
    clock = models.agency_clock_for_case(case) if case else None
    # precondition: clock > revocation_deadline (strictly after)
    if clock is None or rec["_revocation_deadline"] is None or clock <= rec["_revocation_deadline"]:
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Consent cannot be made irrevocable before its revocation deadline passes.")
    rec["status"] = "IRREVOCABLE"
    models.touch(rec)
    if case is not None:
        models.reconcile_case_mut(case)
    return success(models.serialize_consent(rec))


# ==========================================================================
# IcpcClearance
# ==========================================================================
@app.route("/icpc-clearances", methods=["POST"])
def create_icpc():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    body = get_body(request)
    case_id = require_string(body, "case_id")
    case = helpers.resolve_fk(db.cases, case_id)

    interstate = case["child_state"] != case["family_state"]
    rec = models.base_fields()
    rec["case_id"] = case_id
    rec["sending_state"] = case["child_state"]
    rec["receiving_state"] = case["family_state"]
    rec["_submitted_at"] = None
    rec["status"] = "DRAFT" if interstate else "NOT_REQUIRED"
    db.icpc_clearances[rec["id"]] = rec
    return success(models.serialize_icpc(rec), status=201)


@app.route("/icpc-clearances/<rid>", methods=["GET"])
def get_icpc(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker", "CompactAdministrator"])
    rec = helpers.get_path(db.icpc_clearances, rid)
    return success(models.serialize_icpc(rec))


@app.route("/icpc-clearances", methods=["GET"])
def list_icpc():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker", "CompactAdministrator"])
    limit, offset = helpers.parse_pagination()
    rows = list(db.icpc_clearances.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        rows = [i for i in rows if i["case_id"] == case_id]
    page, pg = helpers.paginate(rows, limit, offset)
    return success([models.serialize_icpc(i) for i in page], pagination=pg)


@app.route("/icpc-clearances/<rid>/submit", methods=["POST"])
def submit_icpc(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    rec = helpers.get_path(db.icpc_clearances, rid)
    _check_state(rec, ["DRAFT"])
    case = db.cases.get(rec["case_id"])
    # prerequisite: ACCEPTED match (priority 9) BEFORE icpc-applicability (priority 17)
    if case is None or not any(m["status"] == "ACCEPTED" for m in models.case_matches(case["id"])):
        raise errors.err(errors.ERR_PREREQUISITE_NOT_MET,
                         "ICPC submit requires an ACCEPTED match on the case.")
    interstate = case["child_state"] != case["family_state"]
    if not interstate:
        raise errors.err(errors.ERR_ICPC_NOT_APPLICABLE,
                         "ICPC clearance does not apply to an in-state case.")
    clock = models.agency_clock_for_case(case)
    rec["status"] = "SUBMITTED"
    rec["_submitted_at"] = clock
    models.touch(rec)
    return success(models.serialize_icpc(rec))


@app.route("/icpc-clearances/<rid>/approve-sending", methods=["POST"])
def approve_sending_icpc(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["CompactAdministrator"])
    rec = helpers.get_path(db.icpc_clearances, rid)
    _check_state(rec, ["SUBMITTED"])
    rec["status"] = "SENDING_APPROVED"
    models.touch(rec)
    return success(models.serialize_icpc(rec))


@app.route("/icpc-clearances/<rid>/approve-receiving", methods=["POST"])
def approve_receiving_icpc(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["CompactAdministrator"])
    rec = helpers.get_path(db.icpc_clearances, rid)
    _check_state(rec, ["SENDING_APPROVED"])
    rec["status"] = "RECEIVING_APPROVED"
    models.touch(rec)
    case = db.cases.get(rec["case_id"])
    if case is not None:
        models.reconcile_case_mut(case)
    return success(models.serialize_icpc(rec))


@app.route("/icpc-clearances/<rid>/reject", methods=["POST"])
def reject_icpc(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["CompactAdministrator"])
    rec = helpers.get_path(db.icpc_clearances, rid)
    _check_state(rec, ["SUBMITTED", "SENDING_APPROVED"])
    rec["status"] = "REJECTED"
    models.touch(rec)
    return success(models.serialize_icpc(rec))


@app.route("/icpc-clearances/<rid>/rework", methods=["POST"])
def rework_icpc(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    rec = helpers.get_path(db.icpc_clearances, rid)
    _check_state(rec, ["REJECTED"])
    rec["status"] = "DRAFT"
    rec["_submitted_at"] = None
    models.touch(rec)
    return success(models.serialize_icpc(rec))


# ==========================================================================
# Placement
# ==========================================================================
@app.route("/placements", methods=["POST"])
def create_placement():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor"])
    body = get_body(request)
    case_id = require_string(body, "case_id")
    family_id = require_string(body, "family_id")
    case = helpers.resolve_fk(db.cases, case_id)
    helpers.resolve_fk(db.families, family_id)

    interstate = case["child_state"] != case["family_state"]
    rec = models.base_fields()
    rec["case_id"] = case_id
    rec["family_id"] = family_id
    rec["required_visits"] = (models.REQUIRED_VISITS_INTERSTATE
                              if interstate else models.REQUIRED_VISITS_INSTATE)
    rec["completed_visit_count"] = 0
    rec["_placed_at"] = None
    rec["_finalized_at"] = None
    rec["status"] = "PENDING"
    db.placements[rec["id"]] = rec
    return success(models.serialize_placement(rec), status=201)


@app.route("/placements/<rid>", methods=["GET"])
def get_placement(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker"])
    rec = helpers.get_path(db.placements, rid)
    return success(models.serialize_placement(rec))


@app.route("/placements", methods=["GET"])
def list_placements():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker"])
    limit, offset = helpers.parse_pagination()
    rows = list(db.placements.values())
    case_id = request.args.get("case_id")
    family_id = request.args.get("family_id")
    if case_id is not None:
        rows = [p for p in rows if p["case_id"] == case_id]
    if family_id is not None:
        rows = [p for p in rows if p["family_id"] == family_id]
    page, pg = helpers.paginate(rows, limit, offset)
    return success([models.serialize_placement(p) for p in page], pagination=pg)


@app.route("/placements/<rid>/activate", methods=["POST"])
def activate_placement(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor"])
    rec = helpers.get_path(db.placements, rid)
    _check_state(rec, ["PENDING"])
    case = db.cases.get(rec["case_id"])
    interstate = case["child_state"] != case["family_state"] if case else False

    # prerequisite gates (priority 9): consent IRREVOCABLE, ICPC if interstate
    consents = models.case_consents(case["id"]) if case else []
    if not any(c["status"] == "IRREVOCABLE" for c in consents):
        raise errors.err(errors.ERR_PREREQUISITE_NOT_MET,
                         "Activation requires an IRREVOCABLE consent on the case.")
    if interstate:
        icpcs = models.case_icpc(case["id"])
        if not any(i["status"] == "RECEIVING_APPROVED" for i in icpcs):
            raise errors.err(errors.ERR_PREREQUISITE_NOT_MET,
                             "Interstate case requires a RECEIVING_APPROVED ICPC clearance.")
    # home study APPROVED prerequisite then expiry (priorities 9, 10)
    _case_approved_homestudy_check(case)

    clock = models.agency_clock_for_case(case)
    rec["status"] = "ACTIVE"
    rec["_placed_at"] = clock
    models.recompute_placement(rec)
    models.touch(rec)
    if case is not None:
        models.reconcile_case_mut(case)
    return success(models.serialize_placement(rec))


@app.route("/placements/<rid>/finalize", methods=["POST"])
def finalize_placement(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor"])
    rec = helpers.get_path(db.placements, rid)
    _check_state(rec, ["ACTIVE"])
    case = db.cases.get(rec["case_id"])
    models.recompute_placement(rec)
    # visits-incomplete (priority 14)
    if rec["completed_visit_count"] < rec["required_visits"]:
        raise errors.err(errors.ERR_VISITS_INCOMPLETE,
                         "Not enough completed post-placement visits to finalize.")
    # must have an ISSUED or PAID invoice (no VOID-blocking); treated as prerequisite
    invoices = [inv for inv in db.agency_fee_invoices.values()
                if case is not None and inv["case_id"] == case["id"]]
    if not any(inv["status"] in ("ISSUED", "PAID") for inv in invoices):
        raise errors.err(errors.ERR_PREREQUISITE_NOT_MET,
                         "Finalization requires an ISSUED or PAID agency fee invoice.")
    clock = models.agency_clock_for_case(case) if case else None
    rec["status"] = "FINALIZED"
    rec["_finalized_at"] = clock
    models.touch(rec)
    # cascade: every SIGNED consent for the case -> IRREVOCABLE
    if case is not None:
        for c in models.case_consents(case["id"]):
            if c["status"] == "SIGNED":
                c["status"] = "IRREVOCABLE"
                models.touch(c)
        models.reconcile_case_mut(case)
    return success(models.serialize_placement(rec))


@app.route("/placements/<rid>/disrupt", methods=["POST"])
def disrupt_placement(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor"])
    rec = helpers.get_path(db.placements, rid)
    _check_state(rec, ["ACTIVE"])
    rec["status"] = "DISRUPTED"
    models.touch(rec)
    # cascade: SCHEDULED visits -> MISSED
    for v in models.placement_visits(rec["id"]):
        if v["status"] == "SCHEDULED":
            v["status"] = "MISSED"
            models.touch(v)
    case = db.cases.get(rec["case_id"])
    if case is not None:
        models.reconcile_case_mut(case)
    return success(models.serialize_placement(rec))


# ==========================================================================
# PostPlacementVisit
# ==========================================================================
@app.route("/post-placement-visits", methods=["POST"])
def create_visit():
    user_id, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    body = get_body(request)
    case_id = require_string(body, "case_id")
    placement_id = require_string(body, "placement_id")
    window_start = require_datetime(body, "window_start")
    window_end = require_datetime(body, "window_end")
    helpers.resolve_fk(db.cases, case_id)
    helpers.resolve_fk(db.placements, placement_id)

    # ordering + half-open touching-allowed overlap (priority 15: ERR_VISIT_OVERLAP)
    if not (window_start < window_end):
        raise errors.err(errors.ERR_VISIT_OVERLAP,
                         "window_start must be strictly before window_end.")
    for v in db.post_placement_visits.values():
        if v["placement_id"] != placement_id:
            continue
        if v["status"] != "SCHEDULED":
            continue
        # overlap iff new.start < existing.end AND existing.start < new.end
        if window_start < v["_window_end"] and v["_window_start"] < window_end:
            raise errors.err(errors.ERR_VISIT_OVERLAP,
                             "Visit window overlaps an existing scheduled visit.")

    rec = models.base_fields()
    rec["case_id"] = case_id
    rec["placement_id"] = placement_id
    rec["visiting_caseworker_id"] = user_id
    rec["_window_start"] = window_start
    rec["_window_end"] = window_end
    rec["_conducted_at"] = None
    rec["status"] = "SCHEDULED"
    db.post_placement_visits[rec["id"]] = rec
    return success(models.serialize_visit(rec), status=201)


@app.route("/post-placement-visits/<rid>", methods=["GET"])
def get_visit(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker"])
    rec = helpers.get_path(db.post_placement_visits, rid)
    return success(models.serialize_visit(rec))


@app.route("/post-placement-visits", methods=["GET"])
def list_visits():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker"])
    limit, offset = helpers.parse_pagination()
    rows = list(db.post_placement_visits.values())
    case_id = request.args.get("case_id")
    placement_id = request.args.get("placement_id")
    if case_id is not None:
        rows = [v for v in rows if v["case_id"] == case_id]
    if placement_id is not None:
        rows = [v for v in rows if v["placement_id"] == placement_id]
    page, pg = helpers.paginate(rows, limit, offset)
    return success([models.serialize_visit(v) for v in page], pagination=pg)


@app.route("/post-placement-visits/<rid>/complete", methods=["POST"])
def complete_visit(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    rec = helpers.get_path(db.post_placement_visits, rid)
    _check_state(rec, ["SCHEDULED"])
    placement = db.placements.get(rec["placement_id"])
    # prerequisite (priority 9): placement ACTIVE
    if placement is None or placement["status"] != "ACTIVE":
        raise errors.err(errors.ERR_PREREQUISITE_NOT_MET,
                         "Visit completion requires an ACTIVE placement.")
    case = db.cases.get(rec["case_id"])
    clock = models.agency_clock_for_case(case) if case else None
    # visit-window (priority 13): window_start <= clock < window_end
    if clock is None or clock < rec["_window_start"] or clock >= rec["_window_end"]:
        raise errors.err(errors.ERR_VISIT_WINDOW_INVALID,
                         "Visit can only be completed within its half-open window.")
    rec["status"] = "COMPLETED"
    rec["_conducted_at"] = clock
    models.touch(rec)
    # recompute parent placement's completed_visit_count (derived) -> mutation
    models.recompute_placement(placement)
    models.touch(placement)
    return success(models.serialize_visit(rec))


@app.route("/post-placement-visits/<rid>/mark-missed", methods=["POST"])
def mark_missed_visit(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["AgencyAdmin"])
    rec = helpers.get_path(db.post_placement_visits, rid)
    _check_state(rec, ["SCHEDULED"])
    case = db.cases.get(rec["case_id"])
    clock = models.agency_clock_for_case(case) if case else None
    # precondition: clock >= window_end
    if clock is None or clock < rec["_window_end"]:
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Visit cannot be marked missed before its window closes.")
    rec["status"] = "MISSED"
    models.touch(rec)
    return success(models.serialize_visit(rec))


# ==========================================================================
# ExpenseEntry
# ==========================================================================
@app.route("/expense-entries", methods=["POST"])
def create_expense():
    user_id, role = middleware.require_user()
    middleware.require_role(role, ["Caseworker"])
    body = get_body(request)
    case_id = require_string(body, "case_id")
    category = require_enum(body, "category", EXPENSE_CATEGORIES)
    amount_cents = require_int(body, "amount_cents", exclusive_min=0)
    helpers.resolve_fk(db.cases, case_id)

    rec = models.base_fields()
    rec["case_id"] = case_id
    rec["logged_by_caseworker_id"] = user_id
    rec["approved_by_finance_id"] = None
    rec["category"] = category
    rec["amount_cents"] = amount_cents
    rec["status"] = "LOGGED"
    db.expense_entries[rec["id"]] = rec
    return success(models.serialize_expense(rec), status=201)


@app.route("/expense-entries/<rid>", methods=["GET"])
def get_expense(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker", "FinanceOfficer"])
    rec = helpers.get_path(db.expense_entries, rid)
    return success(models.serialize_expense(rec))


@app.route("/expense-entries", methods=["GET"])
def list_expenses():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "Caseworker", "FinanceOfficer"])
    limit, offset = helpers.parse_pagination()
    rows = list(db.expense_entries.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        rows = [e for e in rows if e["case_id"] == case_id]
    page, pg = helpers.paginate(rows, limit, offset)
    return success([models.serialize_expense(e) for e in page], pagination=pg)


@app.route("/expense-entries/<rid>/approve", methods=["POST"])
def approve_expense(rid):
    user_id, role = middleware.require_user()
    middleware.require_role(role, ["FinanceOfficer"])
    rec = helpers.get_path(db.expense_entries, rid)
    _check_state(rec, ["LOGGED"])
    # SoD (priority 8): approver != logger
    if user_id == rec["logged_by_caseworker_id"]:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES,
                         "Approver must differ from the caseworker who logged the expense.")
    rec["status"] = "APPROVED"
    rec["approved_by_finance_id"] = user_id
    models.touch(rec)
    case = db.cases.get(rec["case_id"])
    if case is not None:
        models.reconcile_case_mut(case)
    return success(models.serialize_expense(rec))


@app.route("/expense-entries/<rid>/reject", methods=["POST"])
def reject_expense(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["FinanceOfficer"])
    rec = helpers.get_path(db.expense_entries, rid)
    _check_state(rec, ["LOGGED"])
    rec["status"] = "REJECTED"
    models.touch(rec)
    return success(models.serialize_expense(rec))


@app.route("/expense-entries/<rid>/disburse", methods=["POST"])
def disburse_expense(rid):
    user_id, role = middleware.require_user()
    middleware.require_role(role, ["FinanceOfficer"])
    rec = helpers.get_path(db.expense_entries, rid)
    _check_state(rec, ["APPROVED"])
    case = db.cases.get(rec["case_id"])
    balance = models.compute_escrow_balance(case["id"]) if case else 0
    # insufficient-escrow (priority 18): balance >= amount
    if balance < rec["amount_cents"]:
        raise errors.err(errors.ERR_INSUFFICIENT_ESCROW,
                         "Escrow balance is insufficient to disburse this expense.")
    rec["status"] = "DISBURSED"
    models.touch(rec)
    # cascade hop 1: create DISBURSEMENT escrow txn tied to this expense
    txn = models.base_fields(with_version=False)
    txn["case_id"] = rec["case_id"]
    txn["expense_id"] = rec["id"]
    txn["txn_type"] = "DISBURSEMENT"
    txn["amount_cents"] = rec["amount_cents"]
    txn["recorded_by_finance_id"] = user_id
    db.escrow_transactions[txn["id"]] = txn
    # cascade hop 2: recompute case escrow balance (derived reconciliation)
    if case is not None:
        models.reconcile_case_mut(case)
    return success(models.serialize_expense(rec))


# ==========================================================================
# EscrowTransaction
# ==========================================================================
@app.route("/escrow-transactions", methods=["POST"])
def create_escrow_txn():
    user_id, role = middleware.require_user()
    middleware.require_role(role, ["FinanceOfficer"])
    body = get_body(request)
    case_id = require_string(body, "case_id")
    txn_type = require_enum(body, "txn_type", TXN_TYPES)
    amount_cents = require_int(body, "amount_cents", exclusive_min=0)
    expected_case_version = require_int(body, "expected_case_version")
    expense_id = optional_string(body, "expense_id")

    case = helpers.resolve_fk(db.cases, case_id)
    if expense_id is not None:
        helpers.resolve_fk(db.expense_entries, expense_id)

    # insufficient-escrow (priority 18) BEFORE OCC (priority 19)
    if txn_type in ("DISBURSEMENT", "REFUND"):
        balance = models.compute_escrow_balance(case_id)
        if balance < amount_cents:
            raise errors.err(errors.ERR_INSUFFICIENT_ESCROW,
                             "Transaction would drive the escrow balance negative.")

    # OCC (priority 19)
    if expected_case_version != case["version"]:
        raise errors.err(errors.ERR_STALE_CASE_VERSION,
                         "expected_case_version does not match the case's current version.")

    rec = models.base_fields(with_version=False)
    rec["case_id"] = case_id
    rec["expense_id"] = expense_id
    rec["txn_type"] = txn_type
    rec["amount_cents"] = amount_cents
    rec["recorded_by_finance_id"] = user_id
    db.escrow_transactions[rec["id"]] = rec
    # recompute case escrow balance + bump case version
    models.reconcile_case_mut(case)
    return success(models.serialize_escrow_txn(rec), status=201)


@app.route("/escrow-transactions/<rid>", methods=["GET"])
def get_escrow_txn(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "FinanceOfficer"])
    rec = helpers.get_path(db.escrow_transactions, rid)
    return success(models.serialize_escrow_txn(rec))


@app.route("/escrow-transactions", methods=["GET"])
def list_escrow_txns():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "FinanceOfficer"])
    limit, offset = helpers.parse_pagination()
    rows = list(db.escrow_transactions.values())
    case_id = request.args.get("case_id")
    expense_id = request.args.get("expense_id")
    if case_id is not None:
        rows = [t for t in rows if t["case_id"] == case_id]
    if expense_id is not None:
        rows = [t for t in rows if t["expense_id"] == expense_id]
    page, pg = helpers.paginate(rows, limit, offset)
    return success([models.serialize_escrow_txn(t) for t in page], pagination=pg)


# ==========================================================================
# AgencyFeeInvoice
# ==========================================================================
@app.route("/agency-fee-invoices", methods=["POST"])
def create_invoice():
    _, role = middleware.require_user()
    middleware.require_role(role, ["FinanceOfficer"])
    body = get_body(request)
    case_id = require_string(body, "case_id")
    case = helpers.resolve_fk(db.cases, case_id)

    agency = db.agencies.get(case["agency_id"])
    base = agency["fee_schedule_cents"] if agency else 0
    # family for this case (income feeds sliding scale)
    fams = [f for f in db.families.values() if f["case_id"] == case_id]
    income = fams[0]["annual_income_cents"] if fams else 0
    reimbursable = models.compute_reimbursable(case_id)
    pct, base_fee, total = agency_fee_total(base, income, reimbursable)

    rec = models.base_fields()
    rec["case_id"] = case_id
    rec["base_fee_cents"] = base_fee
    rec["sliding_scale_pct"] = pct
    rec["total_due_cents"] = total
    rec["status"] = "ISSUED"
    db.agency_fee_invoices[rec["id"]] = rec
    return success(models.serialize_invoice(rec), status=201)


@app.route("/agency-fee-invoices/<rid>", methods=["GET"])
def get_invoice(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "FinanceOfficer"])
    rec = helpers.get_path(db.agency_fee_invoices, rid)
    return success(models.serialize_invoice(rec))


@app.route("/agency-fee-invoices", methods=["GET"])
def list_invoices():
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor", "FinanceOfficer"])
    limit, offset = helpers.parse_pagination()
    rows = list(db.agency_fee_invoices.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        rows = [inv for inv in rows if inv["case_id"] == case_id]
    page, pg = helpers.paginate(rows, limit, offset)
    return success([models.serialize_invoice(inv) for inv in page], pagination=pg)


@app.route("/agency-fee-invoices/<rid>/pay", methods=["POST"])
def pay_invoice(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["FinanceOfficer"])
    rec = helpers.get_path(db.agency_fee_invoices, rid)
    _check_state(rec, ["ISSUED"])
    rec["status"] = "PAID"
    models.touch(rec)
    return success(models.serialize_invoice(rec))


@app.route("/agency-fee-invoices/<rid>/void", methods=["POST"])
def void_invoice(rid):
    _, role = middleware.require_user()
    middleware.require_role(role, ["Supervisor"])
    rec = helpers.get_path(db.agency_fee_invoices, rid)
    _check_state(rec, ["ISSUED"])
    case = db.cases.get(rec["case_id"])
    # cannot void if the case's placement is FINALIZED
    if case is not None and any(p["status"] == "FINALIZED"
                                for p in models.case_placements(case["id"])):
        raise errors.err(errors.ERR_PREREQUISITE_NOT_MET,
                         "Cannot void a fee invoice on a finalized case.")
    rec["status"] = "VOID"
    models.touch(rec)
    return success(models.serialize_invoice(rec))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
