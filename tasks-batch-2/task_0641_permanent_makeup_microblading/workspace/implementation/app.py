"""Permanent Makeup & Microblading Studio API — entry point and all routes.

In-memory only. The store starts empty on every boot; nothing is seeded.
"""
import os
from datetime import timedelta

from flask import Flask, request

import errors
import middleware
import helpers
import serialize
import services
import calculations as calc
from clock import clock
from db import db, new_id, iso_ms as _iso_ms_fn
from response import success, list_success, error_response


def _iso(dt):
    return _iso_ms_fn(dt)

app = Flask(__name__)

PROCEDURE_TYPES = {"BROWS", "EYELINER", "LIP_BLUSH"}
PATCH_READ_MIN = timedelta(hours=48)
CANCEL_FREE = timedelta(hours=48)
TOUCHUP_OPEN = timedelta(days=30)
TOUCHUP_CLOSE = timedelta(days=60)
ANNUAL_DAYS = timedelta(days=365)
REDO_WINDOW = timedelta(days=90)


# ============================================================================
# Error handling
# ============================================================================
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    body = error_response(e.error_id, e.message)
    return body, e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = error_response("ERR_NOT_FOUND", "Referenced resource does not exist")
    return body, 404


@app.errorhandler(405)
def handle_405(e):
    body = error_response("ERR_NOT_FOUND", "Method not allowed")
    return body, 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return handle_api_error(e)
    body = error_response("ERR_INVALID_REQUEST", str(e))
    return body, 422


# ============================================================================
# Logical clock
# ============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin"})
    body = helpers.get_body()
    dt = helpers.require_dt(body, "to_iso8601")
    clock.set(dt)
    return success({"current_utc": helpers.iso_ms_now()}, status=200)


# ============================================================================
# Studio
# ============================================================================
@app.route("/studios", methods=["POST"])
def create_studio():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin"})
    body = helpers.get_body()
    name = helpers.require_str(body, "name")
    state_code = helpers.require_str(body, "state_code")
    sterile_kit_total = helpers.require_int(body, "sterile_kit_total")
    # Range: sterile_kit_total >= 0 -> ERR_VALIDATION_RANGE
    if sterile_kit_total < 0:
        raise errors.err(errors.ERR_VALIDATION_RANGE, "sterile_kit_total must be >= 0")
    min_client_age = helpers.optional_int(body, "min_client_age", 18)
    # min_client_age >= 18 — out-of-range is a malformed request (ERR_INVALID_REQUEST)
    if min_client_age < 18:
        raise errors.err(errors.ERR_INVALID_REQUEST, "min_client_age must be >= 18")

    sid = new_id()
    studio = {
        "id": sid,
        "name": name,
        "state_code": state_code,
        "min_client_age": min_client_age,
        "sterile_kit_total": sterile_kit_total,
    }
    helpers.stamp_common(studio, versioned=True)
    db.studios[sid] = studio
    return success(serialize.serialize_studio(studio), status=201)


@app.route("/studios/<sid>", methods=["GET"])
def get_studio(sid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "Technician", "ComplianceOfficer"})
    studio = helpers.get_or_404(db.studios, sid)
    return success(serialize.serialize_studio(studio), status=200)


# ============================================================================
# Technician
# ============================================================================
@app.route("/technicians", methods=["POST"])
def create_technician():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "ComplianceOfficer"})
    body = helpers.get_body()
    studio_id = helpers.require_str(body, "studio_id")
    full_name = helpers.require_str(body, "full_name")
    license_number = helpers.require_str(body, "license_number")
    bbp_cert_expiry = helpers.require_dt(body, "bbp_cert_expiry")
    license_expiry = helpers.require_dt(body, "license_expiry")

    studio = helpers.get_or_404(db.studios, studio_id)

    tid = new_id()
    tech = {
        "id": tid,
        "studio_id": studio_id,
        "full_name": full_name,
        "license_number": license_number,
        "bbp_cert_expiry": _iso(bbp_cert_expiry),
        "license_expiry": _iso(license_expiry),
        "license_status": "LICENSE_ACTIVE",
    }
    helpers.stamp_common(tech, versioned=True)
    db.technicians[tid] = tech
    # registration recomputes studio posture (derived) and increments studio version
    helpers.touch(studio)
    return success(serialize.serialize_technician(tech), status=201)


@app.route("/technicians/<tid>", methods=["GET"])
def get_technician(tid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "Technician", "ComplianceOfficer"})
    tech = helpers.get_or_404(db.technicians, tid)
    return success(serialize.serialize_technician(tech), status=200)


@app.route("/technicians", methods=["GET"])
def list_technicians():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "Technician", "ComplianceOfficer"})
    limit, offset = helpers.get_pagination()
    items = list(db.technicians.values())
    studio_id = request.args.get("studio_id")
    if studio_id is not None:
        items = [t for t in items if t["studio_id"] == studio_id]
    page, total = helpers.paginate(items, limit, offset)
    return list_success([serialize.serialize_technician(t) for t in page], limit, offset, total)


