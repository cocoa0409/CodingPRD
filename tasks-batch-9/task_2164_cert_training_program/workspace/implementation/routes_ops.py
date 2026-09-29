"""Exercises, activations, roster assignments and the two test-driving hooks."""
from __future__ import annotations

from flask import Blueprint

from calc import (AAR_MIN_SUMMARY_CHARS, EXERCISE_TYPES, ROLE_MULTIPLIERS,
                  ROLE_PLAYED, RESPONSE_WINDOW_MINUTES, SEVERITIES,
                  add_refresher_hours, credential_of, exercise_hours,
                  rank_candidates, recompute_readiness,
                  recompute_trainee_tallies, trainee_is_eligible)
from cascade import (refresh_activation, refresh_exercise, refresh_program,
                     withdraw_roster_commitments)
from errors import ApiError, bad_request
from store import new_row, sorted_rows, store, touch
from util import D, add_minutes, fmt_iso, parse_iso
from web import (body, f_dt, f_enum, f_id, f_int, f_str, ok, ok_row, paginate,
                 q_enum, q_str, require, require_any, resolve)

bp = Blueprint("ops", __name__)

EXERCISE_STATUS = ("PLANNED", "RUNNING", "COMPLETED", "AAR_SUBMITTED",
                   "AAR_ACCEPTED", "CANCELLED")
PARTICIPATION_STATUS = ("REGISTERED", "CREDITED", "VOIDED")
ACTIVATION_STATUS = ("REQUESTED", "ROSTERED", "ACTIVATED", "DEMOBILIZED", "CANCELLED")
FILL_STATUS = ("UNFILLED", "PARTIAL", "FILLED")
ASSIGNMENT_STATUS = ("NOTIFIED", "ACCEPTED", "DECLINED", "NO_RESPONSE",
                     "DEPLOYED", "RELEASED", "WITHDRAWN")


