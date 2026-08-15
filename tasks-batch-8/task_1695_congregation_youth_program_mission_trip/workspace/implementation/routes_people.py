"""Participants, registrations, and consent forms."""
from datetime import timedelta

from flask import request

from store import DB
from util import (
    ApiError, success_object, get_body, req_str, opt_str, req_int, req_enum,
    req_datetime, req_date, fmt_clock, round_half_up_cents,
)
import domain as D
from web import (
    app, PREFIX, caller, require_role, paginate,
    get_program, get_trip, get_participant, get_registration, get_consent_form,
    guardian_owns_or_403,
)

PARTICIPANT_LIST_ROLES = ["ProgramDirector", "TripLeader", "Treasurer"]


def _arg(name):
    return request.args.get(name)


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------

@app.post(f"{PREFIX}/participants")
def create_participant():
    uid, role = caller()
    body = get_body()
    program_id = req_str(body, "program_id")
    family_key = req_str(body, "family_key")
    first_name = req_str(body, "first_name")
    last_name = req_str(body, "last_name")
    birth_raw, birth_d = req_date(body, "birth_date")
    grade = req_int(body, "grade", min_value=6, max_value=12)
    bracket = req_enum(body, "annual_income_bracket", D.INCOME_BRACKETS)
    household = req_int(body, "household_size", min_value=1)
    if role == "ProgramDirector":
        guardian_id = req_str(body, "guardian_user_id")
    require_role(role, ["ProgramDirector", "Guardian"])
    if role == "Guardian":
        guardian_id = uid

    program = get_program(program_id)
    if program["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_NOT_OPEN", "Program is not OPEN", 409)

    participant = {
        "program_id": program_id,
        "family_key": family_key,
        "guardian_user_id": guardian_id,
        "first_name": first_name,
        "last_name": last_name,
        "birth_date": birth_raw,
        "grade": grade,
        "annual_income_bracket": bracket,
        "household_size": household,
        "barred_until": "",
        "_barred_until_dt": None,
    }
    DB.stamp_created(participant)
    DB.participants[participant["id"]] = participant
    return success_object(D.ser_participant(participant), 201)


@app.get(f"{PREFIX}/participants")
def list_participants():
    uid, role = caller()
    require_role(role, PARTICIPANT_LIST_ROLES)
    items = list(DB.participants.values())
    program_id = _arg("program_id")
    family_key = _arg("family_key")
    if program_id is not None:
        items = [p for p in items if p["program_id"] == program_id]
    if family_key is not None:
        items = [p for p in items if p["family_key"] == family_key]
    return paginate(items, D.ser_participant)


@app.get(f"{PREFIX}/participants/<pid>")
def read_participant(pid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "TripLeader", "Treasurer", "Guardian"])
    participant = get_participant(pid)
    guardian_owns_or_403(uid, role, participant["guardian_user_id"])
    return success_object(D.ser_participant(participant))


# ---------------------------------------------------------------------------
# Registrations
# ---------------------------------------------------------------------------

def _check_participant_not_barred(participant):
    barred_dt = participant.get("_barred_until_dt")
    if barred_dt is not None and barred_dt >= DB.clock_dt:
        raise ApiError("ERR_PARTICIPANT_BARRED", "Participant is barred from future trips", 409)