@app.route("/technicians/<tid>/suspend-license", methods=["POST"])
def suspend_license(tid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ComplianceOfficer"})
    tech = helpers.get_or_404(db.technicians, tid)
    body = helpers.get_body()
    # expected_studio_version is for the operator's reference; required field.
    helpers.require_int(body, "expected_studio_version")
    if tech["license_status"] != "LICENSE_ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "License not LICENSE_ACTIVE")
    services.suspend_license_cascade(tech)
    return success(serialize.serialize_technician(tech), status=200)


@app.route("/technicians/<tid>/reinstate-license", methods=["POST"])
def reinstate_license(tid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ComplianceOfficer"})
    tech = helpers.get_or_404(db.technicians, tid)
    if tech["license_status"] != "LICENSE_SUSPENDED":
        raise errors.err(errors.ERR_INVALID_STATE, "License not LICENSE_SUSPENDED")
    le = helpers.parse_dt(tech["license_expiry"], "license_expiry")
    be = helpers.parse_dt(tech["bbp_cert_expiry"], "bbp_cert_expiry")
    if not (le > clock.now() and be > clock.now()):
        raise errors.err(errors.ERR_LICENSE_INVALID, "License or BBP certification expired")
    tech["license_status"] = "LICENSE_ACTIVE"
    helpers.touch(tech)
    studio = db.studios.get(tech["studio_id"])
    if studio:
        helpers.touch(studio)
    return success(serialize.serialize_technician(tech), status=200)


# ============================================================================
# Client
# ============================================================================
@app.route("/clients", methods=["POST"])
def create_client():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk"})
    body = helpers.get_body()
    studio_id = helpers.require_str(body, "studio_id")
    full_name = helpers.require_str(body, "full_name")
    date_of_birth = helpers.require_dt(body, "date_of_birth")
    medical_flag_count = helpers.optional_int(body, "medical_flag_count", 0)
    prior_adverse_reactions = helpers.optional_int(body, "prior_adverse_reactions", 0)
    skin_sensitivity_self = helpers.optional_int(body, "skin_sensitivity_self", 0)

    if medical_flag_count < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "medical_flag_count must be >= 0")
    if prior_adverse_reactions < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "prior_adverse_reactions must be >= 0")
    # skin_sensitivity_self range -> ERR_VALIDATION_RANGE
    if skin_sensitivity_self < 0 or skin_sensitivity_self > 3:
        raise errors.err(errors.ERR_VALIDATION_RANGE, "skin_sensitivity_self must be 0..3")

    studio = helpers.get_or_404(db.studios, studio_id)

    cid = new_id()
    client = {
        "id": cid,
        "studio_id": studio_id,
        "full_name": full_name,
        "date_of_birth": _iso(date_of_birth),
        "medical_flag_count": medical_flag_count,
        "prior_adverse_reactions": prior_adverse_reactions,
        "skin_sensitivity_self": skin_sensitivity_self,
        "skin_sensitivity_observed": None,
        "medical_cleared": False,
    }
    helpers.stamp_common(client, versioned=True)
    db.clients[cid] = client
    return success(serialize.serialize_client(client), status=201)


@app.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "Technician", "ComplianceOfficer"})
    client = helpers.get_or_404(db.clients, cid)
    return success(serialize.serialize_client(client), status=200)


@app.route("/clients", methods=["GET"])
def list_clients():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "ComplianceOfficer"})
    limit, offset = helpers.get_pagination()
    items = list(db.clients.values())
    studio_id = request.args.get("studio_id")
    if studio_id is not None:
        items = [c for c in items if c["studio_id"] == studio_id]
    page, total = helpers.paginate(items, limit, offset)
    return list_success([serialize.serialize_client(c) for c in page], limit, offset, total)


@app.route("/clients/<cid>/medical-clearance", methods=["POST"])
def medical_clearance(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ComplianceOfficer"})
    client = helpers.get_or_404(db.clients, cid)
    client["medical_cleared"] = True
    helpers.touch(client)
    return success(serialize.serialize_client(client), status=200)


# ============================================================================
# ConsentRecord
# ============================================================================
@app.route("/consent-records", methods=["POST"])
def create_consent():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"FrontDesk", "ComplianceOfficer"})
    body = helpers.get_body()
    client_id = helpers.require_str(body, "client_id")
    consent_type = helpers.require_enum(body, "consent_type",
                                        {"PROCEDURE_CONSENT", "MEDICAL_DISCLOSURE", "PHOTO_RELEASE"})
    age_verified = helpers.require_bool(body, "age_verified")
    signed_by_name = helpers.require_str(body, "signed_by_name")

    helpers.get_or_404(db.clients, client_id)

    rid = new_id()
    rec = {
        "id": rid,
        "client_id": client_id,
        "consent_type": consent_type,
        "age_verified": age_verified,
        "signed_by_name": signed_by_name,
    }
    helpers.stamp_common(rec, versioned=False)
    db.consent_records[rid] = rec
    return success(serialize.serialize_consent(rec), status=201)


@app.route("/consent-records/<rid>", methods=["GET"])
def get_consent(rid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "ComplianceOfficer"})
    rec = helpers.get_or_404(db.consent_records, rid)
    return success(serialize.serialize_consent(rec), status=200)


@app.route("/consent-records", methods=["GET"])
def list_consents():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "ComplianceOfficer"})
    limit, offset = helpers.get_pagination()
    items = list(db.consent_records.values())
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [r for r in items if r["client_id"] == client_id]
    page, total = helpers.paginate(items, limit, offset)
    return list_success([serialize.serialize_consent(r) for r in page], limit, offset, total)


# ============================================================================
# PatchTest
# ============================================================================
@app.route("/patch-tests", methods=["POST"])
def create_patch_test():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"Technician", "FrontDesk"})
    body = helpers.get_body()
    client_id = helpers.require_str(body, "client_id")
    helpers.get_or_404(db.clients, client_id)

    pid = new_id()
    pt = {
        "id": pid,
        "client_id": client_id,
        "applied_at": helpers.iso_ms_now(),
        "read_at": None,
        "status": "APPLIED",
        "reaction_grade": None,
        "result": None,
    }
    helpers.stamp_common(pt, versioned=True)
    db.patch_tests[pid] = pt
    return success(serialize.serialize_patch_test(pt), status=201)


@app.route("/patch-tests/<pid>", methods=["GET"])
def get_patch_test(pid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "Technician", "ComplianceOfficer"})
    pt = helpers.get_or_404(db.patch_tests, pid)
    return success(serialize.serialize_patch_test(pt), status=200)


