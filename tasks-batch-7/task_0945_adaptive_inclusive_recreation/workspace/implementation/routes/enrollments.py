"""Enrolments and enrolment charges."""

from datetime import timedelta

from flask import Blueprint

import calc
import engine
import enums
import lookups as L
import serial
from ctx import (
    Body,
    check_transition,
    check_version,
    endpoint,
    pagination,
    paginate,
    resolve_one,
)
from envelope import ok, ok_list
from errors import ApiError
from store import db, insert, parse_instant, sort_rows, touch

bp = Blueprint("enrollments", __name__)

ENROLLMENT_TERMINALS = ("ATTENDED", "NO_SHOW", "WITHDRAWN", "DENIED")


# --- caregiver-scope resolvers ---------------------------------------------

def _scope_body_participant(context):
    row = db.get("participants", context.body.get("participant_id"))
    return [row["id"]] if row else []


def _scope_enrollment_param(context):
    row = db.get("enrollments", context.params.get("enrollment_id"))
    return [row["participant_id"]] if row else []


def _scope_enrollment_filter(context):
    row = db.get("participants", context.q("participant_id"))
    return [row["id"]] if row else []


def _scope_charge_param(context):
    charge = db.get("enrollment_charges", context.params.get("charge_id"))
    enrollment = L.enrollment_of_charge(charge)
    return [enrollment["participant_id"]] if enrollment else []


def _scope_charge_filter(context):
    enrollment = db.get("enrollments", context.q("enrollment_id"))
    return [enrollment["participant_id"]] if enrollment else []


def _attendance_session(context):
    enrollment = db.get("enrollments", context.params.get("enrollment_id"))
    return L.session_of_enrollment(enrollment) if enrollment else None


# ---------------------------------------------------------------------------
# enrolments
# ---------------------------------------------------------------------------

@bp.route("/recreation/enrollments", methods=["POST"])
@endpoint(roles=("IntakeCoordinator", "CaregiverUser"), scope=_scope_body_participant)
def create_enrollment(context):
    raw = context.body
    participant_id = raw.get("participant_id")
    session_id = raw.get("session_id")

    participant = None
    if isinstance(participant_id, str):
        participant = resolve_one("participant", participant_id)     # rung 11
    session = None
    if isinstance(session_id, str):
        session = resolve_one("session", session_id)                 # rung 13

    band = None
    if participant is not None:
        band = calc.fee_scale_band_match(participant)                # rung 18
        if band is None:
            raise ApiError("ERR_FEE_BAND_NOT_FOUND")

    body = Body(raw)                                                 # rung 22
    body.req_string("participant_id")
    body.req_string("session_id")
    expected_version = body.req_int("expected_session_version")
    transport_requested = body.opt_bool("transport_requested", False)
    body.check_enums()                                               # rung 23

    if participant is None:
        participant = resolve_one("participant", participant_id)
    if session is None:
        session = resolve_one("session", session_id)
    if band is None:
        band = calc.fee_scale_band_match(participant)
        if band is None:
            raise ApiError("ERR_FEE_BAND_NOT_FOUND")

    check_version(expected_version, session)                         # rung 25

    if session["status"] != "OPEN":                                  # rung 28
        raise ApiError("ERR_SESSION_NOT_OPEN")

    start = parse_instant(session["start_at"])                       # rung 29
    if start - db.clock_dt < timedelta(hours=calc.SESSION_ENROLLMENT_CUTOFF_HOURS):
        raise ApiError("ERR_ENROLLMENT_CUTOFF_PASSED")

    for existing in L.enrollments_of_participant(participant):       # rung 31
        if (
            existing["session_id"] == session["id"]
            and existing["enrollment_status"] in calc.LIVE_ENROLLMENT_STATUSES
        ):
            raise ApiError("ERR_DUPLICATE_ENROLLMENT")

    if participant["status"] != "ACTIVE":                            # rung 33
        raise ApiError("ERR_PARTICIPANT_NOT_ACTIVE")

    new_end = parse_instant(session["end_at"])                       # rung 43
    for existing in L.enrollments_of_participant(participant):
        if existing["enrollment_status"] not in calc.LIVE_ENROLLMENT_STATUSES:
            continue
        other = L.session_of_enrollment(existing)
        if other is None:
            continue
        other_start = parse_instant(other["start_at"])
        other_end = parse_instant(other["end_at"])
        if start < other_end and other_start < new_end:
            raise ApiError("ERR_PARTICIPANT_TIME_CONFLICT")

    if calc.financial_gate_blocked(participant):                     # rung 60
        raise ApiError("ERR_FAMILY_BALANCE_OUTSTANDING")

    program = L.program_of_session(session)
    enrollment = insert(
        "enrollments",
        {
            "participant_id": participant["id"],
            "session_id": session["id"],
            "transport_requested": transport_requested,
            "enrollment_status": "REQUESTED",
            "funding_status": "QUOTED",
            "waitlist_score": 0,
            "promoted_at": None,
            "effective_support_tier_at_session": calc.effective_support_tier(
                participant, session
            ),
        },
    )
    charge = insert(
        "enrollment_charges",
        {
            "enrollment_id": enrollment["id"],
            "fee_scale_band_id": band["id"],
            "program_fee_cents": calc.participant_session_fee_cents(band, program, session),
            "scholarship_applied_cents": 0,
            "copay_cents": 0,
            "transport_fee_cents": 0,
            "sibling_discount_bp": 0,
            "family_responsibility_cents": 0,
            "amount_paid_cents": 0,
            "balance_cents": 0,
            "status": "QUOTED",
        },
    )
    engine.recompute_charge(charge, bump=False)
    touch(session)
    return ok(serial.dump(enrollment), 201)


