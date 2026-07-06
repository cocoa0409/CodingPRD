from flask import Blueprint, request
from db import db
from middleware import require_user_context, require_role
from response import object_response, array_response
from services.common import (stamp_new, bump, public, get_json_body, require_str,
                             require_int, require_enum, paginate, sorted_by_creation)
from services.lookup import get_or_404
from services.calc import (MODALITY_PRICE_CENTS, provisional_responsibility,
                           referral_priority_and_due, recompute_grant,
                           NO_SHOW_STRIKE_LIMIT)
from errors import err
from clock import clock

bp = Blueprint("appointments", __name__)

BOOKED_STATES = {"SCHEDULED", "CHECKED_IN", "SCREENED", "RESULT_READY", "CLOSED"}
NON_CANCELLED_FOR_OVERLAP = {"SCHEDULED", "CHECKED_IN", "SCREENED", "RESULT_READY", "CLOSED", "NO_SHOW"}
ALL_READ = {"ProgramManager", "ClinicalStaff", "BillingClerk", "PatientNavigator"}


def _booked_count(event_id):
    return sum(1 for a in db.appointments.values()
               if a["event_id"] == event_id and a["status"] in BOOKED_STATES)


@bp.route("/appointments", methods=["POST"])
def book():
    _, role = require_user_context()
    require_role(role, {"ProgramManager", "ClinicalStaff"})
    body = get_json_body()
    # priority 5: well-formedness
    event_id = require_str(body, "event_id")
    participant_id = require_str(body, "participant_id")
    slot_start = require_int(body, "slot_start_min", minimum=0)
    slot_duration = require_int(body, "slot_duration_min", minimum=1)
    # priority 4: FK existence
    event = get_or_404("events", event_id)
    participant = get_or_404("participants", participant_id)
    # priority 9: blocked participant
    if participant["status"] == "BLOCKED":
        raise err("ERR_PARTICIPANT_BLOCKED", "Participant is BLOCKED")
    slot_end = slot_start + slot_duration
    # priority 10: slot within window (half-open)
    if slot_start < event["window_start_min"] or slot_end > event["window_end_min"]:
        raise err("ERR_SLOT_OUTSIDE_WINDOW", "Slot not fully within event window")
    # priority 11: slot overlap
    for a in db.appointments.values():
        if a["event_id"] != event_id:
            continue
        if a["status"] not in NON_CANCELLED_FOR_OVERLAP:
            continue
        a_start = a["slot_start_min"]
        a_end = a["slot_start_min"] + a["slot_duration_min"]
        if slot_start < a_end and a_start < slot_end:
            raise err("ERR_SLOT_OVERLAP", "Slot overlaps an existing appointment")
    # priority 12: capacity
    unit = db.mobile_units.get(event["mobile_unit_id"])
    capacity = unit["daily_capacity"] if unit else 0
    if _booked_count(event_id) >= capacity:
        raise err("ERR_EVENT_FULL", "Event at capacity")
    # priority 13: grant depletion
    if participant["pay_type"] == "GRANT":
        grant = db.grants.get(participant.get("grant_id"))
        if grant:
            recompute_grant(grant)
            if grant["is_depleted"]:
                raise err("ERR_GRANT_DEPLETED", "Grant is depleted")
    appt = stamp_new({
        "event_id": event_id, "participant_id": participant_id,
        "slot_start_min": slot_start, "slot_duration_min": slot_duration,
        "consent_signed": False, "consent_signed_at": None,
        "result": None, "result_delivered_at": None, "status": "SCHEDULED",
    })
    db.appointments[appt["id"]] = appt
    return object_response(public(appt), 201)