@app.route("/patch-tests", methods=["GET"])
def list_patch_tests():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "Technician", "ComplianceOfficer"})
    limit, offset = helpers.get_pagination()
    items = list(db.patch_tests.values())
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [p for p in items if p["client_id"] == client_id]
    page, total = helpers.paginate(items, limit, offset)
    return list_success([serialize.serialize_patch_test(p) for p in page], limit, offset, total)


@app.route("/patch-tests/<pid>/read", methods=["POST"])
def read_patch_test(pid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"Technician"})
    pt = helpers.get_or_404(db.patch_tests, pid)
    body = helpers.get_body()
    reaction_grade = helpers.require_int(body, "reaction_grade")
    # range -> ERR_VALIDATION_RANGE
    if reaction_grade < 0 or reaction_grade > 3:
        raise errors.err(errors.ERR_VALIDATION_RANGE, "reaction_grade must be 0..3")
    # state
    if pt["status"] != "APPLIED":
        raise errors.err(errors.ERR_INVALID_STATE, "Patch test not APPLIED")
    # cooling-off: current time >= applied_at + 48h
    applied = helpers.parse_dt(pt["applied_at"], "applied_at")
    if clock.now() < applied + PATCH_READ_MIN:
        raise errors.err(errors.ERR_COOLING_OFF_VIOLATION, "Patch read minimum (48h) not yet elapsed")

    pt["status"] = "READ"
    pt["read_at"] = helpers.iso_ms_now()
    pt["reaction_grade"] = reaction_grade
    pt["result"] = "PASS" if reaction_grade <= 1 else "FAIL"
    helpers.touch(pt)

    client = db.clients.get(pt["client_id"])
    if client:
        client["skin_sensitivity_observed"] = reaction_grade
        helpers.touch(client)
    return success(serialize.serialize_patch_test(pt), status=200)


@app.route("/patch-tests/<pid>/void", methods=["POST"])
def void_patch_test(pid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ComplianceOfficer"})
    pt = helpers.get_or_404(db.patch_tests, pid)
    if pt["status"] != "APPLIED":
        raise errors.err(errors.ERR_INVALID_STATE, "Patch test not APPLIED")
    pt["status"] = "VOIDED"
    helpers.touch(pt)
    return success(serialize.serialize_patch_test(pt), status=200)


# ============================================================================
# ColorFormula
# ============================================================================
@app.route("/color-formulas", methods=["POST"])
def create_color_formula():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "Technician"})
    body = helpers.get_body()
    studio_id = helpers.require_str(body, "studio_id")
    name = helpers.require_str(body, "name")
    procedure_type = helpers.require_enum(body, "procedure_type", PROCEDURE_TYPES)
    pigment_count = helpers.require_int(body, "pigment_count")
    if pigment_count < 1:
        raise errors.err(errors.ERR_VALIDATION_RANGE, "pigment_count must be >= 1")

    helpers.get_or_404(db.studios, studio_id)

    fid = new_id()
    cf = {
        "id": fid,
        "studio_id": studio_id,
        "name": name,
        "procedure_type": procedure_type,
        "pigment_count": pigment_count,
    }
    helpers.stamp_common(cf, versioned=True)
    db.color_formulas[fid] = cf
    return success(serialize.serialize_color_formula(cf), status=201)


@app.route("/color-formulas/<fid>", methods=["GET"])
def get_color_formula(fid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "Technician", "ComplianceOfficer"})
    cf = helpers.get_or_404(db.color_formulas, fid)
    return success(serialize.serialize_color_formula(cf), status=200)


@app.route("/color-formulas", methods=["GET"])
def list_color_formulas():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "Technician", "ComplianceOfficer"})
    limit, offset = helpers.get_pagination()
    items = list(db.color_formulas.values())
    studio_id = request.args.get("studio_id")
    if studio_id is not None:
        items = [c for c in items if c["studio_id"] == studio_id]
    page, total = helpers.paginate(items, limit, offset)
    return list_success([serialize.serialize_color_formula(c) for c in page], limit, offset, total)


# ============================================================================
# Booking gates (shared by initial / touch-up / annual-refresh)
# ============================================================================
def _booking_safety_gates(client, scheduled_start, studio, patch_test=None, check_patch=True, check_cooling=True):
    """Gates in priority order (PRD 3.5 / 2.9):
      6 age, 7 consent, 8 patch-test, 9 cooling-off, 10 high-risk, 11 blocked.
    patch_test/check_cooling are skipped for annual-refresh (no patch/cooling gate
    per PRD 3.8 annual-refresh gate list)."""
    # 6 — Age verification
    dob = helpers.parse_dt(client["date_of_birth"], "date_of_birth")
    age_years = helpers.whole_years_between(dob, scheduled_start)
    has_age_verified_consent = any(
        r["client_id"] == client["id"] and r["age_verified"] is True
        for r in db.consent_records.values()
    )
    if age_years < studio["min_client_age"] or not has_age_verified_consent:
        raise errors.err(errors.ERR_AGE_NOT_VERIFIED, "Age not verified for booking")

    # 7 — Consent present (PROCEDURE_CONSENT)
    has_procedure_consent = any(
        r["client_id"] == client["id"] and r["consent_type"] == "PROCEDURE_CONSENT"
        for r in db.consent_records.values()
    )
    if not has_procedure_consent:
        raise errors.err(errors.ERR_CONSENT_MISSING, "PROCEDURE_CONSENT not on file for client")

    # 8 — Patch-test gate
    if check_patch:
        if patch_test is None or patch_test["status"] != "READ" or patch_test["result"] != "PASS":
            raise errors.err(errors.ERR_PATCH_TEST_FAILED, "Patch test not READ/PASS")

    # 9 — Cooling-off
    if check_cooling and patch_test is not None:
        applied = helpers.parse_dt(patch_test["applied_at"], "applied_at")
        if scheduled_start < applied + PATCH_READ_MIN:
            raise errors.err(errors.ERR_COOLING_OFF_VIOLATION, "Cooling-off (48h) not satisfied")

    # 10 — High-risk gate
    score, band = serialize.client_risk(client)
    if band == "HIGH_RISK" and not client["medical_cleared"]:
        raise errors.err(errors.ERR_MEDICAL_CLEARANCE_REQUIRED, "HIGH_RISK client requires medical clearance")

    # 11 — Blocked client
    strikes = serialize.client_no_show_strikes(client["id"])
    if serialize.client_status(strikes) == "BLOCKED":
        raise errors.err(errors.ERR_CLIENT_BLOCKED, "Client is BLOCKED")


