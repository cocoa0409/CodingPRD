"""Enrollments: seats, confirmation, attendance (§3.4)."""

from datetime import timedelta

from flask import Blueprint, request

from core import calc
from core.auth import authenticate, own_participant_field
from core.envelope import created, listing, ok
from core.errors import ApiError
from core.shape import WITHDRAW_REASONS, body, req_enum, req_int, req_str
from core.store import fmt_ts, parse_ts, public, store
from services import cascade, derive
from services.state import must_exist, require_participant_active, transition

bp = Blueprint("enrollments", __name__)

HOLD_HOURS = 72


def _latest_needs(participant_id):
    rows = [a for a in store.find("Assessment", participant_id=participant_id)
            if a["kind"] == "NEEDS"]
    return rows[-1] if rows else None


@bp.route("/bereavement/enrollments", methods=["POST"])
def create_enrollment():
    authenticate(["IntakeCoordinator"])
    data = body()
    participant_id = req_str(data, "participant_id")
    cohort_id = req_str(data, "cohort_id")
    expected_version = req_int(data, "expected_cohort_version")

    participant = must_exist("Participant", participant_id)
    cohort = must_exist("Cohort", cohort_id)

    if expected_version != cohort["version"]:
        raise ApiError("ERR_STALE_COHORT_VERSION", "The cohort version has moved.")

    if cohort["status"] != "OPEN_ENROLLMENT":
        raise ApiError("ERR_COHORT_NOT_ENROLLING", "The cohort is not open for enrolment.")
    require_participant_active(participant)

    needs = _latest_needs(participant_id)
    if needs is None:
        raise ApiError("ERR_ASSESSMENT_REQUIRED", "The participant has no NEEDS assessment on file.")
    if needs["suicidality_flag"]:
        open_referral = any(r["status"] in ("WAITLISTED", "ASSIGNED")
                            for r in store.find("CounselingReferral", participant_id=participant_id))
        if not open_referral:
            raise ApiError("ERR_SUICIDALITY_REQUIRES_COUNSELING",
                           "An open counselling referral is required for this participant.")

    if cohort["loss_type"] != participant["loss_type"]:
        raise ApiError("ERR_LOSS_TYPE_MISMATCH", "The cohort loss type does not match the participant.")

    if cohort["seats_open"] < 1:
        raise ApiError("ERR_COHORT_FULL", "The cohort has no open seats.")
    for other in store.find("Enrollment", participant_id=participant_id, cohort_id=cohort_id):
        if other["status"] in ("HELD", "CONFIRMED", "ATTENDING", "COMPLETED"):
            raise ApiError("ERR_DUPLICATE_ENROLLMENT", "The participant already holds a seat here.")

    held_until = fmt_ts(store.now() + timedelta(hours=HOLD_HOURS))
    rec = store.create("Enrollment", {
        "participant_id": participant_id,
        "cohort_id": cohort_id,
        "status": "HELD",
        "held_until": held_until,
        "sessions_attended": 0,
        "attendance_ratio": 0,
        "withdraw_reason": None,
    })
    derive.recompute_seats(cohort)
    store.touch(cohort)
    if participant["service_status"] == "ASSESSED":
        participant["service_status"] = "ACTIVE"
        store.touch(participant)
    return created(public(rec))


@bp.route("/bereavement/enrollments/<eid>", methods=["GET"])
def read_enrollment(eid):
    ctx = authenticate(["IntakeCoordinator", "ProgramDirector", "Participant"])
    rec = must_exist("Enrollment", eid)
    own_participant_field(ctx, rec)
    return ok(public(rec))


@bp.route("/bereavement/enrollments", methods=["GET"])
def list_enrollments():
    authenticate(["IntakeCoordinator", "ProgramDirector"])
    rows = store.all("Enrollment")
    for key in ("participant_id", "cohort_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return listing(rows, public)


@bp.route("/bereavement/enrollments/<eid>/confirm", methods=["POST"])
def confirm_enrollment(eid):
    ctx = authenticate(["IntakeCoordinator", "Participant"])
    rec = must_exist("Enrollment", eid)
    own_participant_field(ctx, rec)
    body()
    transition(rec, {"HELD"})
    cohort = store.get("Cohort", rec["cohort_id"])
    if cohort is None or cohort["status"] != "OPEN_ENROLLMENT":
        raise ApiError("ERR_COHORT_NOT_ENROLLING", "The cohort is not open for enrolment.")
    held_until = parse_ts(rec["held_until"])
    if held_until is not None and store.now() > held_until:
        raise ApiError("ERR_INVALID_STATE", "The hold window has lapsed.")
    rec["status"] = "CONFIRMED"
    store.touch(rec)
    derive.recompute_seats(cohort)
    store.touch(cohort)
    return ok(public(rec))


@bp.route("/bereavement/enrollments/<eid>/withdraw", methods=["POST"])
def withdraw_enrollment(eid):
    ctx = authenticate(["IntakeCoordinator", "Participant"])
    rec = must_exist("Enrollment", eid)
    own_participant_field(ctx, rec)
    data = body()
    reason = req_enum(data, "withdraw_reason", WITHDRAW_REASONS)
    transition(rec, {"HELD", "CONFIRMED", "ATTENDING"})
    rec["status"] = "WITHDRAWN"
    rec["withdraw_reason"] = reason
    store.touch(rec)
    cohort = store.get("Cohort", rec["cohort_id"])
    if cohort is not None:
        cascade.seat_released(cohort)
    return ok(public(rec))


@bp.route("/bereavement/enrollments/<eid>/attendance", methods=["POST"])
def log_attendance(eid):
    authenticate(["IntakeCoordinator"])
    rec = must_exist("Enrollment", eid)
    data = body()
    delta = req_int(data, "sessions_delta")
    cohort = store.get("Cohort", rec["cohort_id"])
    total = cohort["sessions_total"] if cohort else 0
    attended = rec["sessions_attended"] + delta
    if attended > total:
        attended = total
    if attended < 0:
        attended = 0
    rec["sessions_attended"] = attended
    rec["attendance_ratio"] = calc.attendance_ratio(attended, total) if total else 0
    store.touch(rec)
    return ok(public(rec))
