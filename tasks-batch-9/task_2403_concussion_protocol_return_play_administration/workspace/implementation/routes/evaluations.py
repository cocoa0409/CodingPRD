"""Sideline evaluation, locker-room examination and diagnosis (PRD §3.3-§3.5)."""
from datetime import timedelta

from flask import Blueprint

import constants as C
import serializers as S
import validation as V
from db import db, sort_rows, stamp_new, touch
from errors import ApiError
from response import created, ok, ok_list, paginate, read_pagination
from services import calc

bp = Blueprint("evaluations", __name__)


def _player_of(evaluation):
    return db.players.get(evaluation["player_id"])


def _game_of(evaluation):
    return db.games.get(evaluation["game_id"])


def _require_game_in_progress(evaluation):
    game = _game_of(evaluation)
    if game is None or game["status"] != "IN_PROGRESS":
        raise ApiError("ERR_GAME_NOT_IN_PROGRESS")


def _require_exam_long_enough(evaluation):
    started = evaluation.get("exam_started_at")
    if started is None:
        raise ApiError("ERR_LOCKER_ROOM_EXAM_TOO_SHORT")
    minutes = calc.exam_duration_minutes(started, db.now)
    if minutes < C.MIN_LOCKER_ROOM_EXAM_MINUTES:
        raise ApiError("ERR_LOCKER_ROOM_EXAM_TOO_SHORT")
    return minutes


@bp.post("/sideline-evaluations")
def initiate_evaluation():
    actor = V.authenticate(["ClubPhysician", "UnaffiliatedObserver"])
    b = V.body()
    player_id = V.req_id(b, "player_id")
    game_id = V.req_id(b, "game_id")
    trigger_source = V.req_enum(b, "trigger_source", C.TRIGGER_SOURCES)
    if actor.role == "ClubPhysician" and trigger_source not in C.PHYSICIAN_ALLOWED_TRIGGERS:
        V.bad("A ClubPhysician may not declare trigger_source %s." % trigger_source)
    if actor.role != "UnaffiliatedObserver" and trigger_source == "UNAFFILIATED_OBSERVER":
        V.bad("Only an UnaffiliatedObserver may declare trigger_source UNAFFILIATED_OBSERVER.")

    player = V.get_player(player_id)
    game = V.get_game(game_id)
    clinician = V.role_identity(actor)
    V.physician_scope(actor, player["club_id"])
    V.not_suspended(clinician)
    if player["club_id"] not in (game["home_club_id"], game["away_club_id"]):
        raise ApiError("ERR_PLAYER_CLUB_MISMATCH")
    V.credential_valid(clinician)
    if game["status"] != "IN_PROGRESS":
        raise ApiError("ERR_GAME_NOT_IN_PROGRESS")

    mandatory = trigger_source in C.MANDATORY_REMOVAL_TRIGGERS
    minutes = (C.MANDATORY_EVAL_DEADLINE_MINUTES if mandatory
               else C.DISCRETIONARY_EVAL_DEADLINE_MINUTES)
    row = {
        "player_id": player["id"],
        "game_id": game["id"],
        "initiating_clinician_id": clinician["id"],
        "evaluating_clinician_id": None,
        "inc_clinician_id": None,
        "trigger_source": trigger_source,
        "mandatory_removal": mandatory,
        "status": "INITIATED",
        "initiated_at": db.now,
        "protocol_deadline_at": db.now + timedelta(minutes=minutes),
        "no_go_signs": [],
        "screen_symptom_score": None,
        "screened_at": None,
        "exam_started_at": None,
        "inc_block_ends_at": None,
        "exam_completed_at": None,
        "exam_duration_minutes": None,
        "diagnosis_outcome": "PENDING",
        "documentation_note": None,
    }
    stamp_new(row)
    db.sideline_evaluations[row["id"]] = row
    return created(S.evaluation_out(row))