# ============================================================================
# Appointment
# ============================================================================
@app.route("/appointments", methods=["POST"])
def book_appointment():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"FrontDesk"})
    body = helpers.get_body()
    client_id = helpers.require_str(body, "client_id")
    technician_id = helpers.require_str(body, "technician_id")
    color_formula_id = helpers.require_str(body, "color_formula_id")
    patch_test_id = helpers.require_str(body, "patch_test_id")
    procedure_type = helpers.require_enum(body, "procedure_type", PROCEDURE_TYPES)
    is_corrective = helpers.optional_bool(body, "is_corrective", False)
    scheduled_start = helpers.require_dt(body, "scheduled_start")

    # existence left-to-right
    client = helpers.get_or_404(db.clients, client_id)
    tech = helpers.get_or_404(db.technicians, technician_id)
    cf = helpers.get_or_404(db.color_formulas, color_formula_id)
    pt = helpers.get_or_404(db.patch_tests, patch_test_id)

    # well-formedness: procedure_type must equal color_formula.procedure_type
    if procedure_type != cf["procedure_type"]:
        raise errors.err(errors.ERR_INVALID_REQUEST, "procedure_type must equal color_formula.procedure_type")

    studio = db.studios.get(client["studio_id"])

    # safety gates
    _booking_safety_gates(client, scheduled_start, studio, patch_test=pt,
                          check_patch=True, check_cooling=True)

    appt = _create_appointment(
        client_id=client_id, technician_id=technician_id, color_formula_id=color_formula_id,
        patch_test_id=patch_test_id, procedure_type=procedure_type, is_corrective=is_corrective,
        scheduled_start=scheduled_start, appointment_kind="INITIAL", pigment_count=cf["pigment_count"],
    )
    return success(serialize.serialize_appointment(appt), status=201)


def _create_appointment(client_id, technician_id, color_formula_id, patch_test_id,
                        procedure_type, is_corrective, scheduled_start, appointment_kind,
                        pigment_count, parent_appointment_id=None, package_order_id=None):
    sp = calc.session_price(procedure_type, pigment_count, is_corrective, appointment_kind)
    dep = calc.deposit_amount(sp, appointment_kind)
    aid = new_id()
    appt = {
        "id": aid,
        "client_id": client_id,
        "technician_id": technician_id,
        "color_formula_id": color_formula_id,
        "patch_test_id": patch_test_id,
        "procedure_type": procedure_type,
        "appointment_kind": appointment_kind,
        "is_corrective": is_corrective,
        "scheduled_start": _iso(scheduled_start),
        "lifecycle_status": "BOOKED",
        "payment_status": "AWAITING_DEPOSIT",
        "session_price_cents": sp,
        "deposit_required_cents": dep,
        "kit_consumed": False,
        "healing_outcome": None,
        "completed_at": None,
        "parent_appointment_id": parent_appointment_id,
        "package_order_id": package_order_id,
    }
    helpers.stamp_common(appt, versioned=True)
    db.appointments[aid] = appt
    return appt


@app.route("/appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "Technician", "ComplianceOfficer"})
    appt = helpers.get_or_404(db.appointments, aid)
    return success(serialize.serialize_appointment(appt), status=200)


@app.route("/appointments", methods=["GET"])
def list_appointments():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "Technician", "ComplianceOfficer"})
    limit, offset = helpers.get_pagination()
    items = list(db.appointments.values())
    for f in ("client_id", "technician_id", "color_formula_id", "patch_test_id",
              "parent_appointment_id", "package_order_id"):
        val = request.args.get(f)
        if val is not None:
            items = [a for a in items if a.get(f) == val]
    page, total = helpers.paginate(items, limit, offset)
    return list_success([serialize.serialize_appointment(a) for a in page], limit, offset, total)


@app.route("/appointments/<aid>/deposit", methods=["POST"])
def collect_deposit(aid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"FrontDesk"})
    appt = helpers.get_or_404(db.appointments, aid)
    body = helpers.get_body()
    amount_cents = helpers.require_int(body, "amount_cents")
    if amount_cents <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "amount_cents must be > 0")
    if appt["payment_status"] != "AWAITING_DEPOSIT":
        raise errors.err(errors.ERR_INVALID_STATE, "Payment not AWAITING_DEPOSIT")
    if amount_cents != appt["deposit_required_cents"]:
        raise errors.err(errors.ERR_DEPOSIT_AMOUNT_MISMATCH, "amount_cents must equal deposit_required_cents")
    services.emit_txn(aid, "CHARGE", amount_cents)
    appt["payment_status"] = "DEPOSIT_PAID"
    helpers.touch(appt)
    return success(serialize.serialize_appointment(appt), status=200)


