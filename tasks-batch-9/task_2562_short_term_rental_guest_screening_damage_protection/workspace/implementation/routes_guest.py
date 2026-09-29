"""Identity documents and reservations (PRD 3.2 / 3.3 / 3.4)."""

from datetime import timedelta

from flask import Blueprint, g

import calc
import views
from core import (ALL_ROLES, ROLE_ADJUDICATOR, ROLE_ADMIN, ROLE_COMPLIANCE,
                  ROLE_GUEST, ROLE_HOST, at_time, body_json, db, fail, hours,
                  new_row, now, object_response, opt_string, paginate, qs,
                  req_bool, req_country_code, req_date, req_dt, req_enum,
                  req_int, req_string, require_auth, require_owner, touch)

bp = Blueprint("guests", __name__)

DOC_TYPES = ("GOVERNMENT_ID", "SELFIE", "ADDRESS_PROOF")
DOC_REJECT_REASONS = ("UNREADABLE", "NAME_MISMATCH", "SUSPECTED_FORGERY")
LIVE_STAY_STATES = ("REQUESTED", "CONFIRMED", "IN_STAY")


# ---------------------------------------------------------------------------
# Identity documents
# ---------------------------------------------------------------------------

@bp.route("/rentals/identity-documents", methods=["POST"])
def create_document():
    require_auth(ROLE_GUEST)
    body = body_json()
    guest_id = req_string(body, "guest_id")
    doc_type = req_enum(body, "doc_type", DOC_TYPES)
    issuing_country = req_country_code(body, "issuing_country")
    document_ref = req_string(body, "document_ref")
    expires_on = req_dt(body, "expires_on")

    guest_row = db.guests.get(guest_id)
    if guest_row is None:
        fail("ERR_GUEST_NOT_FOUND", "Guest not found")
    require_owner(guest_id)

    row = new_row()
    row.update({
        "guest_id": guest_id,
        "doc_type": doc_type,
        "issuing_country": issuing_country,
        "document_ref": document_ref,
        "expires_on": expires_on,
        "review_state": "PENDING",
        "reject_reason_code": None,
        "reviewed_by_user_id": None,
    })
    db.identity_documents[row["id"]] = row
    touch(guest_row)
    calc.apply_risk_cascade(guest_row)
    return object_response(views.document_view(row)), 201


@bp.route("/rentals/identity-documents/<did>", methods=["GET"])
def get_document(did):
    require_auth(ROLE_GUEST, ROLE_COMPLIANCE, ROLE_ADJUDICATOR, ROLE_ADMIN)
    row = db.identity_documents.get(did)
    if row is None:
        fail("ERR_DOCUMENT_NOT_FOUND", "Identity document not found")
    return object_response(views.document_view(row)), 200


@bp.route("/rentals/identity-documents", methods=["GET"])
def list_documents():
    require_auth(ROLE_GUEST, ROLE_COMPLIANCE, ROLE_ADJUDICATOR, ROLE_ADMIN)
    guest_id = qs("guest_id")
    review_state = qs("review_state")
    rows = list(db.identity_documents.values())
    if guest_id is not None:
        rows = [r for r in rows if r["guest_id"] == guest_id]
    if review_state is not None:
        rows = [r for r in rows if r["review_state"] == review_state]
    return paginate(rows, views.document_view), 200


@bp.route("/rentals/identity-documents/<did>/review", methods=["POST"])
def review_document(did):
    require_auth(ROLE_COMPLIANCE)
    body = body_json()
    decision = req_enum(body, "decision", ("ACCEPT", "REJECT"))
    reject_reason_code = None
    if decision == "REJECT":
        reject_reason_code = req_enum(body, "reject_reason_code",
                                      DOC_REJECT_REASONS)
    d = db.identity_documents.get(did)
    if d is None:
        fail("ERR_DOCUMENT_NOT_FOUND", "Identity document not found")
    if d["review_state"] in ("REJECTED", "EXPIRED"):
        fail("ERR_ALREADY_TERMINAL",
             "This document has already reached a terminal review state")
    if d["review_state"] != "PENDING":
        fail("ERR_INVALID_STATE", "Only a PENDING document can be reviewed")
    if decision == "ACCEPT" and not (d["expires_on"] > now()):
        fail("ERR_DOCUMENT_EXPIRED",
             "An expired document cannot be accepted")
    d["reviewed_by_user_id"] = g.user_id
    if decision == "ACCEPT":
        d["review_state"] = "ACCEPTED"
    else:
        d["review_state"] = "REJECTED"
        d["reject_reason_code"] = reject_reason_code
    touch(d)
    guest_row = db.guests.get(d["guest_id"])
    if guest_row is not None:
        touch(guest_row)
        calc.apply_risk_cascade(guest_row)
    return object_response(views.document_view(d)), 200


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------

