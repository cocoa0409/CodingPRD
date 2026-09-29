"""Concussion cases, the return-to-participation ladder and consultant clearances."""
from flask import Blueprint

import constants as C
import serializers as S
import validation as V
from db import db, sort_rows, stamp_new, touch
from errors import ApiError
from response import created, ok, ok_list, paginate, read_pagination
from services import calc

bp = Blueprint("cases", __name__)

_READ_ROLES = C.ALL_ROLES
_STAGE_FROM_STATES = ("MANDATORY_REMOVAL", "RTP_IN_PROGRESS")
_CLEARANCE_FROM_STATES = ("MANDATORY_REMOVAL", "RTP_IN_PROGRESS")
_EXEMPTION_FROM_STATES = (
    "MANDATORY_REMOVAL",
    "RTP_IN_PROGRESS",
    "PENDING_INC_CLEARANCE",
    "STAGE_FROZEN",
)


# ------------------------------------------------------------------- utilities
def _freeze_guard(case):
    """Rung 11."""
    if case["case_status"] == "STAGE_FROZEN":
        raise ApiError("ERR_CASE_STAGE_FROZEN")
    club = db.clubs.get(case["club_id"])
    if club is not None and club["status"] == "SANCTIONED":
        raise ApiError("ERR_CASE_STAGE_FROZEN")


def _latest_clearance(case_id):
    rows = calc.case_clearances(case_id)
    if not rows:
        return None
    return max(rows, key=lambda c: (c["requested_at"], c["created_at"], c["_seq"]))


def _apply_prolonged_watch(case):
    """Force PROLONGED_SYMPTOM_WATCH and drive the player. Returns True when moved."""
    if case["monitoring_status"] != "ACTIVE_SYMPTOM_WATCH":
        return False
    case["monitoring_status"] = "PROLONGED_SYMPTOM_WATCH"
    player = db.players.get(case["player_id"])
    if player is not None and player["availability_status"] != "PROTOCOL_RESTRICTED":
        player["availability_status"] = "PROTOCOL_RESTRICTED"
        touch(player)
    return True


def _revoke_highest_passed_step(case):
    step = calc.latest_passed_step(case["id"])
    if step is None:
        return None
    step["status"] = "REVOKED"
    touch(step)
    return step


def _more_rest_regression(case):
    """Shared by a consultant more-rest denial and a symptomatic check."""
    _revoke_highest_passed_step(case)
    case["rtp_stage"] = max(0, int(case["rtp_stage"]) - 1)
    case["earliest_return_at"] = None
    if case["case_status"] == "PENDING_INC_CLEARANCE":
        case["case_status"] = "RTP_IN_PROGRESS"


# ---------------------------------------------------------------- return steps
@bp.post("/concussion-cases/<row_id>/return-steps")
def open_return_step(row_id):
    actor = V.authenticate(["ClubPhysician"])
    b = V.body()
    stage_index = V.req_int(b, "stage_index", 1, 5)

    case = V.get_case(row_id)
    clinician = V.role_identity(actor)
    V.physician_scope(actor, case["club_id"])
    V.not_suspended(clinician)
    if case["case_status"] not in _STAGE_FROM_STATES and case["case_status"] != "STAGE_FROZEN":
        raise ApiError("ERR_CASE_STATE_INVALID",
                       message="A stage may only be opened from MANDATORY_REMOVAL or "
                               "RTP_IN_PROGRESS.")
    _freeze_guard(case)
    V.credential_valid(clinician)

    min_start_at = calc.compute_min_start_at(case, stage_index)
    if min_start_at is not None and db.now < min_start_at:
        raise ApiError("ERR_STAGE_REST_BUFFER_VIOLATION")
    if stage_index != int(case["rtp_stage"]) + 1:
        raise ApiError("ERR_STAGE_SEQUENCE_VIOLATION")
    for existing in calc.case_steps(case["id"]):
        if existing["status"] == "IN_PROGRESS":
            raise ApiError("ERR_STEP_ALREADY_IN_PROGRESS")

    attempt_index = 1 + sum(
        1 for s in calc.case_steps(case["id"]) if s["stage_index"] == stage_index)
    step = {
        "case_id": case["id"],
        "stage_index": stage_index,
        "stage_name": C.STAGE_NAMES[stage_index],
        "attempt_index": attempt_index,
        "status": "IN_PROGRESS",
        "started_at": db.now,
        "min_start_at": min_start_at if min_start_at is not None else case["diagnosis_at"],
        "dwell_complete_at": calc.compute_dwell_complete_at(db.now, stage_index),
        "evaluated_at": None,
        "cleared_by_clinician_id": None,
        "evaluation_symptom_score": None,
    }
    stamp_new(step)
    db.return_steps[step["id"]] = step

    if case["case_status"] == "MANDATORY_REMOVAL":
        case["case_status"] = "RTP_IN_PROGRESS"
    touch(case)
    return created(S.step_out(step))