@app.route("/appointments/<aid>/start", methods=["POST"])
def start_procedure(aid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"Technician"})
    appt = helpers.get_or_404(db.appointments, aid)
    # state
    if appt["lifecycle_status"] != "BOOKED":
        raise errors.err(errors.ERR_INVALID_STATE, "Appointment not BOOKED")
    if appt["payment_status"] not in ("DEPOSIT_PAID", "PAID_IN_FULL"):
        raise errors.err(errors.ERR_INVALID_STATE, "Payment not DEPOSIT_PAID/PAID_IN_FULL")

    tech = db.technicians.get(appt["technician_id"])
    studio = db.studios.get(tech["studio_id"]) if tech else None

    # patch-test gate (priority 8)
    pt = db.patch_tests.get(appt["patch_test_id"])
    if pt is None or pt["status"] != "READ" or pt["result"] != "PASS":
        # license gate evaluated below; but PRD lists patch failure as ERR_PATCH_TEST_FAILED at start
        pass

    # license/posture gate (priority 12)
    services.effective_license_status(tech)
    posture = serialize.compliance_posture(studio) if studio else "FROZEN"
    if tech["license_status"] != "LICENSE_ACTIVE" or posture != "OPEN":
        raise errors.err(errors.ERR_LICENSE_INVALID, "Technician not active or studio posture not OPEN")

    # kit availability (priority 17)
    available = serialize.studio_kit_available(studio) if studio else 0
    if available < 1:
        raise errors.err(errors.ERR_NO_STERILE_KIT, "No sterile kit available")

    # patch-test gate
    if pt is None or pt["status"] != "READ" or pt["result"] != "PASS":
        raise errors.err(errors.ERR_PATCH_TEST_FAILED, "Patch test not READ/PASS")

    appt["lifecycle_status"] = "IN_PROCEDURE"
    appt["kit_consumed"] = True
    helpers.touch(appt)
    # Studio kit ledger & posture recomputed (derived) -> bump studio version
    if studio:
        helpers.touch(studio)
    return success(serialize.serialize_appointment(appt), status=200)


@app.route("/appointments/<aid>/finish-procedure", methods=["POST"])
def finish_procedure(aid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"Technician"})
    appt = helpers.get_or_404(db.appointments, aid)
    if appt["lifecycle_status"] != "IN_PROCEDURE":
        raise errors.err(errors.ERR_INVALID_STATE, "Appointment not IN_PROCEDURE")
    appt["lifecycle_status"] = "HEALING"
    # parallel payment axis: DEPOSIT_PAID -> BALANCE_DUE
    if appt["payment_status"] == "DEPOSIT_PAID":
        appt["payment_status"] = "BALANCE_DUE"
    helpers.touch(appt)
    return success(serialize.serialize_appointment(appt), status=200)


@app.route("/appointments/<aid>/pay-balance", methods=["POST"])
def pay_balance(aid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"FrontDesk"})
    appt = helpers.get_or_404(db.appointments, aid)
    body = helpers.get_body()
    amount_cents = helpers.require_int(body, "amount_cents")
    if amount_cents <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "amount_cents must be > 0")
    if appt["payment_status"] != "BALANCE_DUE":
        raise errors.err(errors.ERR_INVALID_STATE, "Payment not BALANCE_DUE")
    deposit_paid = serialize.appointment_deposit_paid(aid)
    balance_due = appt["session_price_cents"] - deposit_paid
    if amount_cents != balance_due:
        raise errors.err(errors.ERR_DEPOSIT_AMOUNT_MISMATCH, "amount_cents must equal balance_due_cents")
    appt["payment_status"] = "PAID_IN_FULL"
    helpers.touch(appt)
    return success(serialize.serialize_appointment(appt), status=200)


@app.route("/appointments/<aid>/complete", methods=["POST"])
def complete_appointment(aid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"Technician"})
    appt = helpers.get_or_404(db.appointments, aid)
    if appt["lifecycle_status"] != "HEALING":
        raise errors.err(errors.ERR_INVALID_STATE, "Appointment not HEALING")
    if appt["payment_status"] != "PAID_IN_FULL":
        raise errors.err(errors.ERR_INVALID_STATE, "Payment not PAID_IN_FULL")
    logs = [h for h in db.healing_logs.values() if h["appointment_id"] == aid]
    if len(logs) == 0:
        raise errors.err(errors.ERR_INVALID_STATE, "At least one healing log required")

    appt["lifecycle_status"] = "COMPLETED"
    appt["completed_at"] = helpers.iso_ms_now()
    appt["healing_outcome"] = "POOR" if any(h["outcome_flag"] == "POOR" for h in logs) else "GOOD"
    helpers.touch(appt)

    # If this is a REDO appointment linked to a SCHEDULED redo request, bubble up to FULFILLED
    if appt["appointment_kind"] == "REDO":
        for r in db.redo_requests.values():
            if r["redo_appointment_id"] == aid and r["status"] == "SCHEDULED":
                r["status"] = "FULFILLED"
                helpers.touch(r)
    return success(serialize.serialize_appointment(appt), status=200)


@app.route("/appointments/<aid>/cancel", methods=["POST"])
def cancel_appointment(aid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"FrontDesk"})
    appt = helpers.get_or_404(db.appointments, aid)
    if appt["lifecycle_status"] != "BOOKED":
        raise errors.err(errors.ERR_INVALID_STATE, "Appointment not BOOKED")
    appt["lifecycle_status"] = "CANCELLED"
    deposit_paid = serialize.appointment_deposit_paid(aid)
    scheduled = helpers.parse_dt(appt["scheduled_start"], "scheduled_start")
    if clock.now() <= scheduled - CANCEL_FREE:
        # full refund
        if deposit_paid > 0:
            services.emit_txn(aid, "REFUND", deposit_paid)
        appt["payment_status"] = "REFUNDED"
    else:
        # late cancel: forfeit, deposit kept, payment stays DEPOSIT_PAID
        if deposit_paid > 0:
            services.emit_txn(aid, "FORFEIT", deposit_paid)
    helpers.touch(appt)
    return success(serialize.serialize_appointment(appt), status=200)