def live_reservations():
    return [r for r in db.reservations.values()
            if r["stay_state"] in LIVE_STAY_STATES]


@bp.route("/rentals/reservations", methods=["POST"])
def create_reservation():
    require_auth(ROLE_GUEST)
    body = body_json()
    guest_id = req_string(body, "guest_id")
    property_id = req_string(body, "property_id")
    check_in = req_date(body, "check_in")
    check_out = req_date(body, "check_out")
    guest_count = req_int(body, "guest_count", minimum=1)
    event_declared = req_bool(body, "event_declared")
    expected_property_version = req_int(body, "expected_property_version")

    guest_row = db.guests.get(guest_id)
    if guest_row is None:
        fail("ERR_GUEST_NOT_FOUND", "Guest not found")
    p = db.properties.get(property_id)
    if p is None:
        fail("ERR_PROPERTY_NOT_FOUND", "Property not found")
    require_owner(guest_id)
    if expected_property_version != p["version"]:
        fail("ERR_PROPERTY_VERSION_STALE",
             "expected_property_version does not match the listing")

    jr = calc.prop_rule(p)

    # 1. Standing bans.
    if calc.is_blocklisted(guest_id, p):
        fail("ERR_GUEST_BLOCKLISTED",
             "A standing ban covers this guest for this listing")
    # 2. Date range.
    if not (check_out > check_in):
        fail("ERR_INVALID_DATE_RANGE",
             "check_out must be strictly later than check_in")
    check_in_at = at_time(check_in, 15)
    check_out_at = at_time(check_out, 11)
    # 3. Not in the past.
    if not (check_in_at > now()):
        fail("ERR_CHECK_IN_IN_PAST",
             "check_in_at must be strictly later than the current instant")
    # 4. Minimum stay.
    nights = (check_out - check_in).days
    if nights < jr["min_stay_nights"]:
        fail("ERR_MIN_STAY_NOT_MET",
             "This jurisdiction requires at least %d nights"
             % jr["min_stay_nights"])
    # 5. Occupancy against the effective ceiling, strictly greater than.
    if guest_count > calc.effective_max_occupancy(p):
        fail("ERR_OCCUPANCY_LIMIT_EXCEEDED",
             "guest_count exceeds the effective occupancy ceiling")
    # 6. Listing calendar -- property scoped, half open.
    buffer_nights = p["turnover_buffer_nights"]
    for other in live_reservations():
        if other["property_id"] != property_id:
            continue
        blocked_start = other["_check_in"]
        blocked_end = other["_check_out"] + timedelta(days=buffer_nights)
        if check_in < blocked_end and check_out > blocked_start:
            fail("ERR_PROPERTY_CALENDAR_CONFLICT",
                 "The requested span overlaps a live booking of this listing")
    # 7. Guest calendar -- platform wide, closed at both ends.
    for other in live_reservations():
        if other["guest_id"] != guest_id:
            continue
        if check_in <= other["_check_out"] and check_out >= other["_check_in"]:
            fail("ERR_GUEST_STAY_OVERLAP",
                 "The requested span overlaps another stay of this guest")

    # Pinned risk snapshot -- frozen, never recomputed, fires no cascade.
    score = calc.risk_score(guest_row)
    tier = calc.risk_tier_of(score)
    charge = calc.compute_charge(p, nights, tier)

    row = new_row()
    row.update({
        "guest_id": guest_id,
        "property_id": property_id,
        "check_in": body["check_in"],
        "check_out": body["check_out"],
        "_check_in": check_in,
        "_check_out": check_out,
        "guest_count": guest_count,
        "event_declared": event_declared,
        "nights": nights,
        "check_in_at": check_in_at,
        "check_out_at": check_out_at,
        "claim_window_ends_at": check_out_at + hours(72),
        "screening_state": "SCREENING",
        "screening_reason_code": None,
        "risk_score_at_booking": score,
        "risk_tier_at_booking": tier,
        "screening_decided_by_user_id": None,
        "stay_state": "REQUESTED",
        "cancel_reason_code": None,
        "deposit_state": "NONE",
        "deposit_applied_cents": 0,
        "deposit_refunded_cents": 0,
        "accommodation_cents": charge["accommodation_cents"],
        "waiver_fee_cents": charge["waiver_fee_cents"],
        "pre_fee_subtotal_cents": charge["pre_fee_subtotal_cents"],
        "trust_fee_pct": charge["trust_fee_pct"],
        "trust_fee_cents": charge["trust_fee_cents"],
        "total_charged_cents": charge["total_charged_cents"],
        "deposit_hold_cents": charge["deposit_hold_cents"],
    })

    verdict, reason = calc.screening_decision(tier, event_declared, jr, p,
                                             guest_count)
    row["screening_state"] = verdict
    row["screening_reason_code"] = reason
    if verdict == "DENIED":
        row["stay_state"] = "CANCELLED"
        row["cancel_reason_code"] = "SCREENING_DENIED"

    db.reservations[row["id"]] = row
    touch(p)
    return object_response(views.reservation_view(row)), 201