@app.post(f"{PREFIX}/registrations")
def create_registration():
    uid, role = caller()
    body = get_body()
    trip_id = req_str(body, "trip_id")
    participant_id = req_str(body, "participant_id")
    insurance_tier = req_enum(body, "insurance_tier", D.INSURANCE_TIERS)
    goal = req_int(body, "fundraising_goal_cents", min_value=0)
    require_role(role, ["ProgramDirector", "Guardian"])
    trip = get_trip(trip_id)
    participant = get_participant(participant_id)
    guardian_owns_or_403(uid, role, participant["guardian_user_id"])
    if trip["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION", "Trip is not REGISTRATION_OPEN", 409)
    _check_participant_not_barred(participant)
    if DB.clock_dt > trip["_registration_close_dt"]:
        raise ApiError("ERR_REGISTRATION_WINDOW_CLOSED",
                       "Clock is strictly past registration_close_at", 422)
    for other in D.regs_of_trip(trip_id):
        if other["participant_id"] == participant_id \
                and other["registration_status"] in D.REG_NON_TERMINAL:
            raise ApiError("ERR_DUPLICATE_REGISTRATION",
                           "A non-terminal registration already exists for this trip and participant", 409)

    provisional = trip["base_cost_cents"] + round_half_up_cents(
        trip["lodging_cost_total_cents"], trip["capacity_youth"]
    )
    reg = {
        "trip_id": trip_id,
        "participant_id": participant_id,
        "guardian_user_id": participant["guardian_user_id"],
        "registration_status": "DRAFT",
        "payment_status": "PENDING_DEPOSIT",
        "insurance_tier": insurance_tier,
        "provisional_cost_share_cents": provisional,
        "final_cost_share_cents": 0,
        "late_fees_total_cents": 0,
        "covered_cents": 0,
        "amount_due_cents": provisional,
        "fundraising_credit_applied_cents": 0,
        "scholarship_awarded_cents": 0,
        "conduct_acknowledged": False,
        "deposit_late_fee_assessed": False,
        "final_late_fee_assessed": False,
        "dismiss_sanction": "",
        "dismiss_reason": "",
    }
    DB.stamp_created(reg)
    DB.registrations[reg["id"]] = reg

    account = {
        "registration_id": reg["id"],
        "status": "OPEN",
        "goal_cents": goal,
        "raised_gross_cents": 0,
        "fee_total_cents": 0,
        "raised_net_cents": 0,
        "credit_applied_cents": 0,
        "available_credit_cents": 0,
        "goal_met": False,
    }
    DB.stamp_created(account)
    DB.fundraising_accounts[account["id"]] = account
    D.recompute_trip(trip)
    return success_object(D.ser_registration(reg), 201)


@app.get(f"{PREFIX}/registrations")
def list_registrations():
    uid, role = caller()
    require_role(role, ["ProgramDirector", "TripLeader", "Treasurer"])
    items = list(DB.registrations.values())
    trip_id = _arg("trip_id")
    participant_id = _arg("participant_id")
    reg_status = _arg("registration_status")
    pay_status = _arg("payment_status")
    if trip_id is not None:
        items = [r for r in items if r["trip_id"] == trip_id]
    if participant_id is not None:
        items = [r for r in items if r["participant_id"] == participant_id]
    if reg_status is not None:
        items = [r for r in items if r["registration_status"] == reg_status]
    if pay_status is not None:
        items = [r for r in items if r["payment_status"] == pay_status]
    return paginate(items, D.ser_registration)


@app.get(f"{PREFIX}/registrations/<rid>")
def read_registration(rid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "TripLeader", "Treasurer", "ScholarshipReviewer", "Guardian"])
    reg = get_registration(rid)
    guardian_owns_or_403(uid, role, reg["guardian_user_id"])
    return success_object(D.ser_registration(reg))


def _required_forms(reg, statuses):
    """True when every required form type has a form in one of the given statuses."""
    forms = D.forms_of_registration(reg["id"])
    for ftype in D.REQUIRED_FORM_TYPES:
        if not any(f["form_type"] == ftype and f["status"] in statuses for f in forms):
            return False
    return True


@app.post(f"{PREFIX}/registrations/<rid>/submit")
def submit_registration(rid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "Guardian"])
    reg = get_registration(rid)
    guardian_owns_or_403(uid, role, reg["guardian_user_id"])
    if reg["registration_status"] != "DRAFT":
        raise ApiError("ERR_REGISTRATION_STATE_FORBIDS_ACTION", "Registration is not DRAFT", 409)
    trip = get_trip(reg["trip_id"])
    if trip["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION", "Trip is not REGISTRATION_OPEN", 409)
    if not _required_forms(reg, ("SUBMITTED", "VERIFIED")):
        raise ApiError("ERR_REQUIRED_FORMS_INCOMPLETE",
                       "All three required consent forms must be SUBMITTED or VERIFIED", 422)
    reg["registration_status"] = "SUBMITTED"
    DB.touch("registrations", reg["id"])
    return success_object(D.ser_registration(reg))