@bp.route("/recreation/enrollments", methods=["GET"])
@endpoint(roles=enums.ALL_ROLES, scope=_scope_enrollment_filter)
def list_enrollments(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("enrollments"))
    participant_id = context.q("participant_id")
    session_id = context.q("session_id")
    enrollment_status = context.q("enrollment_status")
    funding_status = context.q("funding_status")
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    if session_id is not None:
        rows = [r for r in rows if r["session_id"] == session_id]
    if enrollment_status is not None:
        rows = [r for r in rows if r["enrollment_status"] == enrollment_status]
    if funding_status is not None:
        rows = [r for r in rows if r["funding_status"] == funding_status]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/enrollments/<enrollment_id>", methods=["GET"])
@endpoint(roles=enums.ALL_ROLES, scope=_scope_enrollment_param)
def read_enrollment(context, enrollment_id):
    return ok(serial.dump(resolve_one("enrollment", enrollment_id)))


@bp.route("/recreation/enrollments/<enrollment_id>/confirm", methods=["POST"])
@endpoint(roles=("IntakeCoordinator",))
def confirm_enrollment(context, enrollment_id):
    enrollment = resolve_one("enrollment", enrollment_id)
    body = Body(context.body)
    on_full = body.opt_enum("on_full", enums.ON_FULL, "ERROR")
    body.check_enums()
    check_transition(enrollment["enrollment_status"], ("REQUESTED",), ENROLLMENT_TERMINALS)

    session = L.session_of_enrollment(enrollment)
    if session["status"] != "OPEN":
        raise ApiError("ERR_SESSION_NOT_OPEN")

    routed = engine.confirm_gate(enrollment, on_full)
    if routed == "WAITLIST":
        enrollment["enrollment_status"] = "WAITLISTED"
        enrollment["waitlist_score"] = calc.waitlist_priority_score(enrollment)
        touch(enrollment)
    elif routed == "DENY":
        enrollment["enrollment_status"] = "DENIED"
        for award in L.awards_of_enrollment(enrollment):
            if award["status"] in ("PROPOSED", "ENCUMBERED", "PARTIALLY_DISBURSED"):
                engine.release_award(award, force_released=True)
        touch(enrollment)
        engine.recompute_charge_of(enrollment)
    else:
        engine.apply_confirmation(enrollment)
    return ok(serial.dump(enrollment))