@bp.post("/return-steps/<row_id>/evaluate")
def evaluate_return_step(row_id):
    actor = V.authenticate(["ClubPhysician"])
    b = V.body()
    outcome = V.req_enum(b, "outcome", C.STEP_OUTCOMES)
    symptom_score = V.req_int(b, "symptom_score", 0, 20)

    step = V.get_step(row_id)
    case = db.concussion_cases.get(step["case_id"])
    clinician = V.role_identity(actor)
    V.physician_scope(actor, case["club_id"])
    V.not_suspended(clinician)
    if step["status"] != "IN_PROGRESS":
        raise ApiError("ERR_STEP_STATE_INVALID")
    _freeze_guard(case)
    if case.get("heightened_review_required") and clinician["id"] == case["diagnosing_clinician_id"]:
        raise ApiError("ERR_HEIGHTENED_REVIEW_CLINICIAN_REQUIRED")
    V.credential_valid(clinician)
    if outcome == "PASS" and db.now < step["dwell_complete_at"]:
        raise ApiError("ERR_STAGE_DWELL_NOT_MET")
    if outcome == "PASS" and symptom_score >= C.SYMPTOM_RECURRENCE_THRESHOLD:
        raise ApiError("ERR_SYMPTOM_OUTCOME_MISMATCH")
    if outcome == "SYMPTOM_RECURRENCE" and symptom_score < C.SYMPTOM_RECURRENCE_THRESHOLD:
        raise ApiError("ERR_SYMPTOM_OUTCOME_MISMATCH")

    step["evaluated_at"] = db.now
    step["cleared_by_clinician_id"] = clinician["id"]
    step["evaluation_symptom_score"] = symptom_score

    if outcome == "PASS":
        step["status"] = "PASSED"
        case["rtp_stage"] = step["stage_index"]
        if step["stage_index"] == 5:
            case["earliest_return_at"] = calc.final_accrued(
                step["evaluated_at"], int(case["recurrence_count"]))
    else:
        step["status"] = "FAILED_SYMPTOM_RECURRENCE"
        case["recurrence_count"] = int(case["recurrence_count"]) + 1
        case["last_symptomatic_at"] = db.now
        case["rtp_stage"] = max(0, int(step["stage_index"]) - 2)
        case["earliest_return_at"] = None
        case["severity_index"] = calc.compute_severity_index(case)
        if case["recurrence_count"] >= 2:
            _apply_prolonged_watch(case)

    touch(step)
    touch(case)
    return ok(S.step_out(step))


@bp.get("/return-steps/<row_id>")
def get_return_step(row_id):
    actor = V.authenticate(_READ_ROLES)
    step = V.get_step(row_id)
    V.role_identity(actor)
    return ok(S.step_out(step))


@bp.get("/return-steps")
def list_return_steps():
    actor = V.authenticate(_READ_ROLES)
    limit, offset = read_pagination()
    case_id = V.filter_str("case_id")
    cleared_by = V.filter_str("cleared_by_clinician_id")
    stage_index = V.filter_int("stage_index", 1, 5)
    status = V.filter_enum("status", C.STEP_STATUSES)
    V.role_identity(actor)

    rows = sort_rows(list(db.return_steps.values()))
    if case_id is not None:
        rows = [r for r in rows if r["case_id"] == case_id]
    if cleared_by is not None:
        rows = [r for r in rows if r.get("cleared_by_clinician_id") == cleared_by]
    if stage_index is not None:
        rows = [r for r in rows if r["stage_index"] == stage_index]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.step_out(r) for r in page], limit, offset, total)