@app.post(f"{PREFIX}/registrations/<rid>/review")
def review_registration(rid):
    uid, role = caller()
    body = get_body()
    decision = req_enum(body, "decision", ["APPROVE", "REJECT"])
    reason = opt_str(body, "reason", "")
    require_role(role, ["ProgramDirector", "TripLeader"])
    reg = get_registration(rid)
    if uid == reg["guardian_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", "Reviewer must not be the registration's guardian", 403)
    if reg["registration_status"] != "SUBMITTED":
        raise ApiError("ERR_REGISTRATION_STATE_FORBIDS_ACTION", "Registration is not SUBMITTED", 409)
    trip = get_trip(reg["trip_id"])

    if decision == "REJECT":
        reg["registration_status"] = "REJECTED"
        DB.touch("registrations", reg["id"])
        account = D.account_of_registration(reg["id"])
        if account is not None and account["status"] == "OPEN":
            account["status"] = "CLOSED"
            DB.touch("fundraising_accounts", account["id"])
        for form in D.forms_of_registration(reg["id"]):
            if form["status"] in ("SUBMITTED", "VERIFIED", "REJECTED"):
                form["status"] = "VOIDED"
                DB.touch("consent_forms", form["id"])
        return success_object(D.ser_registration(reg))

    # APPROVE
    if trip["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION", "Trip is not REGISTRATION_OPEN", 409)
    participant = get_participant(reg["participant_id"])
    _check_participant_not_barred(participant)
    if not _required_forms(reg, ("VERIFIED",)):
        raise ApiError("ERR_REQUIRED_FORMS_INCOMPLETE",
                       "All three required consent forms must be VERIFIED", 422)
    D.recompute_trip(trip)
    if trip["seats_taken"] < trip["capacity_youth"]:
        reg["registration_status"] = "APPROVED"
    else:
        reg["registration_status"] = "WAITLISTED"
    DB.touch("registrations", reg["id"])
    D.recompute_trip(trip)
    return success_object(D.ser_registration(reg))


@app.post(f"{PREFIX}/registrations/<rid>/promote")
def promote_registration(rid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "TripLeader"])
    reg = get_registration(rid)
    if reg["registration_status"] != "WAITLISTED":
        raise ApiError("ERR_REGISTRATION_STATE_FORBIDS_ACTION", "Registration is not WAITLISTED", 409)
    trip = get_trip(reg["trip_id"])
    if trip["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION", "Trip is not REGISTRATION_OPEN", 409)
    D.recompute_trip(trip)
    if trip["seats_taken"] >= trip["capacity_youth"]:
        raise ApiError("ERR_NO_WAITLIST_CAPACITY", "No seats available for promotion", 409)
    waitlisted = [r for r in D.regs_of_trip(trip["id"]) if r["registration_status"] == "WAITLISTED"]
    head = min(waitlisted, key=lambda r: (r["created_at"], _participant_created(r), r["_seq"]))
    if head["id"] != reg["id"]:
        raise ApiError("ERR_WAITLIST_NOT_HEAD", "Registration is not the waitlist head", 409)
    reg["registration_status"] = "APPROVED"
    DB.touch("registrations", reg["id"])
    D.recompute_trip(trip)
    return success_object(D.ser_registration(reg))


def _participant_created(reg):
    p = DB.participants.get(reg["participant_id"])
    return p["created_at"] if p is not None else ""