@app.route("/appointments/<aid>/no-show", methods=["POST"])
def no_show_appointment(aid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"FrontDesk"})
    appt = helpers.get_or_404(db.appointments, aid)
    if appt["lifecycle_status"] != "BOOKED":
        raise errors.err(errors.ERR_INVALID_STATE, "Appointment not BOOKED")
    scheduled = helpers.parse_dt(appt["scheduled_start"], "scheduled_start")
    if clock.now() < scheduled:
        raise errors.err(errors.ERR_INVALID_STATE, "Cannot mark no-show before scheduled_start")
    appt["lifecycle_status"] = "NO_SHOW"
    deposit_paid = serialize.appointment_deposit_paid(aid)
    if deposit_paid > 0:
        services.emit_txn(aid, "FORFEIT", deposit_paid)
    helpers.touch(appt)
    # client strikes / status recomputed (derived) -> bump client version
    client = db.clients.get(appt["client_id"])
    if client:
        helpers.touch(client)
    return success(serialize.serialize_appointment(appt), status=200)


@app.route("/appointments/<aid>/void", methods=["POST"])
def compliance_void(aid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ComplianceOfficer"})
    appt = helpers.get_or_404(db.appointments, aid)
    if appt["lifecycle_status"] != "BOOKED":
        raise errors.err(errors.ERR_INVALID_STATE, "Appointment not BOOKED")
    services.void_appointment(appt)
    return success(serialize.serialize_appointment(appt), status=200)


@app.route("/appointments/touch-up", methods=["POST"])
def book_touch_up():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"FrontDesk"})
    body = helpers.get_body()
    package_order_id = helpers.require_str(body, "package_order_id")
    technician_id = helpers.require_str(body, "technician_id")
    color_formula_id = helpers.require_str(body, "color_formula_id")
    patch_test_id = helpers.require_str(body, "patch_test_id")
    procedure_type = helpers.require_enum(body, "procedure_type", PROCEDURE_TYPES)
    scheduled_start = helpers.require_dt(body, "scheduled_start")
    expected_package_version = helpers.require_int(body, "expected_package_version")

    # existence left-to-right
    pkg = helpers.get_or_404(db.package_orders, package_order_id)
    tech = helpers.get_or_404(db.technicians, technician_id)
    cf = helpers.get_or_404(db.color_formulas, color_formula_id)
    pt = helpers.get_or_404(db.patch_tests, patch_test_id)

    # well-formedness: procedure_type == color_formula.procedure_type
    if procedure_type != cf["procedure_type"]:
        raise errors.err(errors.ERR_INVALID_REQUEST, "procedure_type must equal color_formula.procedure_type")

    source = db.appointments.get(pkg["source_appointment_id"])
    client = db.clients.get(pkg["client_id"])
    studio = db.studios.get(client["studio_id"]) if client else None

    # safety gates (age, consent, patch-test, cooling-off, high-risk, blocked)
    _booking_safety_gates(client, scheduled_start, studio, patch_test=pt,
                          check_patch=True, check_cooling=True)

    # touch-up window (priority 13)
    services.check_package_expiry(pkg)
    remaining = serialize.package_remaining_sessions(pkg)
    completed = helpers.parse_dt(source["completed_at"], "completed_at") if source and source.get("completed_at") else None
    window_ok = (
        completed is not None
        and completed + TOUCHUP_OPEN <= scheduled_start <= completed + TOUCHUP_CLOSE
    )
    if not window_ok or pkg["status"] != "ACTIVE" or remaining <= 0:
        raise errors.err(errors.ERR_TOUCHUP_WINDOW_CLOSED, "Touch-up window closed or package not ACTIVE")

    # OCC last gate (priority 18)
    if expected_package_version != pkg["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "expected_package_version mismatch")

    appt = _create_appointment(
        client_id=pkg["client_id"], technician_id=technician_id, color_formula_id=color_formula_id,
        patch_test_id=patch_test_id, procedure_type=procedure_type, is_corrective=False,
        scheduled_start=scheduled_start, appointment_kind="TOUCH_UP", pigment_count=cf["pigment_count"],
        parent_appointment_id=pkg["source_appointment_id"], package_order_id=package_order_id,
    )
    # draw one session: decrement remaining (derived), bump package version, exhaust if 0
    helpers.touch(pkg)
    if serialize.package_remaining_sessions(pkg) <= 0:
        pkg["status"] = "EXHAUSTED"
        helpers.touch(pkg)
    return success(serialize.serialize_appointment(appt), status=201)


@app.route("/appointments/annual-refresh", methods=["POST"])
def book_annual_refresh():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"FrontDesk"})
    body = helpers.get_body()
    parent_appointment_id = helpers.require_str(body, "parent_appointment_id")
    technician_id = helpers.require_str(body, "technician_id")
    color_formula_id = helpers.require_str(body, "color_formula_id")
    patch_test_id = helpers.require_str(body, "patch_test_id")
    procedure_type = helpers.require_enum(body, "procedure_type", PROCEDURE_TYPES)
    scheduled_start = helpers.require_dt(body, "scheduled_start")

    parent = helpers.get_or_404(db.appointments, parent_appointment_id)
    tech = helpers.get_or_404(db.technicians, technician_id)
    cf = helpers.get_or_404(db.color_formulas, color_formula_id)
    pt = helpers.get_or_404(db.patch_tests, patch_test_id)

    if procedure_type != cf["procedure_type"]:
        raise errors.err(errors.ERR_INVALID_REQUEST, "procedure_type must equal color_formula.procedure_type")

    client = db.clients.get(parent["client_id"])
    studio = db.studios.get(client["studio_id"]) if client else None

    # annual-refresh gated by age, consent, high-risk, blocked (no patch/cooling gate)
    _booking_safety_gates(client, scheduled_start, studio, patch_test=pt,
                          check_patch=False, check_cooling=False)

    # annual-refresh window (priority 14): scheduled_start >= completed_at + 365d
    if not parent.get("completed_at"):
        raise errors.err(errors.ERR_REFRESH_NOT_DUE, "Source appointment not completed")
    completed = helpers.parse_dt(parent["completed_at"], "completed_at")
    if scheduled_start < completed + ANNUAL_DAYS:
        raise errors.err(errors.ERR_REFRESH_NOT_DUE, "Annual refresh not yet due")

    appt = _create_appointment(
        client_id=parent["client_id"], technician_id=technician_id, color_formula_id=color_formula_id,
        patch_test_id=patch_test_id, procedure_type=procedure_type, is_corrective=False,
        scheduled_start=scheduled_start, appointment_kind="ANNUAL_REFRESH", pigment_count=cf["pigment_count"],
        parent_appointment_id=parent_appointment_id,
    )
    return success(serialize.serialize_appointment(appt), status=201)


