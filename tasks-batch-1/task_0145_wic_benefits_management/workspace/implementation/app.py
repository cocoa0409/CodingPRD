"""WIC Benefits Management API — Flask entry point.

Route registration, auth/RBAC, request parsing, serializers, and per-endpoint
validation in the priority order of PRD §2.9.

Validation order (global, every write):
  1. ERR_UNAUTHENTICATED  (headers present + role recognized)
  2. ERR_FORBIDDEN        (role permitted for the operation)
  3. ERR_NOT_FOUND        (path ids, then body FK ids, left-to-right)
  4. ERR_INVALID_REQUEST  (required fields, enums, non-negative integers)
  5. ERR_STALE_VERSION    (OCC, only the two guarded writes)
  6. ERR_INVALID_STATE    (transition legality)
  ... then domain-specific business rules.
"""
import os
from datetime import datetime, timezone

from flask import Flask, request as flask_request

from db import db, new_common, touch
from response import success, error_response, iso_ms
from errors import (
    ApiError, err,
    ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_STALE_VERSION, ERR_INVALID_STATE, ERR_NO_INCOME_RECORDS,
    ERR_SEGREGATION_OF_DUTIES, ERR_DUAL_PARTICIPATION, ERR_INCOME_INELIGIBLE,
    ERR_RISK_INELIGIBLE, ERR_CASELOAD_EXCEEDED, ERR_CERT_NOT_ACTIVE,
    ERR_EBT_FROZEN, ERR_INSUFFICIENT_BALANCE, ERR_VENDOR_NOT_AUTHORIZED,
    ERR_CERT_PERIOD_ENDED, ERR_APPOINTMENT_OVERLAP, ERR_APPOINTMENT_NOT_PAST,
    ERR_PARTICIPANT_NOT_SERVICEABLE, ERR_CATEGORY_FOOD_MISMATCH,
)
import calculations as calc
import services

app = Flask(__name__)

# ----------------------------------------------------------------------------
# Roles & enums (PRD §2.1, §3)
# ----------------------------------------------------------------------------
ROLES = {"EligibilityClerk", "CompetentProfessionalAuthority", "Participant"}
CLERK = "EligibilityClerk"
CPA = "CompetentProfessionalAuthority"
PARTICIPANT = "Participant"

PEER_GROUPS = {"SMALL", "MEDIUM", "LARGE"}
ADJUNCTIVE = {"NONE", "SNAP", "MEDICAID", "TANF"}
CATEGORIES = {"PREGNANT", "POSTPARTUM", "BREASTFEEDING", "INFANT", "CHILD"}
INCOME_METHODS = {"ANNUALIZE_RECENT", "AVERAGE_ALL"}
PAY_FREQUENCIES = {"WEEKLY", "BIWEEKLY", "MONTHLY", "ANNUAL"}
RISK_CODES = set(calc.RISK_FACTOR_POINTS.keys())
ISSUANCE_MODES = {"FULL", "PRORATED"}
APPT_PURPOSES = {"INITIAL_CERT", "RECERT", "NUTRITION_ED", "BF_SUPPORT"}
EPOCH = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


# ----------------------------------------------------------------------------
# Error handlers
# ----------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", str(e), 400)


# ----------------------------------------------------------------------------
# Parsing helpers
# ----------------------------------------------------------------------------
def get_body():
    try:
        body = flask_request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: {}".format(field))
    return body[field]


def require_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or not v.strip():
        raise err(ERR_INVALID_REQUEST, "{} must be a non-empty string.".format(field))
    return v


def require_int(body, field, minimum=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "{} must be an integer.".format(field))
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, "{} must be >= {}.".format(field, minimum))
    return v


def optional_int(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum=minimum)


def require_enum(body, field, allowed):
    v = require_str(body, field)
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, "Invalid {}.".format(field))
    return v


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    return require_enum(body, field, allowed)


def parse_iso(value, field="timestamp"):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "Invalid {}.".format(field))
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Invalid ISO 8601 {}.".format(field))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ----------------------------------------------------------------------------
# Auth / RBAC (PRD §2.1)
# ----------------------------------------------------------------------------
def auth():
    role = flask_request.headers.get("X-User-Role")
    user_id = flask_request.headers.get("X-User-ID")
    if not user_id or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unrecognized authentication headers.")
    return role, user_id


def require_role(role, allowed):
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "Role {} not permitted for this operation.".format(role))


def find_or_404(store, _id):
    if _id is None or not isinstance(_id, str) or _id not in store:
        raise err(ERR_NOT_FOUND, "Referenced resource not found.")
    return store[_id]


# ----------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ----------------------------------------------------------------------------
def paginate(items):
    args = flask_request.args
    limit, offset = 10, 0
    lr, off_r = args.get("limit"), args.get("offset")
    if lr is not None:
        try:
            limit = int(lr)
        except (ValueError, TypeError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if off_r is not None:
        try:
            offset = int(off_r)
        except (ValueError, TypeError):
            offset = 0
        if offset < 0:
            offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": offset + limit < total}
    return page, meta


def sorted_by_created(items):
    return sorted(items, key=lambda x: x["_created_seq"])


# ============================================================================
# Serializers
# ============================================================================
def ser_agency(a):
    return {
        "id": a["id"], "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"], "name": a["name"], "state_code": a["state_code"],
        "caseload_cap": a["caseload_cap"],
        "active_caseload_count": a["active_caseload_count"],
        "current_utc": a["current_utc"],
    }


def ser_clinic(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"], "agency_id": c["agency_id"], "name": c["name"],
        "appointment_buffer_minutes": c["appointment_buffer_minutes"],
    }