@bp.post("/sideline-evaluations/<row_id>/screen")
def screen_evaluation(row_id):
    actor = V.authenticate(["ClubPhysician"])
    b = V.body()
    no_go_signs = V.req_enum_array(b, "no_go_signs", C.NO_GO_SIGNS, allow_empty=True)
    symptom_score = V.req_int(b, "symptom_score", 0, 20)

    evaluation = V.get_evaluation(row_id)
    clinician = V.role_identity(actor)
    player = _player_of(evaluation)
    V.physician_scope(actor, player["club_id"])
    V.not_suspended(clinician)
    if evaluation["status"] != "INITIATED":
        raise ApiError("ERR_EVALUATION_STATE_INVALID",
                       message="Only an INITIATED evaluation may be screened.")
    V.credential_valid(clinician)
    _require_game_in_progress(evaluation)

    evaluation["status"] = "SCREENED"
    evaluation["evaluating_clinician_id"] = clinician["id"]
    evaluation["screened_at"] = db.now
    evaluation["no_go_signs"] = no_go_signs
    evaluation["screen_symptom_score"] = symptom_score
    touch(evaluation)
    return ok(S.evaluation_out(evaluation))


@bp.post("/sideline-evaluations/<row_id>/locker-room-exam")
def locker_room_exam(row_id):
    actor = V.authenticate(["ClubPhysician"])
    b = V.body()
    inc_clinician_id = V.req_id(b, "inc_clinician_id")

    evaluation = V.get_evaluation(row_id)
    nominee = V.get_clinician(inc_clinician_id)
    clinician = V.role_identity(actor)
    player = _player_of(evaluation)
    V.physician_scope(actor, player["club_id"])
    V.not_suspended(clinician)
    V.not_suspended(nominee)
    if evaluation["status"] != "SCREENED":
        raise ApiError("ERR_EVALUATION_STATE_INVALID",
                       message="Only a SCREENED evaluation may begin a locker-room examination.")
    if nominee["affiliation"] not in ("UNAFFILIATED_OBSERVER", "INDEPENDENT_CONSULTANT"):
        raise ApiError("ERR_EXAM_INC_INELIGIBLE")
    if nominee["id"] == evaluation.get("evaluating_clinician_id"):
        raise ApiError("ERR_EXAM_INC_INELIGIBLE")
    V.credential_valid(clinician)
    V.credential_valid(nominee)

    block_end = db.now + timedelta(minutes=C.INC_EXAM_BLOCK_MINUTES)
    if calc.exam_block_conflict(nominee["id"], db.now, block_end,
                                exclude_evaluation_id=evaluation["id"]):
        raise ApiError("ERR_INC_EXAM_WINDOW_CONFLICT")

    evaluation["status"] = "LOCKER_ROOM_EXAM"
    evaluation["inc_clinician_id"] = nominee["id"]
    evaluation["exam_started_at"] = db.now
    evaluation["inc_block_ends_at"] = block_end
    touch(evaluation)
    return ok(S.evaluation_out(evaluation))