# ------------------------------------------------------------- inc clearances
@bp.post("/concussion-cases/<row_id>/inc-clearances")
def request_clearance(row_id):
    actor = V.authenticate(["ClubPhysician"])
    b = V.body()
    inc_clinician_id = V.req_id(b, "inc_clinician_id")
    expected_case_version = V.req_int(b, "expected_case_version", 0)

    case = V.get_case(row_id)
    nominee = V.get_clinician(inc_clinician_id)
    clinician = V.role_identity(actor)
    V.physician_scope(actor, case["club_id"])
    V.not_suspended(clinician)
    V.not_suspended(nominee)
    if case["case_status"] not in _CLEARANCE_FROM_STATES \
            and case["case_status"] != "STAGE_FROZEN":
        raise ApiError("ERR_CASE_STATE_INVALID",
                       message="Final clearance may only be requested from MANDATORY_REMOVAL "
                               "or RTP_IN_PROGRESS.")
    _freeze_guard(case)
    if case["version"] != expected_case_version:
        raise ApiError("ERR_STALE_CASE_VERSION")

    if nominee["affiliation"] != "INDEPENDENT_CONSULTANT" or nominee.get("club_id") is not None:
        raise ApiError("ERR_INC_NOT_INDEPENDENT")
    if nominee["id"] == case["diagnosing_clinician_id"]:
        raise ApiError("ERR_INC_NOT_INDEPENDENT")
    evaluation = db.sideline_evaluations.get(case["sideline_evaluation_id"])
    if evaluation is not None and evaluation.get("inc_clinician_id") == nominee["id"]:
        raise ApiError("ERR_INC_NOT_INDEPENDENT")

    V.credential_valid(clinician)
    V.credential_valid(nominee)

    steps = calc.case_steps(case["id"])
    if not steps:
        raise ApiError("ERR_NO_RETURN_STEPS_RECORDED")
    if not calc.all_stages_passed(case["id"]):
        raise ApiError("ERR_RTP_STAGES_INCOMPLETE")

    for existing in calc.case_clearances(case["id"]):
        if existing["status"] == "PENDING":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    row = {
        "case_id": case["id"],
        "inc_clinician_id": nominee["id"],
        "requested_by_clinician_id": clinician["id"],
        "requested_at": db.now,
        "decided_at": None,
        "expires_at": None,
        "status": "PENDING",
        "decision_notes": None,
        "documented_stage_count": calc.documented_stage_count(case["id"]),
    }
    stamp_new(row)
    db.inc_clearances[row["id"]] = row

    case["case_status"] = "PENDING_INC_CLEARANCE"
    touch(case)
    return created(S.clearance_out(row))


@bp.post("/inc-clearances/<row_id>/decide")
def decide_clearance(row_id):
    actor = V.authenticate(["IndependentConsultant"])
    b = V.body()
    decision = V.req_enum(b, "decision", C.CLEARANCE_DECISIONS)
    decision_notes = V.req_str(b, "decision_notes")

    clearance = V.get_clearance(row_id)
    clinician = V.role_identity(actor)
    V.not_suspended(clinician)
    if clearance["status"] != "PENDING":
        raise ApiError("ERR_CLEARANCE_STATE_INVALID")
    if clearance["inc_clinician_id"] != clinician["id"]:
        raise ApiError("ERR_INC_ASSIGNMENT_MISMATCH")
    V.credential_valid(clinician)

    case = db.concussion_cases.get(clearance["case_id"])
    if decision == "APPROVED":
        if case is None or case["case_status"] != "PENDING_INC_CLEARANCE":
            raise ApiError("ERR_CASE_STATE_INVALID",
                           message="Approval requires the case to be PENDING_INC_CLEARANCE.")
        if not calc.all_stages_passed(case["id"]):
            raise ApiError("ERR_RTP_STAGES_INCOMPLETE")

    clearance["decision_notes"] = decision_notes
    clearance["decided_at"] = db.now
    clearance["status"] = decision

    if decision == "APPROVED":
        clearance["expires_at"] = db.now + calc.hours(C.INC_CLEARANCE_VALIDITY_HOURS)
        touch(clearance)
        return ok(S.clearance_out(clearance))

    touch(clearance)
    if case is not None:
        if decision == "DENIED_MORE_REST":
            _more_rest_regression(case)
        elif case["case_status"] == "PENDING_INC_CLEARANCE":
            case["case_status"] = "RTP_IN_PROGRESS"
        touch(case)
    return ok(S.clearance_out(clearance))


