"""Registration endpoints (PRD 3.6 / 3.7 / 3.8)."""
from flask import Blueprint, request

import clock
import services
import store
from auth import authenticate, authorize
from errors import raise_err
from routes.payments import payment_out
from util import (
    body_json,
    check_int_range,
    get_or_404,
    list_response,
    req_enum,
    req_int,
    req_str,
    serialize,
    success_object,
)

bp = Blueprint("registrations", __name__)

FIELDS = [
    "id",
    "session_id",
    "participant_id",
    "household_id",
    "residency_at_registration",
    "scholarship_pct_applied",
    "family_discount_applied",
    "fee_charged_cents",
    "net_paid_cents",
    "refund_total_cents",
    "enrollment_status",
    "payment_status",
    "drop_reason",
    "waitlisted_at",
    "promoted_at",
    "payment_due_at",
    "consecutive_absences",
    "created_at",
    "updated_at",
    "version",
]

ROLES = ["HouseholdManager", "FrontDeskStaff"]
READ_ROLES = ["HouseholdManager", "FrontDeskStaff", "ProgramCoordinator", "FinanceOfficer"]
PAYMENT_METHODS = ["EXTERNAL", "ACCOUNT_CREDIT"]


def registration_out(rec):
    return serialize(rec, FIELDS)


@bp.route("/registrations", methods=["POST"])
def create_registration():
    uid, role = authenticate()
    authorize(role, ROLES)
    body = body_json()
    session_id = req_str(body, "session_id")
    participant_id = req_str(body, "participant_id")
    expected = req_int(body, "expected_class_session_version")
    session = get_or_404(store.sessions, session_id, "ClassSession")
    participant = get_or_404(store.participants, participant_id, "Participant")
    # OCC (PRD 2.7): evaluated after well-formedness and existence, before the
    # domain gates of section 3.
    if session["version"] != expected:
        raise_err("ERR_STALE_VERSION", "expected_class_session_version does not match the current version")
    season = services.season_of_session(session)
    # Season gates first.
    if season is None or season["status"] == "DRAFT":
        raise_err("ERR_SEASON_NOT_PUBLISHED", "The season is not PUBLISHED")
    if season["status"] == "CLOSED":
        raise_err("ERR_SEASON_CLOSED", "The season is CLOSED")
    if session["status"] not in ("PUBLISHED", "ACTIVE"):
        raise_err("ERR_SESSION_NOT_OPEN", "The session is not open for registration")
    # Temporal windows in chronological logic.
    now = clock.now()
    if now < season["resident_opens_at"]:
        raise_err("ERR_REGISTRATION_WINDOW_NOT_OPEN", "Registration has not opened yet")
    household = store.households.get(participant["household_id"])
    if now < season["general_opens_at"]:
        if household is None or household["residency_status"] != "RESIDENT":
            raise_err("ERR_RESIDENT_PRIORITY_WINDOW", "Only RESIDENT households may register during the priority window")
    if now >= season["registration_closes_at"]:
        raise_err("ERR_REGISTRATION_WINDOW_CLOSED", "Registration is closed")
    # Duplicate guard.
    for r in store.registrations.values():
        if (
            r["participant_id"] == participant_id
            and r["session_id"] == session_id
            and r["enrollment_status"] in ("ENROLLED", "WAITLISTED")
        ):
            raise_err("ERR_DUPLICATE_REGISTRATION", "A live registration already exists for this participant and session")
    # Age eligibility, both bounds inclusive, measured at the season start.
    program = store.programs.get(session["program_id"])
    age = services.age_years(participant["birth_date"], season["start_date"])
    if program is not None and not (program["min_age"] <= age <= program["max_age"]):
        raise_err("ERR_AGE_INELIGIBLE", "Participant age falls outside the program's age corridor")
    # Household membership; FrontDeskStaff is exempt.
    if role == "HouseholdManager" and participant["household_id"] != uid:
        raise_err("ERR_NOT_HOUSEHOLD_MEMBER", "The participant must belong to the caller's household")
    rec = services.create_registration_record(session, participant, household)
    return success_object(registration_out(rec), 201)


@bp.route("/registrations", methods=["GET"])
def list_registrations():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    session_id = request.args.get("session_id")
    participant_id = request.args.get("participant_id")
    household_id = request.args.get("household_id")
    enrollment_status = request.args.get("enrollment_status")
    records = list(store.registrations.values())
    if session_id is not None:
        records = [r for r in records if r["session_id"] == session_id]
    if participant_id is not None:
        records = [r for r in records if r["participant_id"] == participant_id]
    if household_id is not None:
        records = [r for r in records if r["household_id"] == household_id]
    if enrollment_status is not None:
        records = [r for r in records if r["enrollment_status"] == enrollment_status]
    return list_response(records, registration_out)


@bp.route("/registrations/<registration_id>", methods=["GET"])
def get_registration(registration_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    rec = get_or_404(store.registrations, registration_id, "Registration")
    return success_object(registration_out(rec), 200)


@bp.route("/registrations/<registration_id>/drop", methods=["POST"])
def drop_registration(registration_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    rec = get_or_404(store.registrations, registration_id, "Registration")
    if rec["enrollment_status"] not in ("ENROLLED", "WAITLISTED"):
        raise_err("ERR_INVALID_STATE", "Only an ENROLLED or WAITLISTED registration can be dropped")
    session = store.sessions.get(rec["session_id"])
    if session is None or session["status"] not in ("PUBLISHED", "ACTIVE"):
        raise_err("ERR_SESSION_NOT_OPEN", "The session is not open for drops")
    if role == "HouseholdManager" and rec["household_id"] != uid:
        raise_err("ERR_NOT_HOUSEHOLD_MEMBER", "Only the owning household may drop this registration")
    services.drop_registration(rec)
    return success_object(registration_out(rec), 200)


@bp.route("/registrations/<registration_id>/payment", methods=["POST"])
def pay_registration(registration_id):
    uid, role = authenticate()
    authorize(role, ROLES)
    body = body_json()
    amount_cents = req_int(body, "amount_cents")
    method = req_enum(body, "method", PAYMENT_METHODS)
    check_int_range(amount_cents, 1, None, "amount_cents")
    rec = get_or_404(store.registrations, registration_id, "Registration")
    if not (rec["enrollment_status"] == "ENROLLED" and rec["payment_status"] == "PENDING"):
        raise_err("ERR_PAYMENT_NOT_ALLOWED", "Only an ENROLLED registration with PENDING payment can be paid")
    if role == "HouseholdManager" and rec["household_id"] != uid:
        raise_err("ERR_NOT_HOUSEHOLD_MEMBER", "Only the owning household may pay this registration")
    if amount_cents != rec["fee_charged_cents"]:
        raise_err("ERR_INCORRECT_AMOUNT", "amount_cents must equal the pinned fee_charged_cents exactly")
    tx = services.pay_registration(rec, amount_cents, method)
    return success_object(payment_out(tx), 201)
