"""Clock control, guests, hosts and jurisdiction rules."""

from flask import Blueprint, g, request

import calc
import views
from core import (ROLE_ADJUDICATOR, ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_GUEST,
                  ROLE_HOST, ALL_ROLES, body_json, db, fail, iso, new_row,
                  now, object_response, opt_string, paginate, qs, qs_bool,
                  req_bool, req_country_code, req_dt, req_enum, req_int,
                  req_number, req_string, require_auth, set_now, touch)

bp = Blueprint("accounts", __name__)


# ---------------------------------------------------------------------------
# Logical clock control (PRD 2.5) -- a test-harness facility, not under
# /rentals.  It mutates no entity.
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role = request.headers.get("X-User-Role")
    if role is not None and role.strip() != "":
        require_auth(ROLE_ADMIN)
    body = body_json()
    value = req_dt(body, "current_utc")
    set_now(value)
    return object_response({"current_utc": value}), 200


# ---------------------------------------------------------------------------
# Guests (PRD 3.2)
# ---------------------------------------------------------------------------

def email_taken(collection, email):
    lowered = email.strip().lower()
    for row in collection.values():
        if row["email"].strip().lower() == lowered:
            return True
    return False


@bp.route("/rentals/guests", methods=["POST"])
def create_guest():
    require_auth(ROLE_ADMIN)
    body = body_json()
    full_name = req_string(body, "full_name")
    email = req_string(body, "email")
    country_code = req_country_code(body, "country_code")
    if email_taken(db.guests, email):
        fail("ERR_EMAIL_ALREADY_REGISTERED",
             "A guest with this email already exists")
    row = new_row()
    row.update({
        "full_name": full_name,
        "email": email,
        "country_code": country_code,
        "payment_risk_signal": "CLEAN",
        "chargeback_count": 0,
        "approved_claim_count": 0,
    })
    db.guests[row["id"]] = row
    return object_response(views.guest_view(row)), 201


@bp.route("/rentals/guests/<gid>", methods=["GET"])
def get_guest(gid):
    require_auth(*ALL_ROLES)
    row = db.guests.get(gid)
    if row is None:
        fail("ERR_GUEST_NOT_FOUND", "Guest not found")
    return object_response(views.guest_view(row)), 200


@bp.route("/rentals/guests", methods=["GET"])
def list_guests():
    require_auth(ROLE_ADJUDICATOR, ROLE_COMPLIANCE, ROLE_ADMIN)
    risk_tier = qs("risk_tier")
    verification_state = qs("verification_state")
    rows = list(db.guests.values())
    if risk_tier is not None:
        rows = [r for r in rows if calc.risk_tier(r) == risk_tier]
    if verification_state is not None:
        rows = [r for r in rows
                if calc.verification_state(r) == verification_state]
    return paginate(rows, views.guest_view), 200


@bp.route("/rentals/guests/<gid>/risk-profile", methods=["GET"])
def guest_risk_profile(gid):
    require_auth(ROLE_ADJUDICATOR, ROLE_COMPLIANCE, ROLE_ADMIN)
    row = db.guests.get(gid)
    if row is None:
        fail("ERR_GUEST_NOT_FOUND", "Guest not found")
    return object_response(views.risk_profile_view(row)), 200


@bp.route("/rentals/guests/<gid>/payment-signals", methods=["POST"])
def record_payment_signal(gid):
    require_auth(ROLE_ADMIN)
    body = body_json()
    signal = req_enum(body, "payment_risk_signal",
                      ("CLEAN", "WATCH", "ADVERSE"))
    chargeback_count = req_int(body, "chargeback_count", minimum=0)
    row = db.guests.get(gid)
    if row is None:
        fail("ERR_GUEST_NOT_FOUND", "Guest not found")
    row["payment_risk_signal"] = signal
    row["chargeback_count"] = chargeback_count
    touch(row)
    calc.apply_risk_cascade(row)
    return object_response(views.guest_view(row)), 200


# ---------------------------------------------------------------------------
# Hosts (PRD 3.2)
# ---------------------------------------------------------------------------