@bp.route("/appointments", methods=["GET"])
def list_appts():
    _, role = require_user_context()
    require_role(role, ALL_READ)
    items = list(db.appointments.values())
    for f in ("event_id", "participant_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [a for a in items if a[f] == val]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return array_response([public(a) for a in page], limit, offset, total)


@bp.route("/appointments/<rid>", methods=["GET"])
def get_appt(rid):
    _, role = require_user_context()
    require_role(role, ALL_READ)
    return object_response(public(get_or_404("appointments", rid)), 200)


@bp.route("/appointments/<rid>/consent", methods=["POST"])
def consent(rid):
    _, role = require_user_context()
    require_role(role, {"ProgramManager", "ClinicalStaff"})
    appt = get_or_404("appointments", rid)
    appt["consent_signed"] = True
    appt["consent_signed_at"] = clock.now_iso()
    bump(appt)
    return object_response(public(appt), 200)


@bp.route("/appointments/<rid>/check-in", methods=["POST"])
def check_in(rid):
    _, role = require_user_context()
    require_role(role, {"ClinicalStaff"})
    appt = get_or_404("appointments", rid)
    if appt["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Appointment not SCHEDULED")
    event = db.events.get(appt["event_id"])
    if not event or event["status"] != "PUBLISHED":
        raise err("ERR_EVENT_NOT_PUBLISHED", "Parent event not PUBLISHED")
    if not appt.get("consent_signed"):
        raise err("ERR_CONSENT_REQUIRED", "Consent required before check-in")
    appt["status"] = "CHECKED_IN"
    bump(appt)
    return object_response(public(appt), 200)


@bp.route("/appointments/<rid>/screen", methods=["POST"])
def screen(rid):
    _, role = require_user_context()
    require_role(role, {"ClinicalStaff"})
    appt = get_or_404("appointments", rid)
    if appt["status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "Appointment not CHECKED_IN")
    event = db.events.get(appt["event_id"])
    modality = event["modality"]
    if not _has_active_staff(modality, {"TECHNOLOGIST", "PHLEBOTOMIST"}):
        raise err("ERR_NO_CREDENTIALED_STAFF", "No credentialed active staff")
    appt["status"] = "SCREENED"
    bump(appt)
    _create_charge(appt, event)
    return object_response(public(appt), 200)


def _has_active_staff(modality, role_types):
    for s in db.staff.values():
        if s["status"] == "ACTIVE" and s["modality"] == modality and s["role_type"] in role_types:
            return True
    return False


def _create_charge(appt, event):
    participant = db.participants.get(appt["participant_id"])
    pay_type = participant["pay_type"]
    list_price = MODALITY_PRICE_CENTS[event["modality"]]
    grant_id = None
    grant_remaining = 0
    if pay_type == "GRANT":
        grant_id = participant.get("grant_id")
        grant = db.grants.get(grant_id)
        if grant:
            recompute_grant(grant)
            grant_remaining = grant["remaining_cents"]
    grant_covered, provisional = provisional_responsibility(pay_type, list_price, grant_remaining)
    charge = stamp_new({
        "appointment_id": appt["id"], "participant_id": appt["participant_id"],
        "grant_id": grant_id if pay_type == "GRANT" else None,
        "list_price_cents": list_price, "pay_type": pay_type,
        "insurance_allowed_cents": None,
        "grant_covered_cents": grant_covered if pay_type == "GRANT" else 0,
        "provisional_patient_responsibility_cents": provisional,
        "final_patient_responsibility_cents": None,
        "status": "DRAFT",
    })
    db.charges[charge["id"]] = charge
    if pay_type == "GRANT" and grant_id:
        grant = db.grants.get(grant_id)
        if grant:
            recompute_grant(grant)
            bump(grant)
    return charge


@bp.route("/appointments/<rid>/deliver-result", methods=["POST"])
def deliver_result(rid):
    _, role = require_user_context()
    require_role(role, {"ClinicalStaff"})
    appt = get_or_404("appointments", rid)
    body = get_json_body()
    result = require_enum(body, "result", {"NORMAL", "ABNORMAL"})
    flagged_urgent = body.get("flagged_urgent", False)
    if flagged_urgent is not None and not isinstance(flagged_urgent, bool):
        raise err("ERR_INVALID_REQUEST", "flagged_urgent must be boolean")
    if appt["status"] != "SCREENED":
        raise err("ERR_INVALID_STATE", "Appointment not SCREENED")
    event = db.events.get(appt["event_id"])
    if event["modality"] == "MAMMOGRAPHY":
        if not _has_active_staff("MAMMOGRAPHY", {"RADIOLOGIST"}):
            raise err("ERR_NO_CREDENTIALED_STAFF", "No credentialed radiologist")
    appt["status"] = "RESULT_READY"
    appt["result"] = result
    appt["result_delivered_at"] = clock.now_iso()
    bump(appt)
    if result == "ABNORMAL":
        _create_referral(appt, event, bool(flagged_urgent))
    return object_response(public(appt), 200)


def _create_referral(appt, event, flagged_urgent):
    priority, due_by = referral_priority_and_due(flagged_urgent, event["event_date"])
    referral = stamp_new({
        "appointment_id": appt["id"], "participant_id": appt["participant_id"],
        "priority": priority, "due_by_date": due_by, "status": "OPEN",
    })
    db.referrals[referral["id"]] = referral
    return referral


@bp.route("/appointments/<rid>/close", methods=["POST"])
def close_appt(rid):
    _, role = require_user_context()
    require_role(role, {"ClinicalStaff"})
    appt = get_or_404("appointments", rid)
    if appt["status"] != "RESULT_READY":
        raise err("ERR_INVALID_STATE", "Appointment not RESULT_READY")
    if appt.get("result") == "ABNORMAL":
        ref = _linked_referral(appt["id"])
        if not ref or ref["status"] not in ("RESOLVED", "LOST_TO_FOLLOWUP"):
            raise err("ERR_REFERRAL_UNRESOLVED", "Linked referral not terminal")
    appt["status"] = "CLOSED"
    bump(appt)
    return object_response(public(appt), 200)


def _linked_referral(appt_id):
    refs = [r for r in db.referrals.values() if r["appointment_id"] == appt_id]
    if not refs:
        return None
    return sorted(refs, key=lambda r: r["_seq"])[-1]


@bp.route("/appointments/<rid>/cancel", methods=["POST"])
def cancel_appt(rid):
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    appt = get_or_404("appointments", rid)
    if appt["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Appointment not SCHEDULED")
    appt["status"] = "CANCELLED"
    bump(appt)
    _cancel_pending_reminders(rid)
    return object_response(public(appt), 200)


@bp.route("/appointments/<rid>/mark-no-show", methods=["POST"])
def mark_no_show(rid):
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    appt = get_or_404("appointments", rid)
    if appt["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Appointment not SCHEDULED")
    event = db.events.get(appt["event_id"])
    if not event or event["status"] != "CLOSED":
        raise err("ERR_EVENT_NOT_CLOSED", "Parent event not CLOSED")
    appt["status"] = "NO_SHOW"
    bump(appt)
    # hop 1: strike++
    participant = db.participants.get(appt["participant_id"])
    if participant:
        participant["no_show_strikes"] = participant.get("no_show_strikes", 0) + 1
        # hop 2: threshold flip
        if participant["no_show_strikes"] >= NO_SHOW_STRIKE_LIMIT and participant["status"] == "ACTIVE":
            participant["status"] = "BLOCKED"
        bump(participant)
    # hop 2 (comms): cancel pending reminders
    _cancel_pending_reminders(rid)
    return object_response(public(appt), 200)


def _cancel_pending_reminders(appt_id):
    for r in db.reminders.values():
        if r["appointment_id"] == appt_id and r["status"] == "PENDING":
            r["status"] = "CANCELLED"
            bump(r)