@bp.get("/inc-clearances/<row_id>")
def get_clearance(row_id):
    actor = V.authenticate(_READ_ROLES)
    clearance = V.get_clearance(row_id)
    V.role_identity(actor)
    return ok(S.clearance_out(clearance))


@bp.get("/inc-clearances")
def list_clearances():
    actor = V.authenticate(_READ_ROLES)
    limit, offset = read_pagination()
    case_id = V.filter_str("case_id")
    inc_clinician_id = V.filter_str("inc_clinician_id")
    requested_by = V.filter_str("requested_by_clinician_id")
    status = V.filter_enum("status", C.CLEARANCE_STATUSES)
    V.role_identity(actor)

    rows = sort_rows(list(db.inc_clearances.values()))
    if case_id is not None:
        rows = [r for r in rows if r["case_id"] == case_id]
    if inc_clinician_id is not None:
        rows = [r for r in rows if r["inc_clinician_id"] == inc_clinician_id]
    if requested_by is not None:
        rows = [r for r in rows if r["requested_by_clinician_id"] == requested_by]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.clearance_out(r) for r in page], limit, offset, total)


# --------------------------------------------------------------- case actions
@bp.post("/concussion-cases/<row_id>/return-to-contact")
def return_to_contact(row_id):
    actor = V.authenticate(["ClubPhysician"])
    b = V.body()
    V.opt_str(b, "documentation_note")

    case = V.get_case(row_id)
    clinician = V.role_identity(actor)
    V.physician_scope(actor, case["club_id"])
    V.not_suspended(clinician)
    if case["case_status"] not in ("PENDING_INC_CLEARANCE", "STAGE_FROZEN"):
        raise ApiError("ERR_CASE_STATE_INVALID",
                       message="Return to contact requires the case to be PENDING_INC_CLEARANCE.")
    _freeze_guard(case)
    V.credential_valid(clinician)

    earliest = case.get("earliest_return_at")
    if earliest is None or db.now < earliest:
        raise ApiError("ERR_RETURN_BEFORE_EARLIEST_DATE")

    latest = _latest_clearance(case["id"])
    if latest is not None:
        if latest["status"] == "EXPIRED":
            raise ApiError("ERR_INC_CLEARANCE_EXPIRED")
        if latest["status"] == "APPROVED" and (
                latest.get("expires_at") is None or latest["expires_at"] <= db.now):
            raise ApiError("ERR_INC_CLEARANCE_EXPIRED")
    if latest is None or latest["status"] != "APPROVED":
        raise ApiError("ERR_INC_CLEARANCE_MISSING")

    player = db.players.get(case["player_id"])
    if player["baseline_status"] == "NONE":
        raise ApiError("ERR_BASELINE_NOT_ESTABLISHED")
    if player["baseline_status"] == "RETEST_REQUIRED":
        raise ApiError("ERR_BASELINE_RETEST_REQUIRED")

    case["case_status"] = "CLEARED_FOR_CONTACT"
    case["cleared_for_contact_at"] = db.now
    case["heightened_review_required"] = False
    case["frozen_from_status"] = None
    released = False
    if case["roster_exemption_status"] == "GRANTED":
        case["roster_exemption_status"] = "RELEASED"
        released = True
    touch(case)

    player["availability_status"] = "AVAILABLE"
    touch(player)

    if released:
        club = db.clubs.get(case["club_id"])
        if club is not None:
            touch(club)

    consultant = db.clinicians.get(latest["inc_clinician_id"])
    if consultant is not None:
        consultant["cases_cleared_count"] = int(consultant.get("cases_cleared_count") or 0) + 1
        consultant["updated_at"] = db.now

    return ok(S.case_out(case))