@bp.route("/rentals/hosts", methods=["POST"])
def create_host():
    require_auth(ROLE_ADMIN)
    body = body_json()
    legal_name = req_string(body, "legal_name")
    email = req_string(body, "email")
    if email_taken(db.hosts, email):
        fail("ERR_EMAIL_ALREADY_REGISTERED",
             "A host with this email already exists")
    row = new_row()
    row.update({
        "legal_name": legal_name,
        "email": email,
        "payout_hold": False,
    })
    db.hosts[row["id"]] = row
    return object_response(views.host_view(row)), 201


@bp.route("/rentals/hosts/<hid>", methods=["GET"])
def get_host(hid):
    require_auth(ROLE_HOST, ROLE_ADJUDICATOR, ROLE_COMPLIANCE, ROLE_ADMIN)
    row = db.hosts.get(hid)
    if row is None:
        fail("ERR_HOST_NOT_FOUND", "Host not found")
    return object_response(views.host_view(row)), 200


@bp.route("/rentals/hosts", methods=["GET"])
def list_hosts():
    require_auth(ROLE_ADJUDICATOR, ROLE_COMPLIANCE, ROLE_ADMIN)
    payout_hold = qs_bool("payout_hold")
    rows = list(db.hosts.values())
    if payout_hold is not None:
        rows = [r for r in rows if r["payout_hold"] is payout_hold]
    return paginate(rows, views.host_view), 200


# ---------------------------------------------------------------------------
# Jurisdiction rules (PRD 3.1) -- immutable, no version, no updated_at.
# ---------------------------------------------------------------------------

@bp.route("/rentals/jurisdiction-rules", methods=["POST"])
def create_jurisdiction_rule():
    require_auth(ROLE_COMPLIANCE, ROLE_ADMIN)
    body = body_json()
    code = req_string(body, "jurisdiction_code")
    min_stay_nights = req_int(body, "min_stay_nights", minimum=1)
    max_occupancy_cap = req_int(body, "max_occupancy_cap", minimum=1)
    events_prohibited = req_bool(body, "events_prohibited")
    registration_required = req_bool(body, "registration_required")
    indoor_camera_allowed = req_bool(body, "indoor_camera_allowed")
    indoor_audio_allowed = req_bool(body, "indoor_audio_allowed")
    sensor_notice_required = req_bool(body, "sensor_notice_required")
    noise_threshold_db = req_number(body, "noise_threshold_db")
    if noise_threshold_db <= 0:
        fail("ERR_INVALID_REQUEST", "noise_threshold_db must be greater than 0")
    for existing in db.jurisdiction_rules.values():
        if existing["jurisdiction_code"] == code:
            fail("ERR_JURISDICTION_CODE_TAKEN",
                 "This jurisdiction_code is already registered")
    row = new_row(with_version=False)
    row.update({
        "jurisdiction_code": code,
        "min_stay_nights": min_stay_nights,
        "max_occupancy_cap": max_occupancy_cap,
        "events_prohibited": events_prohibited,
        "registration_required": registration_required,
        "indoor_camera_allowed": indoor_camera_allowed,
        "indoor_audio_allowed": indoor_audio_allowed,
        "sensor_notice_required": sensor_notice_required,
        "noise_threshold_db": noise_threshold_db,
    })
    db.jurisdiction_rules[row["id"]] = row
    return object_response(views.jurisdiction_rule_view(row)), 201


@bp.route("/rentals/jurisdiction-rules/<jid>", methods=["GET"])
def get_jurisdiction_rule(jid):
    require_auth(*ALL_ROLES)
    row = db.jurisdiction_rules.get(jid)
    if row is None:
        fail("ERR_JURISDICTION_RULE_NOT_FOUND", "Jurisdiction rule not found")
    return object_response(views.jurisdiction_rule_view(row)), 200


@bp.route("/rentals/jurisdiction-rules", methods=["GET"])
def list_jurisdiction_rules():
    require_auth(*ALL_ROLES)
    code = qs("jurisdiction_code")
    rows = list(db.jurisdiction_rules.values())
    if code is not None:
        rows = [r for r in rows if r["jurisdiction_code"] == code]
    return paginate(rows, views.jurisdiction_rule_view), 200
