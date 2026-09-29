"""Fair-play cases: the conduct docket, its sanction cascade and its inverse."""

from decimal import Decimal

from flask import Blueprint

import domain
from errors import fail
from guards import not_owner
from http_util import (
    created,
    endpoint,
    listing,
    ok,
    opt_enum,
    opt_str,
    present,
    req_enum,
    req_str,
)
from serialize import dump
from store import db, find, must_find, new_record, touch

bp = Blueprint("routes_e", __name__)

CASE_READ_ROLES = (
    "LeagueAdmin",
    "DistrictAdmin",
    "AthleticDirector",
    "Coach",
    "IntegrityOfficer",
)
SUBJECT_TYPES = ("STUDENT", "MATCH_BROADCAST")
CASE_TYPES = ("ACCOUNT_SHARING", "SMURFING", "CHEAT_DETECTION", "SPECTATOR_CONDUCT")
SEVERITIES = ("MINOR", "MAJOR", "SEVERE")


@bp.post("/fair-play-cases")
@endpoint("IntegrityOfficer", "LeagueAdmin", "Coach")
def open_case(ctx):
    body = ctx.body
    team_id = req_str(body, "team_id")
    subject_type = req_enum(body, "subject_type", SUBJECT_TYPES)
    case_type = req_enum(body, "case_type", CASE_TYPES)
    evidence_ref = req_str(body, "evidence_ref", 1, 200)
    student_id = opt_str(body, "subject_student_id")
    match_id = opt_str(body, "subject_match_id")
    team = find("team", team_id)
    if team is None:
        fail("ERR_TEAM_NOT_FOUND", "No team with that identifier exists.")
    student = None
    if student_id is not None:
        student = find("student", student_id)
        if student is None:
            fail("ERR_STUDENT_NOT_FOUND", "No student with that identifier exists.")
    match = None
    if match_id is not None:
        match = find("match", match_id)
        if match is None:
            fail("ERR_MATCH_NOT_FOUND", "No match with that identifier exists.")
    if subject_type == "STUDENT" and (student_id is None or match_id is not None):
        fail(
            "ERR_SUBJECT_REFERENCE_MISMATCH",
            "A STUDENT case names subject_student_id and no match.",
        )
    if subject_type == "MATCH_BROADCAST" and (match_id is None or student_id is not None):
        fail(
            "ERR_SUBJECT_REFERENCE_MISMATCH",
            "A MATCH_BROADCAST case names subject_match_id and no student.",
        )
    if subject_type == "STUDENT":
        live = [
            s
            for s in domain.slots_of_student(student_id)
            if s["team_id"] == team_id and s["participation_status"] != "RELEASED"
        ]
        if not live:
            fail(
                "ERR_SUBJECT_TEAM_MISMATCH",
                "The named student holds no live slot on the charged team.",
            )
    else:
        if team_id not in (match["home_team_id"], match["away_team_id"]):
            fail(
                "ERR_SUBJECT_TEAM_MISMATCH",
                "The charged team does not play in the named match.",
            )
    case = new_record(
        "fair_play_case",
        team_id=team_id,
        subject_type=subject_type,
        subject_student_id=student_id,
        subject_match_id=match_id,
        case_type=case_type,
        evidence_ref=evidence_ref,
        severity=None,
        status="REPORTED",
        reported_by_user_id=ctx.user_id,
        investigator_user_id=None,
        decider_user_id=None,
        appeal_decider_user_id=None,
        severity_weight=Decimal("0.00"),
        repeat_index=None,
        applied_penalty=Decimal("0.00"),
        sanction_type="NONE",
        appeal_grounds=None,
        decided_at=None,
    )
    return created(dump(case))


@bp.get("/fair-play-cases/<case_id>")
@endpoint(*CASE_READ_ROLES)
def read_case(ctx, case_id):
    return ok(dump(must_find("fair_play_case", case_id)))


@bp.get("/fair-play-cases")
@endpoint(*CASE_READ_ROLES)
def list_cases(ctx):
    return listing(
        "fair_play_case",
        ("team_id", "subject_student_id", "subject_match_id", "status", "case_type"),
        dump,
    )


@bp.post("/fair-play-cases/<case_id>/investigate")
@endpoint("IntegrityOfficer")
def investigate_case(ctx, case_id):
    case = must_find("fair_play_case", case_id)
    opt_str(ctx.body, "investigation_note", None, 1, 500)
    if case["status"] != "REPORTED":
        fail("ERR_INVALID_CASE_STATE", "Only a reported case may be taken up.")
    domain.update(case, status="INVESTIGATING", investigator_user_id=ctx.user_id)
    touch(case)
    return ok(dump(case))