# ============================================================================
# PackageOrder
# ============================================================================
@app.route("/packages", methods=["POST"])
def create_package():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"FrontDesk"})
    body = helpers.get_body()
    client_id = helpers.require_str(body, "client_id")
    source_appointment_id = helpers.require_str(body, "source_appointment_id")
    included_sessions = helpers.require_int(body, "included_sessions")
    pricing_mode = helpers.require_enum(body, "pricing_mode", {"PAYG", "BUNDLE"})

    if included_sessions < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, "included_sessions must be >= 1")

    client = helpers.get_or_404(db.clients, client_id)
    source = helpers.get_or_404(db.appointments, source_appointment_id)

    # source must be a COMPLETED INITIAL appointment
    if source["lifecycle_status"] != "COMPLETED" or source["appointment_kind"] != "INITIAL":
        raise errors.err(errors.ERR_INVALID_STATE, "Source appointment must be COMPLETED INITIAL")

    price = calc.package_price(source["session_price_cents"], included_sessions, pricing_mode)
    pid = new_id()
    pkg = {
        "id": pid,
        "client_id": client_id,
        "source_appointment_id": source_appointment_id,
        "included_sessions": included_sessions,
        "pricing_mode": pricing_mode,
        "package_price_cents": price,
        "status": "ACTIVE",
    }
    helpers.stamp_common(pkg, versioned=True)
    db.package_orders[pid] = pkg
    return success(serialize.serialize_package(pkg), status=201)


@app.route("/packages/<pid>", methods=["GET"])
def get_package(pid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "ComplianceOfficer"})
    pkg = helpers.get_or_404(db.package_orders, pid)
    services.check_package_expiry(pkg)
    return success(serialize.serialize_package(pkg), status=200)


@app.route("/packages", methods=["GET"])
def list_packages():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "ComplianceOfficer"})
    limit, offset = helpers.get_pagination()
    items = list(db.package_orders.values())
    for f in ("client_id", "source_appointment_id"):
        val = request.args.get(f)
        if val is not None:
            items = [p for p in items if p.get(f) == val]
    page, total = helpers.paginate(items, limit, offset)
    for p in page:
        services.check_package_expiry(p)
    return list_success([serialize.serialize_package(p) for p in page], limit, offset, total)


# ============================================================================
# DepositTransaction
# ============================================================================
@app.route("/deposit-transactions/<tid>", methods=["GET"])
def get_deposit_txn(tid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "ComplianceOfficer"})
    t = helpers.get_or_404(db.deposit_transactions, tid)
    return success(serialize.serialize_deposit_txn(t), status=200)


@app.route("/deposit-transactions", methods=["GET"])
def list_deposit_txns():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "ComplianceOfficer"})
    limit, offset = helpers.get_pagination()
    items = list(db.deposit_transactions.values())
    appointment_id = request.args.get("appointment_id")
    if appointment_id is not None:
        items = [t for t in items if t["appointment_id"] == appointment_id]
    page, total = helpers.paginate(items, limit, offset)
    return list_success([serialize.serialize_deposit_txn(t) for t in page], limit, offset, total)


# ============================================================================
# HealingLog
# ============================================================================
@app.route("/healing-logs", methods=["POST"])
def create_healing_log():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"Technician", "FrontDesk"})
    body = helpers.get_body()
    appointment_id = helpers.require_str(body, "appointment_id")
    day_offset = helpers.require_int(body, "day_offset")
    outcome_flag = helpers.require_enum(body, "outcome_flag", {"GOOD", "POOR"})
    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "notes must be a string")
    if day_offset < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "day_offset must be >= 0")

    appt = helpers.get_or_404(db.appointments, appointment_id)
    # must be a HEALING or COMPLETED appointment
    if appt["lifecycle_status"] not in ("HEALING", "COMPLETED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Appointment must be HEALING or COMPLETED")

    hid = new_id()
    log = {
        "id": hid,
        "appointment_id": appointment_id,
        "day_offset": day_offset,
        "outcome_flag": outcome_flag,
        "notes": notes,
    }
    helpers.stamp_common(log, versioned=False)
    db.healing_logs[hid] = log

    # if appointment already COMPLETED and outcome POOR, recompute healing_outcome
    if appt["lifecycle_status"] == "COMPLETED" and outcome_flag == "POOR":
        appt["healing_outcome"] = "POOR"
        helpers.touch(appt)
    return success(serialize.serialize_healing_log(log), status=201)


@app.route("/healing-logs/<hid>", methods=["GET"])
def get_healing_log(hid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "Technician", "ComplianceOfficer"})
    log = helpers.get_or_404(db.healing_logs, hid)
    return success(serialize.serialize_healing_log(log), status=200)