@bp.post("/sideline-evaluations/<row_id>/diagnose-concussion")
def diagnose_concussion(row_id):
    actor = V.authenticate(["ClubPhysician"])
    b = V.body()
    symptom_score = V.req_int(b, "symptom_score", 0, 20)
    composite_score = V.req_int(b, "composite_score", 0, 100)
    documentation_note = V.opt_str(b, "documentation_note")

    evaluation = V.get_evaluation(row_id)
    clinician = V.role_identity(actor)
    player = _player_of(evaluation)
    V.physician_scope(actor, player["club_id"])
    V.not_suspended(clinician)
    if evaluation["status"] != "LOCKER_ROOM_EXAM":
        raise ApiError("ERR_EVALUATION_STATE_INVALID",
                       message="A diagnosis may only be documented from LOCKER_ROOM_EXAM.")
    minutes = _require_exam_long_enough(evaluation)
    V.credential_valid(clinician)
    for case in calc.player_cases(player["id"]):
        if case["case_status"] != "CLEARED_FOR_CONTACT":
            raise ApiError("ERR_OPEN_CASE_EXISTS")

    game = _game_of(evaluation)
    club = db.clubs.get(player["club_id"])

    baseline = calc.latest_valid_baseline(player["id"])
    had_baseline = baseline is not None
    deviation = 0
    if had_baseline:
        deviation = max(0, baseline["composite_score"] - composite_score)

    prior = _resolve_prior_case(player["id"], game["season_year"])

    case = {
        "player_id": player["id"],
        "club_id": player["club_id"],
        "sideline_evaluation_id": evaluation["id"],
        "diagnosing_clinician_id": clinician["id"],
        "prior_case_id": prior["id"] if prior else None,
        "season_year": game["season_year"],
        "diagnosis_at": db.now,
        "initial_symptom_score": symptom_score,
        "diagnosis_composite_score": composite_score,
        "baseline_deviation_points": deviation,
        "_had_valid_baseline": had_baseline,
        "severity_index": 0,
        "recurrence_count": 0,
        "rtp_stage": 0,
        "case_status": "MANDATORY_REMOVAL",
        "frozen_from_status": None,
        "monitoring_status": "ACTIVE_SYMPTOM_WATCH",
        "roster_exemption_status": "NONE",
        "heightened_review_required": bool(
            club is not None and club["status"] in ("PROBATION", "SANCTIONED")),
        "projected_return_at": None,
        "earliest_return_at": None,
        "cleared_for_contact_at": None,
        "last_symptom_check_score": None,
        "last_symptomatic_at": (db.now if symptom_score >= C.SYMPTOM_RECURRENCE_THRESHOLD
                                else None),
    }
    case["severity_index"] = calc.compute_severity_index(case)
    case["projected_return_at"] = calc.provisional_projection(
        case["diagnosis_at"], case["severity_index"])
    stamp_new(case)
    db.concussion_cases[case["id"]] = case

    evaluation["status"] = "DIAGNOSED"
    evaluation["diagnosis_outcome"] = "CONCUSSION"
    evaluation["exam_completed_at"] = db.now
    evaluation["exam_duration_minutes"] = minutes
    if documentation_note is not None:
        evaluation["documentation_note"] = documentation_note
    touch(evaluation)

    if baseline is not None:
        baseline["retest_required_reason"] = "NEW_DIAGNOSIS"
        touch(baseline)
    player["availability_status"] = "PROTOCOL_RESTRICTED"
    player["baseline_status"] = calc.resolve_baseline_status(player["id"])
    touch(player)

    return created(S.case_out(case))


def _resolve_prior_case(player_id, season_year):
    candidates = [c for c in calc.player_cases(player_id) if c["season_year"] == season_year]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (-c["diagnosis_at"].timestamp(), c["created_at"], c["_seq"]))
    return candidates[0]


@bp.post("/sideline-evaluations/<row_id>/conclude-no-concussion")
def conclude_no_concussion(row_id):
    actor = V.authenticate(["ClubPhysician"])
    b = V.body()
    outcome = V.req_enum(b, "outcome", ("NO_CONCUSSION", "INCONCLUSIVE"))
    documentation_note = V.opt_str(b, "documentation_note")

    evaluation = V.get_evaluation(row_id)
    clinician = V.role_identity(actor)
    player = _player_of(evaluation)
    V.physician_scope(actor, player["club_id"])
    V.not_suspended(clinician)
    if evaluation["status"] != "LOCKER_ROOM_EXAM":
        raise ApiError("ERR_EVALUATION_STATE_INVALID",
                       message="A conclusion may only be recorded from LOCKER_ROOM_EXAM.")
    if outcome == "NO_CONCUSSION" and (evaluation.get("no_go_signs") or []):
        raise ApiError("ERR_NO_GO_SIGNS_PRESENT")
    minutes = _require_exam_long_enough(evaluation)
    V.credential_valid(clinician)

    evaluation["status"] = ("NO_CONCUSSION_CLEARED" if outcome == "NO_CONCUSSION"
                           else "HELD_OUT_INCONCLUSIVE")
    evaluation["diagnosis_outcome"] = outcome
    evaluation["exam_completed_at"] = db.now
    evaluation["exam_duration_minutes"] = minutes
    if documentation_note is not None:
        evaluation["documentation_note"] = documentation_note
    touch(evaluation)
    return ok(S.evaluation_out(evaluation))