@bp.post("/fair-play-cases/<case_id>/decision")
@endpoint("IntegrityOfficer")
def decide_case(ctx, case_id):
    case = must_find("fair_play_case", case_id)
    body = ctx.body
    decision = req_enum(body, "decision", ("SUSTAIN", "DISMISS"))
    severity = opt_enum(body, "severity", SEVERITIES)
    opt_str(body, "decision_note", None, 1, 500)
    if decision == "SUSTAIN" and severity is None:
        fail("ERR_INVALID_REQUEST", "A SUSTAIN decision requires a severity.")
    if decision == "DISMISS" and present(body, "severity"):
        fail("ERR_INVALID_REQUEST", "A DISMISS decision forbids a severity.")
    if case["status"] != "INVESTIGATING":
        fail("ERR_INVALID_CASE_STATE", "Only a case under investigation may be decided.")
    case["decider_user_id"] = ctx.user_id
    case["decided_at"] = db.now
    if decision == "DISMISS":
        case["status"] = "DISMISSED"
        touch(case)
        return ok(dump(case))
    case["severity"] = severity
    case["status"] = "SUSTAINED"
    touch(case)
    team = find("team", case["team_id"])
    score = domain.recompute_integrity(team) if team is not None else Decimal("100.00")
    domain.update(case, sanction_type=domain.select_sanction(case, score))
    if case["subject_type"] == "STUDENT":
        student = find("student", case["subject_student_id"])
        if student is not None:
            domain.sanction_student(student, case)
    else:
        match = find("match", case["subject_match_id"])
        if match is not None and match["broadcast_status"] == "LIVE":
            domain.update(
                match,
                broadcast_status="SUSPENDED",
                spectator_strikes=match["spectator_strikes"] + 1,
            )
    return ok(dump(case))


@bp.post("/fair-play-cases/<case_id>/appeal")
@endpoint("Coach")
def appeal_case(ctx, case_id):
    existing = find("fair_play_case", case_id)
    if existing is not None:
        team = find("team", existing.get("team_id"))
        if team is not None and team.get("coach_id") != ctx.user_id:
            not_owner("Only the charged team's own coach may appeal.")
    case = must_find("fair_play_case", case_id)
    grounds = req_str(ctx.body, "appeal_grounds", 1, 1000)
    if case["status"] != "SUSTAINED":
        fail("ERR_INVALID_CASE_STATE", "Only a sustained case may be appealed.")
    domain.update(case, status="APPEALED", appeal_grounds=grounds)
    touch(case)
    return ok(dump(case))


@bp.post("/fair-play-cases/<case_id>/appeal-decision")
@endpoint("IntegrityOfficer")
def decide_appeal(ctx, case_id):
    case = must_find("fair_play_case", case_id)
    decision = req_enum(ctx.body, "decision", ("AFFIRM", "OVERTURN"))
    opt_str(ctx.body, "appeal_note", None, 1, 500)
    if case["status"] != "APPEALED":
        fail("ERR_INVALID_CASE_STATE", "Only an appealed case may receive an appeal decision.")
    if ctx.user_id in (case.get("investigator_user_id"), case.get("decider_user_id")):
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The appeal must be decided by an officer who did not handle the case.",
        )
    case["appeal_decider_user_id"] = ctx.user_id
    team = find("team", case["team_id"])
    if decision == "AFFIRM":
        case["status"] = "SUSTAINED_FINAL"
        touch(case)
        if case["sanction_type"] == "DISQUALIFICATION":
            domain.disqualify_team(team)
        return ok(dump(case))
    case["status"] = "OVERTURNED"
    case["sanction_type"] = "NONE"
    touch(case)
    if team is not None:
        domain.recompute_integrity(team)
    if case["subject_type"] == "STUDENT":
        student = find("student", case["subject_student_id"])
        if student is not None:
            domain.clear_student(student, case)
        domain.maybe_restore_team(team, case)
    else:
        match = find("match", case["subject_match_id"])
        if match is not None and match["broadcast_status"] == "SUSPENDED":
            domain.update(
                match,
                broadcast_status="LIVE",
                spectator_strikes=max(0, match["spectator_strikes"] - 1),
            )
    return ok(dump(case))