@bp.route("/rentals/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    require_auth(*ALL_ROLES)
    row = db.reservations.get(rid)
    if row is None:
        fail("ERR_RESERVATION_NOT_FOUND", "Reservation not found")
    return object_response(views.reservation_view(row)), 200


@bp.route("/rentals/reservations", methods=["GET"])
def list_reservations():
    require_auth(*ALL_ROLES)
    filters = (("guest_id", "guest_id"), ("property_id", "property_id"),
               ("stay_state", "stay_state"),
               ("screening_state", "screening_state"),
               ("deposit_state", "deposit_state"))
    rows = list(db.reservations.values())
    for param, field in filters:
        value = qs(param)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paginate(rows, views.reservation_view), 200


@bp.route("/rentals/reservations/<rid>/charge-breakdown", methods=["GET"])
def reservation_charge_breakdown(rid):
    require_auth(ROLE_GUEST, ROLE_HOST, ROLE_ADJUDICATOR, ROLE_ADMIN)
    row = db.reservations.get(rid)
    if row is None:
        fail("ERR_RESERVATION_NOT_FOUND", "Reservation not found")
    return object_response(views.charge_breakdown_view(row)), 200


TERMINAL_STAY_STATES = ("COMPLETED", "CANCELLED")


def _reservation_or_404(rid):
    row = db.reservations.get(rid)
    if row is None:
        fail("ERR_RESERVATION_NOT_FOUND", "Reservation not found")
    return row


@bp.route("/rentals/reservations/<rid>/screening-decision", methods=["POST"])
def decide_screening(rid):
    require_auth(ROLE_ADJUDICATOR)
    body = body_json()
    decision = req_enum(body, "decision", ("CLEAR", "DENY"))
    opt_string(body, "note")
    r = _reservation_or_404(rid)
    if r["screening_state"] in ("CLEARED", "DENIED"):
        fail("ERR_ALREADY_TERMINAL",
             "The screening dimension has already reached a terminal state")
    if r["screening_state"] != "MANUAL_REVIEW":
        fail("ERR_INVALID_STATE",
             "Only a MANUAL_REVIEW screening can be resolved")
    if r["stay_state"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "The stay must still be REQUESTED")
    r["screening_decided_by_user_id"] = g.user_id
    if decision == "CLEAR":
        r["screening_state"] = "CLEARED"
        r["screening_reason_code"] = "ADJUDICATOR_CLEARED"
    else:
        r["screening_state"] = "DENIED"
        r["screening_reason_code"] = "ADJUDICATOR_DENIED"
        r["stay_state"] = "CANCELLED"
        r["cancel_reason_code"] = "SCREENING_DENIED"
    touch(r)
    return object_response(views.reservation_view(r)), 200


@bp.route("/rentals/reservations/<rid>/confirm", methods=["POST"])
def confirm_reservation(rid):
    require_auth(ROLE_HOST)
    body_json()
    r = _reservation_or_404(rid)
    p = db.properties.get(r["property_id"])
    require_owner(p["host_id"])
    if r["stay_state"] in TERMINAL_STAY_STATES:
        fail("ERR_ALREADY_TERMINAL", "This stay has already ended")
    if r["stay_state"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "Only a REQUESTED stay can be confirmed")
    if r["screening_state"] != "CLEARED":
        fail("ERR_INVALID_STATE", "screening_state must read CLEARED")
    if calc.is_blocklisted(r["guest_id"], p):
        fail("ERR_GUEST_BLOCKLISTED",
             "A standing ban covers this guest for this listing")
    if calc.sensor_compliance_state(p) != "COMPLIANT":
        fail("ERR_SENSOR_COMPLIANCE_BLOCKED",
             "sensor_compliance_state must read COMPLIANT")
    if p["listing_state"] != "ACTIVE":
        fail("ERR_PROPERTY_NOT_LISTED", "The listing is not ACTIVE")
    r["stay_state"] = "CONFIRMED"
    if p["protection_product"] == "DEPOSIT" and r["deposit_state"] == "NONE" \
            and r["deposit_hold_cents"] > 0:
        r["deposit_state"] = "HELD"
        guest_row = db.guests.get(r["guest_id"])
        if guest_row is not None:
            touch(guest_row)
    touch(r)
    return object_response(views.reservation_view(r)), 200


@bp.route("/rentals/reservations/<rid>/check-in", methods=["POST"])
def check_in_reservation(rid):
    require_auth(ROLE_HOST)
    body_json()
    r = _reservation_or_404(rid)
    p = db.properties.get(r["property_id"])
    require_owner(p["host_id"])
    if r["stay_state"] in TERMINAL_STAY_STATES:
        fail("ERR_ALREADY_TERMINAL", "This stay has already ended")
    if r["stay_state"] != "CONFIRMED":
        fail("ERR_INVALID_STATE", "Only a CONFIRMED stay can be checked in")
    if now() < r["check_in_at"]:
        fail("ERR_INVALID_STATE", "check_in_at has not been reached yet")
    if p["listing_state"] != "ACTIVE":
        fail("ERR_PROPERTY_NOT_LISTED", "The listing is not ACTIVE")
    r["stay_state"] = "IN_STAY"
    touch(r)
    return object_response(views.reservation_view(r)), 200


@bp.route("/rentals/reservations/<rid>/complete", methods=["POST"])
def complete_reservation(rid):
    require_auth(ROLE_HOST)
    body_json()
    r = _reservation_or_404(rid)
    p = db.properties.get(r["property_id"])
    require_owner(p["host_id"])
    if r["stay_state"] in TERMINAL_STAY_STATES:
        fail("ERR_ALREADY_TERMINAL", "This stay has already ended")
    if r["stay_state"] != "IN_STAY":
        fail("ERR_INVALID_STATE", "Only an IN_STAY booking can be completed")
    if now() < r["check_out_at"]:
        fail("ERR_INVALID_STATE", "check_out_at has not been reached yet")
    r["stay_state"] = "COMPLETED"
    touch(r)
    guest_row = db.guests.get(r["guest_id"])
    if guest_row is not None:
        touch(guest_row)
        calc.apply_risk_cascade(guest_row)
    return object_response(views.reservation_view(r)), 200


@bp.route("/rentals/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    user_id, role = require_auth(ROLE_GUEST, ROLE_HOST)
    body_json()
    r = _reservation_or_404(rid)
    p = db.properties.get(r["property_id"])
    if role == ROLE_GUEST:
        require_owner(r["guest_id"])
    else:
        require_owner(p["host_id"])
    if r["stay_state"] in TERMINAL_STAY_STATES:
        fail("ERR_ALREADY_TERMINAL", "This stay has already ended")
    if r["stay_state"] == "IN_STAY":
        fail("ERR_INVALID_STATE", "A stay already IN_STAY cannot be cancelled")
    was_confirmed = r["stay_state"] == "CONFIRMED"
    r["stay_state"] = "CANCELLED"
    r["cancel_reason_code"] = "GUEST_WITHDREW" if role == ROLE_GUEST \
        else "HOST_WITHDREW"
    if was_confirmed and r["deposit_state"] == "HELD":
        r["deposit_state"] = "RELEASED"
        r["deposit_refunded_cents"] = r["deposit_hold_cents"]
        guest_row = db.guests.get(r["guest_id"])
        if guest_row is not None:
            touch(guest_row)
    touch(r)
    touch(p)
    return object_response(views.reservation_view(r)), 200