@bp.post("/sideline-evaluations/<row_id>/clear-to-return")
def clear_to_return(row_id):
    actor = V.authenticate(["ClubPhysician"])
    b = V.body()
    documentation_note = V.opt_str(b, "documentation_note")

    evaluation = V.get_evaluation(row_id)
    clinician = V.role_identity(actor)
    player = _player_of(evaluation)
    V.physician_scope(actor, player["club_id"])
    V.not_suspended(clinician)
    if evaluation["status"] != "SCREENED":
        raise ApiError("ERR_EVALUATION_STATE_INVALID",
                       message="Only a SCREENED evaluation may be cleared on field.")
    if (evaluation["mandatory_removal"]
            or (evaluation.get("no_go_signs") or [])
            or (evaluation.get("screen_symptom_score") or 0) > 0):
        raise ApiError("ERR_MANDATORY_REMOVAL_ENFORCED")
    for other in sort_rows(list(db.sideline_evaluations.values())):
        if other["id"] == evaluation["id"]:
            continue
        if other["player_id"] != evaluation["player_id"]:
            continue
        if other["game_id"] != evaluation["game_id"]:
            continue
        if other["status"] in ("DIAGNOSED", "HELD_OUT_INCONCLUSIVE"):
            raise ApiError("ERR_SAME_GAME_RETURN_PROHIBITED")
    V.credential_valid(clinician)
    _require_game_in_progress(evaluation)

    evaluation["status"] = "CLEARED_ON_FIELD"
    evaluation["diagnosis_outcome"] = "NO_CONCUSSION"
    if documentation_note is not None:
        evaluation["documentation_note"] = documentation_note
    touch(evaluation)
    return ok(S.evaluation_out(evaluation))


@bp.get("/sideline-evaluations/<row_id>")
def get_evaluation(row_id):
    actor = V.authenticate(C.ALL_ROLES)
    evaluation = V.get_evaluation(row_id)
    V.role_identity(actor)
    return ok(S.evaluation_out(evaluation))


@bp.get("/sideline-evaluations")
def list_evaluations():
    actor = V.authenticate(C.ALL_ROLES)
    limit, offset = read_pagination()
    player_id = V.filter_str("player_id")
    game_id = V.filter_str("game_id")
    initiating = V.filter_str("initiating_clinician_id")
    evaluating = V.filter_str("evaluating_clinician_id")
    inc = V.filter_str("inc_clinician_id")
    status = V.filter_enum("status", C.EVALUATION_STATUSES)
    trigger_source = V.filter_enum("trigger_source", C.TRIGGER_SOURCES)
    V.role_identity(actor)

    rows = sort_rows(list(db.sideline_evaluations.values()))
    if player_id is not None:
        rows = [r for r in rows if r["player_id"] == player_id]
    if game_id is not None:
        rows = [r for r in rows if r["game_id"] == game_id]
    if initiating is not None:
        rows = [r for r in rows if r["initiating_clinician_id"] == initiating]
    if evaluating is not None:
        rows = [r for r in rows if r.get("evaluating_clinician_id") == evaluating]
    if inc is not None:
        rows = [r for r in rows if r.get("inc_clinician_id") == inc]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if trigger_source is not None:
        rows = [r for r in rows if r["trigger_source"] == trigger_source]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.evaluation_out(r) for r in page], limit, offset, total)