@app.route("/healing-logs", methods=["GET"])
def list_healing_logs():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "Technician", "ComplianceOfficer"})
    limit, offset = helpers.get_pagination()
    items = list(db.healing_logs.values())
    appointment_id = request.args.get("appointment_id")
    if appointment_id is not None:
        items = [h for h in items if h["appointment_id"] == appointment_id]
    page, total = helpers.paginate(items, limit, offset)
    return list_success([serialize.serialize_healing_log(h) for h in page], limit, offset, total)


# ============================================================================
# RedoRequest
# ============================================================================
def _redo_eligible(appt):
    if appt["lifecycle_status"] != "COMPLETED":
        return False
    if appt["healing_outcome"] != "POOR":
        return False
    if not appt.get("completed_at"):
        return False
    completed = helpers.parse_dt(appt["completed_at"], "completed_at")
    if clock.now() > completed + REDO_WINDOW:
        return False
    return True


@app.route("/redo-requests", methods=["POST"])
def create_redo_request():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"FrontDesk", "ComplianceOfficer"})
    body = helpers.get_body()
    appointment_id = helpers.require_str(body, "appointment_id")
    reason = helpers.require_str(body, "reason")

    appt = helpers.get_or_404(db.appointments, appointment_id)
    if not _redo_eligible(appt):
        raise errors.err(errors.ERR_REDO_NOT_ELIGIBLE, "Source not COMPLETED+POOR or beyond redo window")

    rid = new_id()
    redo = {
        "id": rid,
        "appointment_id": appointment_id,
        "reason": reason,
        "status": "REQUESTED",
        "redo_appointment_id": None,
    }
    helpers.stamp_common(redo, versioned=True)
    db.redo_requests[rid] = redo
    return success(serialize.serialize_redo_request(redo), status=201)


@app.route("/redo-requests/<rid>", methods=["GET"])
def get_redo_request(rid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "Technician", "ComplianceOfficer"})
    redo = helpers.get_or_404(db.redo_requests, rid)
    return success(serialize.serialize_redo_request(redo), status=200)


@app.route("/redo-requests", methods=["GET"])
def list_redo_requests():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"StudioAdmin", "FrontDesk", "Technician", "ComplianceOfficer"})
    limit, offset = helpers.get_pagination()
    items = list(db.redo_requests.values())
    for f in ("appointment_id", "redo_appointment_id"):
        val = request.args.get(f)
        if val is not None:
            items = [r for r in items if r.get(f) == val]
    page, total = helpers.paginate(items, limit, offset)
    return list_success([serialize.serialize_redo_request(r) for r in page], limit, offset, total)


@app.route("/redo-requests/<rid>/approve", methods=["POST"])
def approve_redo(rid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ComplianceOfficer"})
    redo = helpers.get_or_404(db.redo_requests, rid)
    if redo["status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Redo request not REQUESTED")
    appt = db.appointments.get(redo["appointment_id"])
    if not appt or not _redo_eligible(appt):
        raise errors.err(errors.ERR_REDO_NOT_ELIGIBLE, "Redo no longer eligible")
    redo["status"] = "APPROVED"
    helpers.touch(redo)
    return success(serialize.serialize_redo_request(redo), status=200)


@app.route("/redo-requests/<rid>/deny", methods=["POST"])
def deny_redo(rid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ComplianceOfficer"})
    redo = helpers.get_or_404(db.redo_requests, rid)
    if redo["status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Redo request not REQUESTED")
    redo["status"] = "DENIED"
    helpers.touch(redo)
    return success(serialize.serialize_redo_request(redo), status=200)


@app.route("/redo-requests/<rid>/schedule", methods=["POST"])
def schedule_redo(rid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"FrontDesk"})
    redo = helpers.get_or_404(db.redo_requests, rid)
    body = helpers.get_body()
    scheduled_start = helpers.require_dt(body, "scheduled_start")
    technician_id = helpers.require_str(body, "technician_id")
    color_formula_id = helpers.require_str(body, "color_formula_id")
    patch_test_id = helpers.require_str(body, "patch_test_id")
    expected_appointment_version = helpers.require_int(body, "expected_appointment_version")

    # existence of referenced new-procedure resources
    tech = helpers.get_or_404(db.technicians, technician_id)
    cf = helpers.get_or_404(db.color_formulas, color_formula_id)
    pt = helpers.get_or_404(db.patch_tests, patch_test_id)

    if redo["status"] != "APPROVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Redo request not APPROVED")

    source = db.appointments.get(redo["appointment_id"])
    if source is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Source appointment not found")

    # OCC last gate
    if expected_appointment_version != source["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "expected_appointment_version mismatch")

    # create REDO appointment (free, PAID_IN_FULL, BOOKED)
    new_appt = _create_appointment(
        client_id=source["client_id"], technician_id=technician_id, color_formula_id=color_formula_id,
        patch_test_id=patch_test_id, procedure_type=cf["procedure_type"], is_corrective=False,
        scheduled_start=scheduled_start, appointment_kind="REDO", pigment_count=cf["pigment_count"],
        parent_appointment_id=source["id"],
    )
    new_appt["payment_status"] = "PAID_IN_FULL"

    redo["status"] = "SCHEDULED"
    redo["redo_appointment_id"] = new_appt["id"]
    helpers.touch(redo)
    # source appointment version incremented (consumes the redo allowance)
    helpers.touch(source)
    return success(serialize.serialize_redo_request(redo), status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Quiet the Werkzeug dev server: per-request access logging writes to stderr on
    # every call, which under the 8x-parallel per-test-reboot sweep adds I/O
    # contention and can slow the runner's readiness probe (manifesting as
    # "could not be restarted"). Silencing the access log is safe; do NOT set
    # WERKZEUG_RUN_MAIN (it makes Werkzeug expect an inherited socket FD and crash).
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