@app.post(f"{PREFIX}/registrations/<rid>/confirm")
def confirm_registration(rid):
    uid, role = caller()
    require_role(role, ["ProgramDirector"])
    reg = get_registration(rid)
    if reg["registration_status"] != "APPROVED":
        raise ApiError("ERR_REGISTRATION_STATE_FORBIDS_ACTION", "Registration is not APPROVED", 409)
    trip = get_trip(reg["trip_id"])
    if trip["status"] not in ("REGISTRATION_OPEN", "REGISTRATION_CLOSED"):
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION",
                       "Trip is not REGISTRATION_OPEN or REGISTRATION_CLOSED", 409)
    D.registration_money(reg, trip, update_status=False)
    if reg["covered_cents"] < trip["deposit_cents"]:
        raise ApiError("ERR_DEPOSIT_NOT_COVERED", "covered_cents is below the deposit", 402)
    reg["registration_status"] = "CONFIRMED"
    DB.touch("registrations", reg["id"])
    D.recompute_trip(trip)
    return success_object(D.ser_registration(reg))


@app.post(f"{PREFIX}/registrations/<rid>/withdraw")
def withdraw_registration(rid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "Guardian"])
    reg = get_registration(rid)
    guardian_owns_or_403(uid, role, reg["guardian_user_id"])
    if reg["registration_status"] not in D.REG_NON_TERMINAL:
        raise ApiError("ERR_REGISTRATION_STATE_FORBIDS_ACTION",
                       "Registration is already terminal", 409)
    trip = get_trip(reg["trip_id"])
    if reg["registration_status"] == "CONFIRMED" and trip["status"] == "IN_PROGRESS":
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION",
                       "A CONFIRMED registration on an in-progress trip can only leave via dismiss", 409)
    mature = reg["registration_status"] in ("APPROVED", "CONFIRMED")
    reg["registration_status"] = "WITHDRAWN"
    DB.touch("registrations", reg["id"])
    D.cascade_registration_terminal(reg, trip, refund_payments=mature, scholarship_mode="withdraw")
    D.recompute_trip(trip)
    return success_object(D.ser_registration(reg))


@app.post(f"{PREFIX}/registrations/<rid>/dismiss")
def dismiss_registration(rid):
    uid, role = caller()
    body = get_body()
    sanction = req_enum(body, "sanction", D.SANCTIONS)
    reason = req_str(body, "reason")
    require_role(role, ["ProgramDirector"])
    reg = get_registration(rid)
    if reg["registration_status"] != "CONFIRMED":
        raise ApiError("ERR_REGISTRATION_STATE_FORBIDS_ACTION", "Registration is not CONFIRMED", 409)
    trip = get_trip(reg["trip_id"])
    if trip["status"] != "IN_PROGRESS":
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION", "Trip is not IN_PROGRESS", 409)
    reg["dismiss_sanction"] = sanction
    reg["dismiss_reason"] = reason
    reg["registration_status"] = "DISMISSED"
    DB.touch("registrations", reg["id"])
    if sanction == "BARRED_FROM_FUTURE":
        participant = get_participant(reg["participant_id"])
        barred_dt = DB.clock_dt + timedelta(days=730)
        participant["barred_until"] = fmt_clock(barred_dt)
        participant["_barred_until_dt"] = barred_dt
        DB.touch("participants", participant["id"])
    D.cascade_registration_terminal(reg, trip, refund_payments=False, scholarship_mode="dismiss")
    D.recompute_trip(trip)
    return success_object(D.ser_registration(reg))


# ---------------------------------------------------------------------------
# Consent forms
# ---------------------------------------------------------------------------