def ser_vendor(v):
    return {
        "id": v["id"], "created_at": v["created_at"], "updated_at": v["updated_at"],
        "version": v["version"], "agency_id": v["agency_id"],
        "legal_name": v["legal_name"], "peer_group": v["peer_group"],
        "status": v["status"], "violation_points": v["violation_points"],
    }


def ser_household(h):
    return {
        "id": h["id"], "created_at": h["created_at"], "updated_at": h["updated_at"],
        "version": h["version"], "agency_id": h["agency_id"],
        "household_size": h["household_size"],
        "pregnancy_count": h["pregnancy_count"],
        "adjunctive_program": h["adjunctive_program"],
    }


def ser_participant(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "household_id": p["household_id"],
        "agency_id": p["agency_id"], "full_name": p["full_name"],
        "ssn_last4": p["ssn_last4"], "category": p["category"],
        "breastfeeding_opt_in": p["breastfeeding_opt_in"],
        "status": p["status"], "priority_level": p["priority_level"],
    }


def ser_application(a):
    return {
        "id": a["id"], "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"], "participant_id": a["participant_id"],
        "income_method": a["income_method"],
        "annual_income_determined": a["annual_income_determined"],
        "income_limit": a["income_limit"],
        "income_eligible": a["income_eligible"],
        "determined_by_user_id": a["determined_by_user_id"],
        "certified_by_user_id": a["certified_by_user_id"],
        "risk_factor_codes": a["risk_factor_codes"],
        "total_risk_score": a["total_risk_score"],
        "risk_eligible": a["risk_eligible"],
        "status": a["status"],
    }


def ser_income_record(r):
    return {
        "id": r["id"], "created_at": r["created_at"],
        "application_id": r["application_id"],
        "gross_amount_cents": r["gross_amount_cents"],
        "pay_frequency": r["pay_frequency"],
        "sequence_index": r["sequence_index"],
    }


def ser_certification(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"], "participant_id": c["participant_id"],
        "application_id": c["application_id"],
        "period_start_utc": c["period_start_utc"],
        "period_end_utc": c["period_end_utc"],
        "cert_length_days": c["cert_length_days"],
        "status": c["status"],
    }


def ser_food_prescription(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "certification_id": p["certification_id"],
        "participant_id": p["participant_id"],
        "issuance_mode": p["issuance_mode"],
        "line_items": p["line_items"],
        "prescribed_value_cents": p["prescribed_value_cents"],
        "status": p["status"],
    }


def ser_ebt(a):
    return {
        "id": a["id"], "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"], "participant_id": a["participant_id"],
        "balance_units": a["balance_units"],
        "issued_value_cents": a["issued_value_cents"],
        "redeemed_value_cents": a["redeemed_value_cents"],
        "voided_value_cents": a["voided_value_cents"],
        "remaining_value_cents": a["remaining_value_cents"],
        "status": a["status"],
    }


def ser_redemption(r):
    return {
        "id": r["id"], "created_at": r["created_at"],
        "ebt_account_id": r["ebt_account_id"], "vendor_id": r["vendor_id"],
        "food_category": r["food_category"], "units": r["units"],
        "value_cents": r["value_cents"], "sequence_index": r["sequence_index"],
    }


def ser_appointment(a):
    return {
        "id": a["id"], "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"], "clinic_id": a["clinic_id"],
        "participant_id": a["participant_id"], "purpose": a["purpose"],
        "start_utc": a["start_utc"], "end_utc": a["end_utc"],
        "status": a["status"],
    }


def ser_peer_session(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"], "participant_id": s["participant_id"],
        "peer_counselor_id": s["peer_counselor_id"],
        "start_utc": s["start_utc"], "end_utc": s["end_utc"],
        "status": s["status"],
    }


# ============================================================================
# Test-driving clock (§3.12)
# ============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    body = get_body()
    agency_id = require_str(body, "agency_id")
    to_iso = require(body, "to_iso8601")
    agency = find_or_404(db.agencies, agency_id)
    dt = parse_iso(to_iso, "to_iso8601")
    agency["current_utc"] = iso_ms(dt)
    agency["_current_utc_dt"] = dt
    touch(agency)
    return success(ser_agency(agency), 200)


@app.route("/_clock/advance-expirations", methods=["POST"])
def advance_expirations_route():
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    body = get_body()
    agency_id = require_str(body, "agency_id")
    agency = find_or_404(db.agencies, agency_id)
    expired_ids = services.advance_expirations(agency)
    return success({"expired_certification_ids": expired_ids,
                    "expired_count": len(expired_ids)}, 200)


# ============================================================================
# Agency
# ============================================================================
@app.route("/agencies", methods=["POST"])
def create_agency():
    role, _ = auth()
    require_role(role, {CLERK})
    body = get_body()
    name = require_str(body, "name")
    state_code = require_str(body, "state_code")
    caseload_cap = require_int(body, "caseload_cap", minimum=0)
    a = new_common()
    a.update({
        "name": name, "state_code": state_code, "caseload_cap": caseload_cap,
        "active_caseload_count": 0,
        "current_utc": iso_ms(EPOCH), "_current_utc_dt": EPOCH,
    })
    db.agencies[a["id"]] = a
    return success(ser_agency(a), 201)


@app.route("/agencies/<aid>", methods=["GET"])
def get_agency(aid):
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    return success(ser_agency(find_or_404(db.agencies, aid)), 200)


# ============================================================================
# Clinic
# ============================================================================
@app.route("/clinics", methods=["POST"])
def create_clinic():
    role, _ = auth()
    require_role(role, {CLERK})
    body = get_body()
    agency_id = require_str(body, "agency_id")
    find_or_404(db.agencies, agency_id)
    name = require_str(body, "name")
    buffer_minutes = optional_int(body, "appointment_buffer_minutes", 0, minimum=0)
    c = new_common()
    c.update({"agency_id": agency_id, "name": name,
              "appointment_buffer_minutes": buffer_minutes})
    db.clinics[c["id"]] = c
    return success(ser_clinic(c), 201)