@bp.route("/recreation/enrollments/<enrollment_id>/withdraw", methods=["POST"])
@endpoint(roles=("IntakeCoordinator", "CaregiverUser"), scope=_scope_enrollment_param)
def withdraw_enrollment(context, enrollment_id):
    enrollment = resolve_one("enrollment", enrollment_id)
    check_transition(
        enrollment["enrollment_status"],
        ("REQUESTED", "WAITLISTED", "CONFIRMED"),
        ENROLLMENT_TERMINALS,
    )
    if enrollment["enrollment_status"] == "CONFIRMED":
        session = L.session_of_enrollment(enrollment)
        if session["status"] not in ("OPEN", "STAFFING_LOCKED"):
            raise ApiError("ERR_INVALID_STATE", "The session no longer accepts withdrawals.")
    engine.withdraw_enrollment(enrollment)
    return ok(serial.dump(enrollment))


@bp.route("/recreation/enrollments/<enrollment_id>/attendance", methods=["POST"])
@endpoint(roles=("ActivityLead",), delivery=_attendance_session)
def record_attendance(context, enrollment_id):
    enrollment = resolve_one("enrollment", enrollment_id)
    body = Body(context.body)
    outcome = body.req_enum("outcome", enums.OUTCOMES)
    body.check_enums()
    check_transition(enrollment["enrollment_status"], ("CONFIRMED",), ENROLLMENT_TERMINALS)

    session = L.session_of_enrollment(enrollment)
    if session["status"] != "STAFFING_LOCKED":
        raise ApiError("ERR_INVALID_STATE", "The session is not staffing-locked.")
    if db.clock_dt < parse_instant(session["start_at"]):
        raise ApiError("ERR_INVALID_STATE", "The session has not started yet.")

    enrollment["enrollment_status"] = outcome
    touch(enrollment)
    for booking in L.bookings_of_enrollment(enrollment):
        if booking["status"] != "CONFIRMED":
            continue
        booking["status"] = "RIDDEN" if outcome == "ATTENDED" else "NO_SHOW"
        touch(booking)
        if outcome == "NO_SHOW":
            run = L.run_of_booking(booking)
            if run is not None:
                engine.refresh_run_counters(run)
                engine.refresh_run_status(run)
    engine.refresh_session_counters(session)
    return ok(serial.dump(enrollment))


# ---------------------------------------------------------------------------
# enrolment charges
# ---------------------------------------------------------------------------

@bp.route("/recreation/enrollment-charges", methods=["GET"])
@endpoint(roles=enums.ALL_ROLES, scope=_scope_charge_filter)
def list_charges(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("enrollment_charges"))
    enrollment_id = context.q("enrollment_id")
    band_id = context.q("fee_scale_band_id")
    status = context.q("status")
    if enrollment_id is not None:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if band_id is not None:
        rows = [r for r in rows if r["fee_scale_band_id"] == band_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/enrollment-charges/<charge_id>", methods=["GET"])
@endpoint(roles=enums.ALL_ROLES, scope=_scope_charge_param)
def read_charge(context, charge_id):
    return ok(serial.dump(resolve_one("charge", charge_id)))


@bp.route("/recreation/enrollment-charges/<charge_id>/payments", methods=["POST"])
@endpoint(roles=("FundingOfficer",), financial=True)
def record_payment(context, charge_id):
    charge = resolve_one("charge", charge_id)
    body = Body(context.body)
    amount_cents = body.req_int("amount_cents")
    body.check_enums()
    charge["amount_paid_cents"] += amount_cents
    engine.recompute_charge(charge)
    return ok(serial.dump(charge))