# ==========================================================================
# Exercise
# ==========================================================================
@bp.post("/exercises")
def create_exercise():
    require("EmergencyManager")
    data = body()
    program_id = f_id(data, "program_id")
    title = f_str(data, "title")
    ex_type = f_enum(data, "exercise_type", EXERCISE_TYPES)
    starts_raw, starts_at = f_dt(data, "starts_at")
    ends_raw, ends_at = f_dt(data, "ends_at")
    base_hours = f_num_positive(data)
    if not ends_at > starts_at:
        raise bad_request("ends_at must fall strictly after starts_at.")
    program = resolve(store.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    row = new_row(
        "Exercise",
        program_id=program_id,
        title=title,
        exercise_type=ex_type,
        starts_at=starts_raw,
        ends_at=ends_raw,
        base_credit_hours=float(base_hours),
        aar_summary=None,
        accepted_participant_count=0,
        status="PLANNED",
    )
    store.exercises[row["id"]] = row
    return ok_row(row, 201)


def f_num_positive(data):
    from web import f_num
    return f_num(data, "base_credit_hours", gt=0, max_decimals=1)


@bp.get("/exercises")
def list_exercises():
    require_any()
    program_id = q_str("program_id")
    status = q_enum("status", EXERCISE_STATUS)
    rows = []
    for e in store.exercises.values():
        if program_id is not None and e["program_id"] != program_id:
            continue
        if status is not None and e["status"] != status:
            continue
        rows.append(e)
    return paginate(rows)


@bp.get("/exercises/<exercise_id>")
def read_exercise(exercise_id):
    require_any()
    ex = resolve(store.exercises, exercise_id, "ERR_EXERCISE_NOT_FOUND")
    return ok_row(ex)


@bp.post("/exercises/<exercise_id>/advance")
def advance_exercise(exercise_id):
    user_id, role = require("EmergencyManager", "ProgramCoordinator")
    ex = resolve(store.exercises, exercise_id, "ERR_EXERCISE_NOT_FOUND")
    data = body()
    to_status = f_enum(data, "to_status",
                       ("RUNNING", "COMPLETED", "AAR_SUBMITTED", "AAR_ACCEPTED", "CANCELLED"))
    # Accepting the after-action report is reserved to a ProgramCoordinator;
    # every other advance is the emergency manager's act.
    if to_status == "AAR_ACCEPTED":
        if role != "ProgramCoordinator":
            raise ApiError("ERR_UNAUTHORIZED",
                           "Only a ProgramCoordinator may accept the after-action report.")
    elif role != "EmergencyManager":
        raise ApiError("ERR_UNAUTHORIZED",
                       "Only an EmergencyManager may drive this advance.")

    allowed = {
        "PLANNED": ("RUNNING", "CANCELLED"),
        "RUNNING": ("COMPLETED", "CANCELLED"),
        "COMPLETED": ("AAR_SUBMITTED",),
        "AAR_SUBMITTED": ("AAR_ACCEPTED",),
        "AAR_ACCEPTED": (),
        "CANCELLED": (),
    }
    current = ex["status"]
    if to_status not in allowed.get(current, ()):
        raise ApiError("ERR_INVALID_STATE",
                       "Exercise cannot move from %s to %s." % (current, to_status))

    participations = [p for p in sorted_rows(list(store.exercise_participations.values()))
                      if p["exercise_id"] == ex["id"]]

    if to_status == "RUNNING":
        if store.now() < parse_iso(ex["starts_at"]):
            raise ApiError("ERR_INVALID_STATE",
                           "The logical clock has not reached the exercise start.")
        if not any(p["status"] == "REGISTERED" for p in participations):
            raise ApiError("ERR_INVALID_STATE",
                           "At least one REGISTERED participation is required.")
        ex["status"] = "RUNNING"
    elif to_status == "COMPLETED":
        if store.now() < parse_iso(ex["ends_at"]):
            raise ApiError("ERR_INVALID_STATE",
                           "The logical clock has not reached the exercise end.")
        ex["status"] = "COMPLETED"
    elif to_status == "AAR_SUBMITTED":
        summary = f_str(data, "aar_summary", required=True,
                        min_len=AAR_MIN_SUMMARY_CHARS)
        ex["aar_summary"] = summary
        ex["status"] = "AAR_SUBMITTED"
    elif to_status == "AAR_ACCEPTED":
        ex["status"] = "AAR_ACCEPTED"
        for p in participations:
            if p["status"] != "REGISTERED":
                continue
            p["status"] = "CREDITED"
            p["hours_credited"] = exercise_hours(ex, p)
            touch(p)
            trainee = store.trainees.get(p["trainee_id"])
            if trainee is None:
                continue
            cred = credential_of(trainee["id"])
            if cred is not None and store.now() >= parse_iso(cred["term_start_on"]):
                add_refresher_hours(cred, D(p["hours_credited"]))
                touch(cred)
            recompute_trainee_tallies(trainee)
            recompute_readiness(trainee)
            touch(trainee)
    else:  # CANCELLED
        for p in participations:
            if p["status"] == "REGISTERED":
                p["status"] = "VOIDED"
                touch(p)
        ex["status"] = "CANCELLED"

    touch(ex)
    refresh_exercise(ex)
    return ok_row(ex)


# ==========================================================================
# ExerciseParticipation
# ==========================================================================
@bp.post("/exercise-participations")
def create_participation():
    require("EmergencyManager")
    data = body()
    exercise_id = f_id(data, "exercise_id")
    trainee_id = f_id(data, "trainee_id")
    role_played = f_enum(data, "role_played", ROLE_PLAYED)
    exercise = resolve(store.exercises, exercise_id, "ERR_EXERCISE_NOT_FOUND")
    trainee = resolve(store.trainees, trainee_id, "ERR_TRAINEE_NOT_FOUND")
    row = new_row(
        "ExerciseParticipation",
        exercise_id=exercise_id,
        trainee_id=trainee_id,
        role_played=role_played,
        role_multiplier=float(ROLE_MULTIPLIERS[role_played]),
        hours_credited=0.0,
        status="REGISTERED",
    )
    store.exercise_participations[row["id"]] = row
    return ok_row(row, 201)


@bp.get("/exercise-participations")
def list_participations():
    require_any()
    exercise_id = q_str("exercise_id")
    trainee_id = q_str("trainee_id")
    status = q_enum("status", PARTICIPATION_STATUS)
    rows = []
    for p in store.exercise_participations.values():
        if exercise_id is not None and p["exercise_id"] != exercise_id:
            continue
        if trainee_id is not None and p["trainee_id"] != trainee_id:
            continue
        if status is not None and p["status"] != status:
            continue
        rows.append(p)
    return paginate(rows)


@bp.get("/exercise-participations/<participation_id>")
def read_participation(participation_id):
    require_any()
    row = resolve(store.exercise_participations, participation_id, "ERR_PARTICIPATION_NOT_FOUND")
    return ok_row(row)


# ==========================================================================
# Activation
# ==========================================================================
@bp.post("/activations")
def create_activation():
    require("EmergencyManager")
    data = body()
    program_id = f_id(data, "program_id")
    incident_number = f_str(data, "incident_number")
    agency = f_str(data, "requesting_agency")
    severity = f_enum(data, "severity", SEVERITIES)
    requested = f_int(data, "requested_responders", min_val=1)
    program = resolve(store.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    for a in store.activations.values():
        if a["program_id"] == program_id and a["incident_number"] == incident_number:
            raise ApiError("ERR_DUPLICATE_SCOPED_KEY",
                           "incident_number is already used inside this program.")
    row = new_row(
        "Activation",
        program_id=program_id,
        incident_number=incident_number,
        requesting_agency=agency,
        severity=severity,
        requested_responders=requested,
        rostered_count=0,
        accepted_count=0,
        deployed_count=0,
        response_deadline_at=None,
        fill_status="UNFILLED",
        status="REQUESTED",
    )
    store.activations[row["id"]] = row
    return ok_row(row, 201)


@bp.get("/activations")
def list_activations():
    require_any()
    program_id = q_str("program_id")
    status = q_enum("status", ACTIVATION_STATUS)
    fill_status = q_enum("fill_status", FILL_STATUS)
    rows = []
    for a in store.activations.values():
        if program_id is not None and a["program_id"] != program_id:
            continue
        if status is not None and a["status"] != status:
            continue
        if fill_status is not None and a["fill_status"] != fill_status:
            continue
        rows.append(a)
    return paginate(rows)


@bp.get("/activations/<activation_id>")
def read_activation(activation_id):
    require_any()
    act = resolve(store.activations, activation_id, "ERR_ACTIVATION_NOT_FOUND")
    return ok_row(act)


@bp.post("/activations/<activation_id>/roster")
def build_roster(activation_id):
    require("EmergencyManager")
    act = resolve(store.activations, activation_id, "ERR_ACTIVATION_NOT_FOUND")
    if act["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a REQUESTED activation can be rostered.")
    candidates = rank_candidates(act)
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_RESPONDERS",
                       "No trainee satisfies the eligibility filter.")
    take = min(int(act["requested_responders"]), len(candidates))
    stamp = store.now_iso()
    for index in range(take):
        trainee = candidates[index]
        row = new_row(
            "RosterAssignment",
            activation_id=act["id"],
            trainee_id=trainee["id"],
            selection_rank=index + 1,
            notified_at=stamp,
            responded_at=None,
            source="AUTO_ROSTER",
            status="NOTIFIED",
        )
        store.roster_assignments[row["id"]] = row
    window = RESPONSE_WINDOW_MINUTES[act["severity"]]
    act["response_deadline_at"] = fmt_iso(add_minutes(store.now(), window))
    act["status"] = "ROSTERED"
    from calc import recompute_activation_counts
    recompute_activation_counts(act)
    touch(act)
    return ok_row(act)


@bp.post("/activations/<activation_id>/roster-assignments")
def manual_roster_add(activation_id):
    require("EmergencyManager")
    act = resolve(store.activations, activation_id, "ERR_ACTIVATION_NOT_FOUND")
    data = body()
    trainee_id = f_id(data, "trainee_id")
    expected = f_int(data, "expected_activation_version")
    trainee = resolve(store.trainees, trainee_id, "ERR_TRAINEE_NOT_FOUND")
    if expected != int(act["version"]):
        raise ApiError("ERR_STALE_ACTIVATION_VERSION",
                       "expected_activation_version does not match the activation's version.")
    eligible, _cred = trainee_is_eligible(trainee, act)
    if not eligible:
        raise ApiError("ERR_TRAINEE_NOT_ELIGIBLE",
                       "The trainee fails the roster eligibility filter.")
    ranks = [int(r["selection_rank"]) for r in store.roster_assignments.values()
             if r["activation_id"] == act["id"] and r.get("selection_rank") is not None]
    next_rank = (max(ranks) + 1) if ranks else 1
    row = new_row(
        "RosterAssignment",
        activation_id=act["id"],
        trainee_id=trainee_id,
        selection_rank=next_rank,
        notified_at=store.now_iso(),
        responded_at=None,
        source="MANUAL_ADD",
        status="NOTIFIED",
    )
    store.roster_assignments[row["id"]] = row
    from calc import recompute_activation_counts
    recompute_activation_counts(act)
    touch(act)
    return ok_row(row, 201)


@bp.post("/activations/<activation_id>/advance")
def advance_activation(activation_id):
    require("EmergencyManager")
    act = resolve(store.activations, activation_id, "ERR_ACTIVATION_NOT_FOUND")
    data = body()
    to_status = f_enum(data, "to_status", ("ACTIVATED", "DEMOBILIZED", "CANCELLED"))
    allowed = {
        "REQUESTED": ("CANCELLED",),
        "ROSTERED": ("ACTIVATED", "CANCELLED"),
        "ACTIVATED": ("DEMOBILIZED",),
        "DEMOBILIZED": (),
        "CANCELLED": (),
    }
    current = act["status"]
    if to_status not in allowed.get(current, ()):
        raise ApiError("ERR_INVALID_STATE",
                       "Activation cannot move from %s to %s." % (current, to_status))
    rows = [r for r in sorted_rows(list(store.roster_assignments.values()))
            if r["activation_id"] == act["id"]]
    if to_status == "ACTIVATED":
        if int(act["accepted_count"]) < 1:
            raise ApiError("ERR_INVALID_STATE",
                           "At least one responder must have accepted.")
        act["status"] = "ACTIVATED"
    elif to_status == "DEMOBILIZED":
        if any(r["status"] == "DEPLOYED" for r in rows):
            raise ApiError("ERR_INVALID_STATE",
                           "A responder is still DEPLOYED.")
        for r in rows:
            if r["status"] == "NOTIFIED":
                r["status"] = "NO_RESPONSE"
                touch(r)
            elif r["status"] == "ACCEPTED":
                r["status"] = "WITHDRAWN"
                touch(r)
        act["status"] = "DEMOBILIZED"
    else:  # CANCELLED
        if current == "ROSTERED":
            for r in rows:
                if r["status"] in ("NOTIFIED", "ACCEPTED"):
                    r["status"] = "WITHDRAWN"
                    touch(r)
        act["status"] = "CANCELLED"
    from calc import recompute_activation_counts
    recompute_activation_counts(act)
    touch(act)
    return ok_row(act)


# ==========================================================================
# RosterAssignment
# ==========================================================================
@bp.get("/roster-assignments")
def list_assignments():
    require_any()
    activation_id = q_str("activation_id")
    trainee_id = q_str("trainee_id")
    status = q_enum("status", ASSIGNMENT_STATUS)
    rows = []
    for r in store.roster_assignments.values():
        if activation_id is not None and r["activation_id"] != activation_id:
            continue
        if trainee_id is not None and r["trainee_id"] != trainee_id:
            continue
        if status is not None and r["status"] != status:
            continue
        rows.append(r)
    return paginate(rows)


@bp.get("/roster-assignments/<assignment_id>")
def read_assignment(assignment_id):
    require_any()
    row = resolve(store.roster_assignments, assignment_id, "ERR_ROSTER_ASSIGNMENT_NOT_FOUND")
    return ok_row(row)


@bp.post("/roster-assignments/<assignment_id>/respond")
def respond_assignment(assignment_id):
    user_id, role = require("Trainee")
    assignment = resolve(store.roster_assignments, assignment_id,
                         "ERR_ROSTER_ASSIGNMENT_NOT_FOUND")
    data = body()
    response = f_enum(data, "response", ("ACCEPT", "DECLINE"))
    if user_id != assignment["trainee_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "A trainee may answer only their own assignment.")
    if assignment["status"] != "NOTIFIED":
        raise ApiError("ERR_INVALID_STATE", "The assignment is no longer NOTIFIED.")
    act = store.activations.get(assignment["activation_id"])
    if response == "ACCEPT":
        cred = credential_of(assignment["trainee_id"])
        if cred is None or cred["status"] not in ("ACTIVE", "GRACE"):
            raise ApiError("ERR_CREDENTIAL_NOT_ACTIVE",
                           "Accepting requires a live credential.")
    if act is None or act["status"] != "ROSTERED":
        raise ApiError("ERR_ACTIVATION_NOT_ROSTERED",
                       "The activation is not ROSTERED.")
    deadline = act.get("response_deadline_at")
    if deadline is None or store.now() >= parse_iso(deadline):
        raise ApiError("ERR_RESPONSE_WINDOW_CLOSED",
                       "The call-out response window has closed.")
    assignment["status"] = "ACCEPTED" if response == "ACCEPT" else "DECLINED"
    assignment["responded_at"] = store.now_iso()
    touch(assignment)
    refresh_activation(act)
    return ok_row(assignment)


@bp.post("/roster-assignments/<assignment_id>/advance")
def advance_assignment(assignment_id):
    require("EmergencyManager")
    assignment = resolve(store.roster_assignments, assignment_id,
                         "ERR_ROSTER_ASSIGNMENT_NOT_FOUND")
    data = body()
    to_status = f_enum(data, "to_status", ("DEPLOYED", "RELEASED"))
    current = assignment["status"]
    allowed = {"ACCEPTED": ("DEPLOYED",), "DEPLOYED": ("RELEASED",)}
    if to_status not in allowed.get(current, ()):
        raise ApiError("ERR_INVALID_STATE",
                       "Assignment cannot move from %s to %s." % (current, to_status))
    act = store.activations.get(assignment["activation_id"])
    trainee = store.trainees.get(assignment["trainee_id"])
    if to_status == "DEPLOYED":
        if act is None or act["status"] != "ACTIVATED":
            raise ApiError("ERR_INVALID_STATE", "The activation is not ACTIVATED.")
        assignment["status"] = "DEPLOYED"
        touch(assignment)
        if trainee is not None:
            trainee["last_deployed_at"] = store.now_iso()
            touch(trainee)
    else:
        assignment["status"] = "RELEASED"
        touch(assignment)
        if trainee is not None:
            recompute_trainee_tallies(trainee)
            recompute_readiness(trainee)
            touch(trainee)
    refresh_activation(act)
    return ok_row(assignment)


# ==========================================================================
# Test-driving hooks
# ==========================================================================
@bp.post("/_clock/set_current_utc")
def set_clock():
    require("ProgramCoordinator")
    data = body()
    raw, parsed = f_dt(data, "to_iso8601")
    store.clock = parsed
    return ok({"current_utc": fmt_iso(parsed)})


@bp.post("/_ops/run-currency-sweep")
def run_sweep():
    require("ProgramCoordinator")
    data = body()
    program_id = f_id(data, "program_id")
    program = resolve(store.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    now = store.now()

    trainee_ids = set(t["id"] for t in store.trainees.values()
                      if t["program_id"] == program_id)
    swept = 0
    graced = 0
    expired = 0
    for cred in sorted_rows(list(store.credentials.values())):
        if cred["trainee_id"] not in trainee_ids:
            continue
        swept += 1
        trainee = store.trainees.get(cred["trainee_id"])
        if cred["status"] == "ACTIVE" and cred.get("expires_on") and \
                now >= parse_iso(cred["expires_on"]) and \
                cred.get("grace_ends_on") and now < parse_iso(cred["grace_ends_on"]):
            cred["status"] = "GRACE"
            touch(cred)
            if trainee is not None and trainee["currency_status"] == "CURRENT":
                trainee["currency_status"] = "LAPSING"
                touch(trainee)
            graced += 1
        elif cred["status"] == "GRACE" and cred.get("grace_ends_on") and \
                now >= parse_iso(cred["grace_ends_on"]):
            cred["status"] = "EXPIRED"
            touch(cred)
            if trainee is not None:
                if trainee["currency_status"] == "LAPSING":
                    trainee["currency_status"] = "LAPSED"
                touch(trainee)
                withdraw_roster_commitments(trainee, restrict_activation=True)
            expired += 1

    no_response = 0
    affected = {}
    for r in sorted_rows(list(store.roster_assignments.values())):
        if r["status"] != "NOTIFIED":
            continue
        act = store.activations.get(r["activation_id"])
        if act is None or act["program_id"] != program_id:
            continue
        deadline = act.get("response_deadline_at")
        if deadline is None or now < parse_iso(deadline):
            continue
        r["status"] = "NO_RESPONSE"
        touch(r)
        affected[act["id"]] = act
        no_response += 1
    for act in affected.values():
        refresh_activation(act)

    return ok({
        "swept_credential_count": swept,
        "graced_count": graced,
        "expired_count": expired,
        "no_response_count": no_response,
    })