@app.route("/clinics/<cid>", methods=["GET"])
def get_clinic(cid):
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    return success(ser_clinic(find_or_404(db.clinics, cid)), 200)


@app.route("/clinics", methods=["GET"])
def list_clinics():
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    agency_id = flask_request.args.get("agency_id")
    items = [c for c in db.clinics.values()
             if agency_id is None or c["agency_id"] == agency_id]
    page, meta = paginate(sorted_by_created(items))
    return success([ser_clinic(c) for c in page], 200, meta)


# ============================================================================
# Vendor
# ============================================================================
@app.route("/vendors", methods=["POST"])
def create_vendor():
    role, _ = auth()
    require_role(role, {CLERK})
    body = get_body()
    agency_id = require_str(body, "agency_id")
    find_or_404(db.agencies, agency_id)
    legal_name = require_str(body, "legal_name")
    peer_group = require_enum(body, "peer_group", PEER_GROUPS)
    v = new_common()
    v.update({"agency_id": agency_id, "legal_name": legal_name,
              "peer_group": peer_group, "status": "PENDING", "violation_points": 0})
    db.vendors[v["id"]] = v
    return success(ser_vendor(v), 201)


@app.route("/vendors/<vid>", methods=["GET"])
def get_vendor(vid):
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    return success(ser_vendor(find_or_404(db.vendors, vid)), 200)


@app.route("/vendors", methods=["GET"])
def list_vendors():
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    agency_id = flask_request.args.get("agency_id")
    items = [v for v in db.vendors.values()
             if agency_id is None or v["agency_id"] == agency_id]
    page, meta = paginate(sorted_by_created(items))
    return success([ser_vendor(v) for v in page], 200, meta)


@app.route("/vendors/<vid>/authorize", methods=["POST"])
def authorize_vendor(vid):
    role, _ = auth()
    require_role(role, {CLERK})
    v = find_or_404(db.vendors, vid)
    if v["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Vendor is not PENDING.")
    v["status"] = "AUTHORIZED"
    touch(v)
    return success(ser_vendor(v), 200)


@app.route("/vendors/<vid>/record-violation", methods=["POST"])
def vendor_record_violation(vid):
    role, _ = auth()
    require_role(role, {CLERK})
    v = find_or_404(db.vendors, vid)
    body = get_body()
    points = require_int(body, "points", minimum=0)
    if v["status"] != "AUTHORIZED":
        raise err(ERR_INVALID_STATE, "Vendor is not AUTHORIZED.")
    services.record_violation(v, points)
    return success(ser_vendor(v), 200)