@app.post(f"{PREFIX}/registrations/<rid>/consent-forms")
def create_consent_form(rid):
    uid, role = caller()
    body = get_body()
    form_type = req_enum(body, "form_type", D.FORM_TYPES)
    signed_by = req_str(body, "signed_by_name")
    signed_raw, signed_dt = req_datetime(body, "signed_at")
    medical_notes = opt_str(body, "medical_notes", "")
    require_role(role, ["ProgramDirector", "Guardian"])
    reg = get_registration(rid)
    guardian_owns_or_403(uid, role, reg["guardian_user_id"])
    if reg["registration_status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_REGISTRATION_STATE_FORBIDS_ACTION",
                       "Registration must be DRAFT or SUBMITTED", 409)
    if form_type == "MEDICAL_RELEASE" and not medical_notes:
        raise ApiError("ERR_REQUIRED_FORMS_INCOMPLETE",
                       "MEDICAL_RELEASE requires non-empty medical_notes", 422)
    for form in D.forms_of_registration(rid):
        if form["form_type"] == form_type and form["status"] in ("SUBMITTED", "VERIFIED"):
            raise ApiError("ERR_DUPLICATE_CONSENT_FORM_TYPE",
                           "A form of this type already exists in SUBMITTED or VERIFIED", 409)
    form = {
        "registration_id": rid,
        "form_type": form_type,
        "status": "SUBMITTED",
        "signed_by_name": signed_by,
        "signed_at": fmt_clock(signed_dt),
        "medical_notes": medical_notes,
        "reviewed_by_user_id": "",
        "rejection_reason": "",
    }
    DB.stamp_created(form)
    DB.consent_forms[form["id"]] = form
    return success_object(D.ser_consent_form(form), 201)


@app.get(f"{PREFIX}/registrations/<rid>/consent-forms")
def list_consent_forms(rid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "TripLeader", "Guardian"])
    reg = get_registration(rid)
    guardian_owns_or_403(uid, role, reg["guardian_user_id"])
    return paginate(D.forms_of_registration(rid), D.ser_consent_form)


@app.post(f"{PREFIX}/consent-forms/<fid>/review")
def review_consent_form(fid):
    uid, role = caller()
    body = get_body()
    decision = req_enum(body, "decision", ["VERIFY", "REJECT"])
    reason = opt_str(body, "reason", "")
    require_role(role, ["ProgramDirector", "TripLeader"])
    form = get_consent_form(fid)
    reg = get_registration(form["registration_id"])
    if uid == reg["guardian_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", "Reviewer must not be the registration's guardian", 403)
    if form["status"] != "SUBMITTED":
        raise ApiError("ERR_CONSENT_FORM_STATE_FORBIDS_ACTION", "Consent form is not SUBMITTED", 409)
    if reg["registration_status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_REGISTRATION_STATE_FORBIDS_ACTION",
                       "Registration must be DRAFT or SUBMITTED", 409)
    form["reviewed_by_user_id"] = uid
    if decision == "VERIFY":
        form["status"] = "VERIFIED"
        if form["form_type"] == "CONDUCT_AGREEMENT" and not reg["conduct_acknowledged"]:
            reg["conduct_acknowledged"] = True
            DB.touch("registrations", reg["id"])
    else:
        form["status"] = "REJECTED"
        form["rejection_reason"] = reason
    DB.touch("consent_forms", form["id"])
    return success_object(D.ser_consent_form(form))


@app.post(f"{PREFIX}/consent-forms/<fid>/resubmit")
def resubmit_consent_form(fid):
    uid, role = caller()
    body = get_body()
    signed_by = req_str(body, "signed_by_name")
    signed_raw, signed_dt = req_datetime(body, "signed_at")
    medical_notes = opt_str(body, "medical_notes", "")
    require_role(role, ["ProgramDirector", "Guardian"])
    form = get_consent_form(fid)
    reg = get_registration(form["registration_id"])
    guardian_owns_or_403(uid, role, reg["guardian_user_id"])
    if form["status"] != "REJECTED":
        raise ApiError("ERR_CONSENT_FORM_STATE_FORBIDS_ACTION", "Consent form is not REJECTED", 409)
    if reg["registration_status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_REGISTRATION_STATE_FORBIDS_ACTION",
                       "Registration must be DRAFT or SUBMITTED", 409)
    if form["form_type"] == "MEDICAL_RELEASE" and not medical_notes:
        raise ApiError("ERR_REQUIRED_FORMS_INCOMPLETE",
                       "MEDICAL_RELEASE requires non-empty medical_notes", 422)
    form["signed_by_name"] = signed_by
    form["signed_at"] = fmt_clock(signed_dt)
    form["medical_notes"] = medical_notes
    form["rejection_reason"] = ""
    form["status"] = "SUBMITTED"
    DB.touch("consent_forms", form["id"])
    return success_object(D.ser_consent_form(form))