@bp.post("/concussion-cases/<row_id>/roster-exemption")
def grant_roster_exemption(row_id):
    actor = V.authenticate(["ClubComplianceOfficer"])
    case = V.get_case(row_id)
    V.officer_scope(actor, case["club_id"])
    if case["case_status"] not in _EXEMPTION_FROM_STATES:
        raise ApiError("ERR_CASE_STATE_INVALID",
                       message="A cleared case may not be granted a roster exemption.")
    if case["roster_exemption_status"] != "NONE":
        raise ApiError("ERR_EXEMPTION_ALREADY_GRANTED")

    club = db.clubs.get(case["club_id"])
    used = calc.exemption_slots_used(club["id"])
    if club["exemption_slots_total"] - used < 1:
        raise ApiError("ERR_NO_EXEMPTION_SLOTS")

    case["roster_exemption_status"] = "GRANTED"
    touch(case)
    touch(club)
    return ok(S.case_out(case))


@bp.post("/concussion-cases/<row_id>/symptom-check")
def symptom_check(row_id):
    actor = V.authenticate(["ClubPhysician"])
    b = V.body()
    symptom_score = V.req_int(b, "symptom_score", 0, 20)

    case = V.get_case(row_id)
    clinician = V.role_identity(actor)
    V.physician_scope(actor, case["club_id"])
    V.not_suspended(clinician)
    V.credential_valid(clinician)

    case["last_symptom_check_score"] = symptom_score

    if symptom_score >= C.SYMPTOM_RECURRENCE_THRESHOLD:
        case["last_symptomatic_at"] = db.now
        case["recurrence_count"] = int(case["recurrence_count"]) + 1
        case["severity_index"] = calc.compute_severity_index(case)
        if case["case_status"] == "PENDING_INC_CLEARANCE":
            for clearance in calc.case_clearances(case["id"]):
                if clearance["status"] == "PENDING":
                    clearance["status"] = "DENIED_MORE_REST"
                    clearance["decided_at"] = db.now
                    touch(clearance)
            _more_rest_regression(case)
        if case["recurrence_count"] >= 2:
            _apply_prolonged_watch(case)
    elif (symptom_score == 0
            and case["monitoring_status"] == "OFFSEASON_MONITORING"
            and case["case_status"] == "CLEARED_FOR_CONTACT"):
        case["monitoring_status"] = "MONITORING_CLOSED"

    touch(case)
    return ok(S.case_out(case))


@bp.get("/concussion-cases/<row_id>")
def get_case(row_id):
    actor = V.authenticate(_READ_ROLES)
    case = V.get_case(row_id)
    V.role_identity(actor)
    return ok(S.case_out(case))


@bp.get("/concussion-cases")
def list_cases():
    actor = V.authenticate(_READ_ROLES)
    limit, offset = read_pagination()
    player_id = V.filter_str("player_id")
    club_id = V.filter_str("club_id")
    evaluation_id = V.filter_str("sideline_evaluation_id")
    diagnosing = V.filter_str("diagnosing_clinician_id")
    prior_case_id = V.filter_str("prior_case_id")
    case_status = V.filter_enum("case_status", C.CASE_STATUSES)
    monitoring_status = V.filter_enum("monitoring_status", C.MONITORING_STATUSES)
    exemption_status = V.filter_enum("roster_exemption_status", C.EXEMPTION_STATUSES)
    season_year = V.filter_int("season_year")
    V.role_identity(actor)

    rows = sort_rows(list(db.concussion_cases.values()))
    if player_id is not None:
        rows = [r for r in rows if r["player_id"] == player_id]
    if club_id is not None:
        rows = [r for r in rows if r["club_id"] == club_id]
    if evaluation_id is not None:
        rows = [r for r in rows if r["sideline_evaluation_id"] == evaluation_id]
    if diagnosing is not None:
        rows = [r for r in rows if r["diagnosing_clinician_id"] == diagnosing]
    if prior_case_id is not None:
        rows = [r for r in rows if r.get("prior_case_id") == prior_case_id]
    if case_status is not None:
        rows = [r for r in rows if r["case_status"] == case_status]
    if monitoring_status is not None:
        rows = [r for r in rows if r["monitoring_status"] == monitoring_status]
    if exemption_status is not None:
        rows = [r for r in rows if r["roster_exemption_status"] == exemption_status]
    if season_year is not None:
        rows = [r for r in rows if r["season_year"] == season_year]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.case_out(r) for r in page], limit, offset, total)