@app.route("/vendors/<vid>/reinstate", methods=["POST"])
def reinstate_vendor(vid):
    role, _ = auth()
    require_role(role, {CLERK})
    v = find_or_404(db.vendors, vid)
    if v["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "Vendor is not SUSPENDED.")
    v["status"] = "AUTHORIZED"
    v["violation_points"] = 0
    touch(v)
    return success(ser_vendor(v), 200)


@app.route("/vendors/<vid>/terminate", methods=["POST"])
def terminate_vendor(vid):
    role, _ = auth()
    require_role(role, {CLERK})
    v = find_or_404(db.vendors, vid)
    if v["status"] not in ("AUTHORIZED", "SUSPENDED"):
        raise err(ERR_INVALID_STATE, "Vendor cannot be terminated from its current state.")
    v["status"] = "TERMINATED"
    touch(v)
    return success(ser_vendor(v), 200)


# ============================================================================
# Household
# ============================================================================
@app.route("/households", methods=["POST"])
def create_household():
    role, _ = auth()
    require_role(role, {CLERK})
    body = get_body()
    agency_id = require_str(body, "agency_id")
    find_or_404(db.agencies, agency_id)
    household_size = require_int(body, "household_size", minimum=0)
    pregnancy_count = optional_int(body, "pregnancy_count", 0, minimum=0)
    adjunctive_program = optional_enum(body, "adjunctive_program", ADJUNCTIVE, "NONE")
    h = new_common()
    h.update({"agency_id": agency_id, "household_size": household_size,
              "pregnancy_count": pregnancy_count,
              "adjunctive_program": adjunctive_program})
    db.households[h["id"]] = h
    return success(ser_household(h), 201)


@app.route("/households/<hid>", methods=["GET"])
def get_household(hid):
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    return success(ser_household(find_or_404(db.households, hid)), 200)


@app.route("/households", methods=["GET"])
def list_households():
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    agency_id = flask_request.args.get("agency_id")
    items = [h for h in db.households.values()
             if agency_id is None or h["agency_id"] == agency_id]
    page, meta = paginate(sorted_by_created(items))
    return success([ser_household(h) for h in page], 200, meta)


# ============================================================================
# Participant
# ============================================================================
@app.route("/participants", methods=["POST"])
def create_participant():
    role, _ = auth()
    require_role(role, {CLERK})
    body = get_body()
    household_id = require_str(body, "household_id")
    household = find_or_404(db.households, household_id)
    full_name = require_str(body, "full_name")
    ssn_last4 = require_str(body, "ssn_last4")
    category = require_enum(body, "category", CATEGORIES)
    bf_opt_in = body.get("breastfeeding_opt_in", False)
    if bf_opt_in is None:
        bf_opt_in = False
    if not isinstance(bf_opt_in, bool):
        raise err(ERR_INVALID_REQUEST, "breastfeeding_opt_in must be a boolean.")
    p = new_common()
    p.update({
        "household_id": household_id, "agency_id": household["agency_id"],
        "full_name": full_name, "ssn_last4": ssn_last4, "category": category,
        "breastfeeding_opt_in": bf_opt_in, "status": "APPLICANT",
        "priority_level": None,
    })
    db.participants[p["id"]] = p
    return success(ser_participant(p), 201)


@app.route("/participants/<pid>", methods=["GET"])
def get_participant(pid):
    role, user_id = auth()
    require_role(role, {CLERK, CPA, PARTICIPANT})
    p = find_or_404(db.participants, pid)
    if role == PARTICIPANT and user_id != p["id"]:
        raise err(ERR_FORBIDDEN, "Participants may only read their own record.")
    return success(ser_participant(p), 200)


@app.route("/participants", methods=["GET"])
def list_participants():
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    household_id = flask_request.args.get("household_id")
    items = [p for p in db.participants.values()
             if household_id is None or p["household_id"] == household_id]
    page, meta = paginate(sorted_by_created(items))
    return success([ser_participant(p) for p in page], 200, meta)


# ============================================================================
# Application
# ============================================================================
@app.route("/applications", methods=["POST"])
def create_application():
    role, _ = auth()
    require_role(role, {CLERK})
    body = get_body()
    participant_id = require_str(body, "participant_id")
    find_or_404(db.participants, participant_id)
    income_method = optional_enum(body, "income_method", INCOME_METHODS, "ANNUALIZE_RECENT")
    a = new_common()
    a.update({
        "participant_id": participant_id, "income_method": income_method,
        "annual_income_determined": None, "income_limit": None,
        "income_eligible": None, "determined_by_user_id": None,
        "certified_by_user_id": None, "risk_factor_codes": [],
        "total_risk_score": None, "risk_eligible": None, "status": "DRAFT",
    })
    db.applications[a["id"]] = a
    return success(ser_application(a), 201)


@app.route("/applications/<aid>", methods=["GET"])
def get_application(aid):
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    return success(ser_application(find_or_404(db.applications, aid)), 200)


@app.route("/applications", methods=["GET"])
def list_applications():
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    participant_id = flask_request.args.get("participant_id")
    items = [a for a in db.applications.values()
             if participant_id is None or a["participant_id"] == participant_id]
    page, meta = paginate(sorted_by_created(items))
    return success([ser_application(a) for a in page], 200, meta)


# ============================================================================
# IncomeRecord
# ============================================================================
@app.route("/income-records", methods=["POST"])
def create_income_record():
    role, _ = auth()
    require_role(role, {CLERK})
    body = get_body()
    application_id = require_str(body, "application_id")
    application = find_or_404(db.applications, application_id)
    gross = require_int(body, "gross_amount_cents", minimum=0)
    freq = require_enum(body, "pay_frequency", PAY_FREQUENCIES)
    seq = len([r for r in db.income_records.values()
               if r["application_id"] == application_id])
    r = new_common(with_version=False)
    r.update({"application_id": application_id, "gross_amount_cents": gross,
              "pay_frequency": freq, "sequence_index": seq})
    db.income_records[r["id"]] = r
    return success(ser_income_record(r), 201)


@app.route("/income-records/<rid>", methods=["GET"])
def get_income_record(rid):
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    return success(ser_income_record(find_or_404(db.income_records, rid)), 200)


@app.route("/income-records", methods=["GET"])
def list_income_records():
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    application_id = flask_request.args.get("application_id")
    items = [r for r in db.income_records.values()
             if application_id is None or r["application_id"] == application_id]
    page, meta = paginate(sorted_by_created(items))
    return success([ser_income_record(r) for r in page], 200, meta)


# ============================================================================
# Application transitions
# ============================================================================
@app.route("/applications/<aid>/determine-income", methods=["POST"])
def determine_income(aid):
    role, user_id = auth()
    require_role(role, {CLERK})
    application = find_or_404(db.applications, aid)
    if application["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Application is not DRAFT.")
    records = [r for r in db.income_records.values()
               if r["application_id"] == aid]
    if not records:
        raise err(ERR_NO_INCOME_RECORDS, "No income records attached to the application.")

    participant = db.participants[application["participant_id"]]
    household = db.households[participant["household_id"]]
    adjusted_size = household["household_size"] + household["pregnancy_count"]

    limit = calc.income_limit(adjusted_size)
    annual = calc.annual_income_determined(records, application["income_method"])
    eligible = calc.income_eligible(annual, limit, household["adjunctive_program"])

    application["income_limit"] = limit
    application["annual_income_determined"] = annual
    application["income_eligible"] = eligible
    application["determined_by_user_id"] = user_id
    application["status"] = "INCOME_DETERMINED"
    touch(application)
    return success(ser_application(application), 200)


@app.route("/applications/<aid>/assess-risk", methods=["POST"])
def assess_risk(aid):
    role, _ = auth()
    require_role(role, {CPA})
    application = find_or_404(db.applications, aid)
    body = get_body()
    codes = require(body, "risk_factor_codes")
    if not isinstance(codes, list):
        raise err(ERR_INVALID_REQUEST, "risk_factor_codes must be an array.")
    for c in codes:
        if not isinstance(c, str) or c not in RISK_CODES:
            raise err(ERR_INVALID_REQUEST, "Invalid risk factor code: {}".format(c))
    if application["status"] != "INCOME_DETERMINED":
        raise err(ERR_INVALID_STATE, "Application is not INCOME_DETERMINED.")

    participant = db.participants[application["participant_id"]]
    total, eligible = calc.nutritional_risk(codes, participant["category"])
    application["risk_factor_codes"] = codes
    application["total_risk_score"] = total
    application["risk_eligible"] = eligible
    application["status"] = "RISK_ASSESSED"
    touch(application)
    return success(ser_application(application), 200)


def _has_dual_participation(participant):
    """True if another participant in a DIFFERENT household with identical
    (full_name, ssn_last4) holds an ACTIVE certification (PRD §3.5)."""
    for other in db.participants.values():
        if other["id"] == participant["id"]:
            continue
        if other["household_id"] == participant["household_id"]:
            continue
        if (other["full_name"] != participant["full_name"]
                or other["ssn_last4"] != participant["ssn_last4"]):
            continue
        for cert in db.certifications.values():
            if cert["participant_id"] == other["id"] and cert["status"] == "ACTIVE":
                return True
    return False


@app.route("/applications/<aid>/approve", methods=["POST"])
def approve_application(aid):
    role, user_id = auth()
    require_role(role, {CPA})
    application = find_or_404(db.applications, aid)
    if application["status"] != "RISK_ASSESSED":
        raise err(ERR_INVALID_STATE, "Application is not RISK_ASSESSED.")

    participant = db.participants[application["participant_id"]]
    household = db.households[participant["household_id"]]
    agency = db.agencies[participant["agency_id"]]

    # Domain-rule order (PRD §2.9): SoD -> dual -> income -> risk -> caseload
    if user_id == application["determined_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES,
                  "Certifier must differ from the income determiner.")
    if _has_dual_participation(participant):
        raise err(ERR_DUAL_PARTICIPATION,
                  "Another participant with the same identity holds an ACTIVE certification.")
    if not application["income_eligible"]:
        raise err(ERR_INCOME_INELIGIBLE, "Application is not income eligible.")
    if not application["risk_eligible"]:
        raise err(ERR_RISK_INELIGIBLE, "Application is not risk eligible.")
    if agency["active_caseload_count"] >= agency["caseload_cap"]:
        raise err(ERR_CASELOAD_EXCEEDED, "Agency caseload cap reached.")

    services.approve_cascade(application, participant, household, agency, user_id)
    return success(ser_application(application), 200)


@app.route("/applications/<aid>/deny", methods=["POST"])
def deny_application(aid):
    role, _ = auth()
    require_role(role, {CPA})
    application = find_or_404(db.applications, aid)
    if application["status"] != "RISK_ASSESSED":
        raise err(ERR_INVALID_STATE, "Application is not RISK_ASSESSED.")
    application["status"] = "DENIED"
    touch(application)
    return success(ser_application(application), 200)


# ============================================================================
# Certification
# ============================================================================
@app.route("/certifications/<cid>", methods=["GET"])
def get_certification(cid):
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    return success(ser_certification(find_or_404(db.certifications, cid)), 200)


@app.route("/certifications", methods=["GET"])
def list_certifications():
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    a = flask_request.args
    participant_id = a.get("participant_id")
    application_id = a.get("application_id")
    items = list(db.certifications.values())
    if participant_id is not None:
        items = [c for c in items if c["participant_id"] == participant_id]
    if application_id is not None:
        items = [c for c in items if c["application_id"] == application_id]
    page, meta = paginate(sorted_by_created(items))
    return success([ser_certification(c) for c in page], 200, meta)


@app.route("/certifications/<cid>/suspend", methods=["POST"])
def suspend_certification(cid):
    role, _ = auth()
    require_role(role, {CPA})
    cert = find_or_404(db.certifications, cid)
    if cert["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Certification is not ACTIVE.")
    services.suspend_cert(cert)
    return success(ser_certification(cert), 200)


@app.route("/certifications/<cid>/reinstate", methods=["POST"])
def reinstate_certification(cid):
    role, _ = auth()
    require_role(role, {CPA})
    cert = find_or_404(db.certifications, cid)
    if cert["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "Certification is not SUSPENDED.")
    participant = db.participants[cert["participant_id"]]
    agency = db.agencies[participant["agency_id"]]
    if not (agency["_current_utc_dt"] < cert["_period_end_dt"]):
        raise err(ERR_CERT_PERIOD_ENDED, "Certification period has ended.")
    services.reinstate_cert(cert)
    return success(ser_certification(cert), 200)


@app.route("/certifications/<cid>/terminate", methods=["POST"])
def terminate_certification(cid):
    role, _ = auth()
    require_role(role, {CPA})
    cert = find_or_404(db.certifications, cid)
    if cert["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err(ERR_INVALID_STATE, "Certification is not ACTIVE or SUSPENDED.")
    participant = db.participants[cert["participant_id"]]
    agency = db.agencies[participant["agency_id"]]
    services.terminate_cert(cert, agency)
    return success(ser_certification(cert), 200)


# ============================================================================
# FoodPrescription (OCC on participant version)
# ============================================================================
@app.route("/food-prescriptions", methods=["POST"])
def create_food_prescription():
    role, _ = auth()
    require_role(role, {CPA})
    body = get_body()
    certification_id = require_str(body, "certification_id")
    cert = find_or_404(db.certifications, certification_id)
    # well-formedness of body fields
    line_items = require(body, "line_items")
    if not isinstance(line_items, list) or not line_items:
        raise err(ERR_INVALID_REQUEST, "line_items must be a non-empty array.")
    parsed_items = []
    for item in line_items:
        if not isinstance(item, dict):
            raise err(ERR_INVALID_REQUEST, "Each line item must be an object.")
        fc = item.get("food_category")
        ru = item.get("requested_units")
        if not isinstance(fc, str) or fc not in calc.FOOD_CATEGORIES:
            raise err(ERR_INVALID_REQUEST, "Invalid food_category in line item.")
        if isinstance(ru, bool) or not isinstance(ru, int) or ru < 0:
            raise err(ERR_INVALID_REQUEST, "requested_units must be a non-negative integer.")
        parsed_items.append({"food_category": fc, "requested_units": ru})
    issuance_mode = optional_enum(body, "issuance_mode", ISSUANCE_MODES, "FULL")
    expected_version = require_int(body, "expected_participant_version")

    participant = db.participants[cert["participant_id"]]

    # OCC (priority 5) before state checks
    if expected_version != participant["version"]:
        raise err(ERR_STALE_VERSION, "Stale participant version.")

    # category-food cap check (ERR_CATEGORY_FOOD_MISMATCH)
    caps = calc.CATEGORY_CAP[participant["category"]]
    for item in parsed_items:
        if item["food_category"] not in caps:
            raise err(ERR_CATEGORY_FOOD_MISMATCH,
                      "Food category not allowed for participant category.")

    agency = db.agencies[participant["agency_id"]]
    value_cents, issued_by_cat = calc.prescribed_value(
        parsed_items, participant["category"], issuance_mode, agency["_current_utc_dt"])

    acc = services.ebt_for_participant(participant["id"])

    presc = new_common()
    presc.update({
        "certification_id": certification_id,
        "participant_id": participant["id"],
        "issuance_mode": issuance_mode,
        "line_items": parsed_items,
        "prescribed_value_cents": value_cents,
        "status": "ISSUED",
        "_issued_units": dict(issued_by_cat),
        "_remaining_units": dict(issued_by_cat),
    })
    db.food_prescriptions[presc["id"]] = presc

    if acc is not None:
        services.issue_prescription(presc, acc)

    # OCC-guarded write bumps the participant version (PRD §3.7)
    touch(participant)
    return success(ser_food_prescription(presc), 201)


@app.route("/food-prescriptions/<pid>", methods=["GET"])
def get_food_prescription(pid):
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    return success(ser_food_prescription(find_or_404(db.food_prescriptions, pid)), 200)


@app.route("/food-prescriptions", methods=["GET"])
def list_food_prescriptions():
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    a = flask_request.args
    certification_id = a.get("certification_id")
    participant_id = a.get("participant_id")
    items = list(db.food_prescriptions.values())
    if certification_id is not None:
        items = [p for p in items if p["certification_id"] == certification_id]
    if participant_id is not None:
        items = [p for p in items if p["participant_id"] == participant_id]
    page, meta = paginate(sorted_by_created(items))
    return success([ser_food_prescription(p) for p in page], 200, meta)


# ============================================================================
# EBT
# ============================================================================
@app.route("/ebt-accounts/<eid>", methods=["GET"])
def get_ebt_account(eid):
    role, user_id = auth()
    require_role(role, {CLERK, CPA, PARTICIPANT})
    acc = find_or_404(db.ebt_accounts, eid)
    if role == PARTICIPANT and user_id != acc["participant_id"]:
        raise err(ERR_FORBIDDEN, "Participants may only read their own EBT account.")
    return success(ser_ebt(acc), 200)


@app.route("/ebt-accounts", methods=["GET"])
def list_ebt_accounts():
    role, user_id = auth()
    require_role(role, {CLERK, CPA, PARTICIPANT})
    participant_id = flask_request.args.get("participant_id")
    items = list(db.ebt_accounts.values())
    if participant_id is not None:
        items = [a for a in items if a["participant_id"] == participant_id]
    if role == PARTICIPANT:
        items = [a for a in items if a["participant_id"] == user_id]
    page, meta = paginate(sorted_by_created(items))
    return success([ser_ebt(a) for a in page], 200, meta)


# ============================================================================
# Redemption
# ============================================================================
@app.route("/redemptions", methods=["POST"])
def create_redemption():
    role, user_id = auth()
    require_role(role, {PARTICIPANT, CLERK})
    body = get_body()
    ebt_account_id = require_str(body, "ebt_account_id")
    acc = find_or_404(db.ebt_accounts, ebt_account_id)
    vendor_id = require_str(body, "vendor_id")
    vendor = find_or_404(db.vendors, vendor_id)
    food_category = require_enum(body, "food_category", calc.FOOD_CATEGORIES)
    units = require_int(body, "units", minimum=1)

    # participant ownership (PRD §2.1)
    if role == PARTICIPANT and user_id != acc["participant_id"]:
        raise err(ERR_FORBIDDEN, "Participants may only redeem against their own account.")

    # cross-entity gates (PRD §3.8): owning cert ACTIVE -> EBT OPEN -> vendor
    # AUTHORIZED -> sufficient balance. Domain order (§2.9): vendor before balance.
    cert = _active_cert_for_participant(acc["participant_id"])
    if cert is None or cert["status"] != "ACTIVE":
        raise err(ERR_CERT_NOT_ACTIVE, "Owning certification is not ACTIVE.")
    if acc["status"] != "OPEN":
        raise err(ERR_EBT_FROZEN, "EBT account is FROZEN.")
    if vendor["status"] != "AUTHORIZED":
        raise err(ERR_VENDOR_NOT_AUTHORIZED, "Vendor is not AUTHORIZED.")
    if units > acc["balance_units"].get(food_category, 0):
        raise err(ERR_INSUFFICIENT_BALANCE, "Insufficient balance for the food category.")

    seq = len([r for r in db.redemptions.values()
               if r["ebt_account_id"] == ebt_account_id])
    value_cents = units * calc.UNIT_PRICE_CENTS[food_category]
    r = new_common(with_version=False)
    r.update({"ebt_account_id": ebt_account_id, "vendor_id": vendor_id,
              "food_category": food_category, "units": units,
              "value_cents": value_cents, "sequence_index": seq})
    db.redemptions[r["id"]] = r

    services.apply_redemption(acc, food_category, units)
    return success(ser_redemption(r), 201)


def _active_cert_for_participant(participant_id):
    """The participant's current ACTIVE certification, if any (latest by creation)."""
    certs = [c for c in db.certifications.values()
             if c["participant_id"] == participant_id and c["status"] == "ACTIVE"]
    if not certs:
        return None
    certs.sort(key=lambda c: c["_created_seq"])
    return certs[-1]


@app.route("/redemptions/<rid>", methods=["GET"])
def get_redemption(rid):
    role, user_id = auth()
    require_role(role, {CLERK, CPA, PARTICIPANT})
    r = find_or_404(db.redemptions, rid)
    if role == PARTICIPANT:
        acc = db.ebt_accounts.get(r["ebt_account_id"])
        if acc is None or user_id != acc["participant_id"]:
            raise err(ERR_FORBIDDEN, "Participants may only read their own redemptions.")
    return success(ser_redemption(r), 200)


@app.route("/redemptions", methods=["GET"])
def list_redemptions():
    role, user_id = auth()
    require_role(role, {CLERK, CPA, PARTICIPANT})
    a = flask_request.args
    ebt_account_id = a.get("ebt_account_id")
    vendor_id = a.get("vendor_id")
    items = list(db.redemptions.values())
    if ebt_account_id is not None:
        items = [r for r in items if r["ebt_account_id"] == ebt_account_id]
    if vendor_id is not None:
        items = [r for r in items if r["vendor_id"] == vendor_id]
    if role == PARTICIPANT:
        own_accs = {acc["id"] for acc in db.ebt_accounts.values()
                    if acc["participant_id"] == user_id}
        items = [r for r in items if r["ebt_account_id"] in own_accs]
    page, meta = paginate(sorted_by_created(items))
    return success([ser_redemption(r) for r in page], 200, meta)


# ============================================================================
# ClinicAppointment (OCC on clinic version)
# ============================================================================
def _intervals_overlap_half_open(s1, e1, s2, e2):
    # collide if s1 < e2 and s2 < e1 (strict; touching endpoints do not collide)
    return s1 < e2 and s2 < e1


def _clinic_has_overlap(clinic_id, start_dt, end_dt, exclude_id=None):
    for appt in db.clinic_appointments.values():
        if appt["clinic_id"] != clinic_id:
            continue
        if appt["status"] not in ("SCHEDULED", "RESCHEDULED"):
            continue
        if exclude_id is not None and appt["id"] == exclude_id:
            continue
        if _intervals_overlap_half_open(start_dt, end_dt,
                                        appt["_start_dt"], appt["_end_dt"]):
            return True
    return False


@app.route("/clinic-appointments", methods=["POST"])
def create_clinic_appointment():
    role, _ = auth()
    require_role(role, {CLERK})
    body = get_body()
    clinic_id = require_str(body, "clinic_id")
    clinic = find_or_404(db.clinics, clinic_id)
    participant_id = require_str(body, "participant_id")
    find_or_404(db.participants, participant_id)
    purpose = require_enum(body, "purpose", APPT_PURPOSES)
    start_dt = parse_iso(require(body, "start_utc"), "start_utc")
    end_dt = parse_iso(require(body, "end_utc"), "end_utc")
    if not (start_dt < end_dt):
        raise err(ERR_INVALID_REQUEST, "start_utc must be before end_utc.")
    expected_version = require_int(body, "expected_clinic_version")

    # OCC (priority 5)
    if expected_version != clinic["version"]:
        raise err(ERR_STALE_VERSION, "Stale clinic version.")

    # overlap (priority 11)
    if _clinic_has_overlap(clinic_id, start_dt, end_dt):
        raise err(ERR_APPOINTMENT_OVERLAP, "Appointment interval collides on the clinic.")

    appt = new_common()
    appt.update({
        "clinic_id": clinic_id, "participant_id": participant_id, "purpose": purpose,
        "start_utc": iso_ms(start_dt), "end_utc": iso_ms(end_dt),
        "_start_dt": start_dt, "_end_dt": end_dt, "status": "SCHEDULED",
    })
    db.clinic_appointments[appt["id"]] = appt
    touch(clinic)  # scheduling bumps the clinic version
    return success(ser_appointment(appt), 201)


@app.route("/clinic-appointments/<aid>", methods=["GET"])
def get_clinic_appointment(aid):
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    return success(ser_appointment(find_or_404(db.clinic_appointments, aid)), 200)


@app.route("/clinic-appointments", methods=["GET"])
def list_clinic_appointments():
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    a = flask_request.args
    clinic_id = a.get("clinic_id")
    participant_id = a.get("participant_id")
    items = list(db.clinic_appointments.values())
    if clinic_id is not None:
        items = [x for x in items if x["clinic_id"] == clinic_id]
    if participant_id is not None:
        items = [x for x in items if x["participant_id"] == participant_id]
    page, meta = paginate(sorted_by_created(items))
    return success([ser_appointment(x) for x in page], 200, meta)


@app.route("/clinic-appointments/<aid>", methods=["PATCH"])
def reschedule_clinic_appointment(aid):
    role, _ = auth()
    require_role(role, {CLERK})
    appt = find_or_404(db.clinic_appointments, aid)
    body = get_body()
    start_dt = parse_iso(require(body, "start_utc"), "start_utc")
    end_dt = parse_iso(require(body, "end_utc"), "end_utc")
    if not (start_dt < end_dt):
        raise err(ERR_INVALID_REQUEST, "start_utc must be before end_utc.")
    if appt["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Appointment is not SCHEDULED.")
    if _clinic_has_overlap(appt["clinic_id"], start_dt, end_dt, exclude_id=appt["id"]):
        raise err(ERR_APPOINTMENT_OVERLAP, "New interval collides on the clinic.")
    appt["start_utc"] = iso_ms(start_dt)
    appt["end_utc"] = iso_ms(end_dt)
    appt["_start_dt"] = start_dt
    appt["_end_dt"] = end_dt
    appt["status"] = "RESCHEDULED"
    touch(appt)
    return success(ser_appointment(appt), 200)


@app.route("/clinic-appointments/<aid>/confirm", methods=["POST"])
def confirm_clinic_appointment(aid):
    role, _ = auth()
    require_role(role, {CLERK})
    appt = find_or_404(db.clinic_appointments, aid)
    if appt["status"] != "RESCHEDULED":
        raise err(ERR_INVALID_STATE, "Appointment is not RESCHEDULED.")
    appt["status"] = "SCHEDULED"
    touch(appt)
    return success(ser_appointment(appt), 200)


@app.route("/clinic-appointments/<aid>/complete", methods=["POST"])
def complete_clinic_appointment(aid):
    role, _ = auth()
    require_role(role, {CPA})
    appt = find_or_404(db.clinic_appointments, aid)
    if appt["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Appointment is not SCHEDULED.")
    participant = db.participants[appt["participant_id"]]
    if participant["status"] not in ("APPLICANT", "ACTIVE"):
        raise err(ERR_PARTICIPANT_NOT_SERVICEABLE,
                  "Participant is not serviceable.")
    appt["status"] = "COMPLETED"
    touch(appt)
    return success(ser_appointment(appt), 200)


@app.route("/clinic-appointments/<aid>/no-show", methods=["POST"])
def no_show_clinic_appointment(aid):
    role, _ = auth()
    require_role(role, {CLERK})
    appt = find_or_404(db.clinic_appointments, aid)
    if appt["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Appointment is not SCHEDULED.")
    participant = db.participants[appt["participant_id"]]
    agency = db.agencies[participant["agency_id"]]
    if not (agency["_current_utc_dt"] >= appt["_end_dt"]):
        raise err(ERR_APPOINTMENT_NOT_PAST, "Appointment is not yet past.")
    appt["status"] = "NO_SHOW"
    touch(appt)
    return success(ser_appointment(appt), 200)


@app.route("/clinic-appointments/<aid>/cancel", methods=["POST"])
def cancel_clinic_appointment(aid):
    role, _ = auth()
    require_role(role, {CLERK})
    appt = find_or_404(db.clinic_appointments, aid)
    if appt["status"] not in ("SCHEDULED", "RESCHEDULED"):
        raise err(ERR_INVALID_STATE, "Appointment is not SCHEDULED or RESCHEDULED.")
    appt["status"] = "CANCELLED"
    touch(appt)
    return success(ser_appointment(appt), 200)


# ============================================================================
# PeerSupportSession (counselor buffered overlap)
# ============================================================================
def _gap_minutes(s1, e1, s2, e2):
    """Minutes between two closed intervals; 0 if they overlap at all."""
    if s1 <= e2 and s2 <= e1:
        return 0
    if e1 < s2:
        return (s2 - e1).total_seconds() / 60.0
    return (s1 - e2).total_seconds() / 60.0


def _counselor_has_collision(counselor_id, start_dt, end_dt):
    for sess in db.peer_sessions.values():
        if sess["peer_counselor_id"] != counselor_id:
            continue
        if sess["status"] != "SCHEDULED":
            continue
        gap = _gap_minutes(start_dt, end_dt, sess["_start_dt"], sess["_end_dt"])
        if gap < calc.SESSION_BUFFER_MINUTES:  # strict; exactly buffer is allowed
            return True
    return False


@app.route("/peer-sessions", methods=["POST"])
def create_peer_session():
    role, _ = auth()
    require_role(role, {CPA})
    body = get_body()
    participant_id = require_str(body, "participant_id")
    find_or_404(db.participants, participant_id)
    counselor_id = require_str(body, "peer_counselor_id")
    start_dt = parse_iso(require(body, "start_utc"), "start_utc")
    end_dt = parse_iso(require(body, "end_utc"), "end_utc")
    if not (start_dt < end_dt):
        raise err(ERR_INVALID_REQUEST, "start_utc must be before end_utc.")
    if _counselor_has_collision(counselor_id, start_dt, end_dt):
        raise err(ERR_APPOINTMENT_OVERLAP, "Session collides within the buffer on the counselor.")
    s = new_common()
    s.update({
        "participant_id": participant_id, "peer_counselor_id": counselor_id,
        "start_utc": iso_ms(start_dt), "end_utc": iso_ms(end_dt),
        "_start_dt": start_dt, "_end_dt": end_dt, "status": "SCHEDULED",
    })
    db.peer_sessions[s["id"]] = s
    return success(ser_peer_session(s), 201)


@app.route("/peer-sessions/<sid>", methods=["GET"])
def get_peer_session(sid):
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    return success(ser_peer_session(find_or_404(db.peer_sessions, sid)), 200)


@app.route("/peer-sessions", methods=["GET"])
def list_peer_sessions():
    role, _ = auth()
    require_role(role, {CLERK, CPA})
    participant_id = flask_request.args.get("participant_id")
    items = [s for s in db.peer_sessions.values()
             if participant_id is None or s["participant_id"] == participant_id]
    page, meta = paginate(sorted_by_created(items))
    return success([ser_peer_session(s) for s in page], 200, meta)


@app.route("/peer-sessions/<sid>/complete", methods=["POST"])
def complete_peer_session(sid):
    role, _ = auth()
    require_role(role, {CPA})
    s = find_or_404(db.peer_sessions, sid)
    if s["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Session is not SCHEDULED.")
    s["status"] = "COMPLETED"
    touch(s)
    return success(ser_peer_session(s), 200)


@app.route("/peer-sessions/<sid>/cancel", methods=["POST"])
def cancel_peer_session(sid):
    role, _ = auth()
    require_role(role, {CPA})
    s = find_or_404(db.peer_sessions, sid)
    if s["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Session is not SCHEDULED.")
    s["status"] = "CANCELLED"
    touch(s)
    return success(ser_peer_session(s), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
