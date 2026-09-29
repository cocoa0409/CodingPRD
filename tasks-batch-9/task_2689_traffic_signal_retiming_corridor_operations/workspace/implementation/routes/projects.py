"""Retiming projects: the before study, coordination, implementation and
disposition (PRD sections 3.4, 3.6, 3.8, 3.10)."""

from datetime import timedelta

from flask import Blueprint

import auth
import calc
import cascades
import clock
import derive
import lookups
import response
import serializers
import validators
from auth import CERTIFYING_ENGINEER, FIELD_TECHNICIAN, SIGNAL_OPS_ADMIN, STAFF, TIMING_ENGINEER
from db import base_row, db, touch
from errors import fail

bp = Blueprint("projects", __name__)

STUDY_ROLES = ("BEFORE", "AFTER")
DIRECTIONS = ("NB", "SB", "EB", "WB")
ACTIONS = ("START", "COMPLETE")
DISPOSITIONS = ("CLOSED", "ABANDONED")
RUN_SPACING_SEC = 120


@bp.route("/signal-ops/retiming-projects", methods=["POST"])
@auth.roles(TIMING_ENGINEER)
def create_project():
    data = validators.body()
    corridor = lookups.corridor(validators.req_id(data, "corridor_id"))
    study_window_start_at = validators.req_ts(data, "study_window_start_at")
    study_window_days = validators.opt_int(data, "study_window_days", 30, 730, 180)
    lead_engineer_user_id = validators.req_str(data, "lead_engineer_user_id", 1, 64)

    if derive.has_live_project(corridor["id"]):
        fail("ERR_CORRIDOR_PROJECT_ACTIVE")
    if corridor["selection_status"] != "SELECTED":
        fail("ERR_CORRIDOR_NOT_SELECTED")

    row = {
        "corridor_id": corridor["id"],
        "status": "DATA_COLLECTION",
        "study_window_start_at": study_window_start_at,
        "study_window_days": study_window_days,
        "tuning_round": 0,
        "last_tuning_completed_at": None,
        "lead_engineer_user_id": lead_engineer_user_id,
        "eligible_member_count": derive.eligible_member_count(corridor["id"]),
        "_field_tuning_started_at": None,
    }
    row.update(base_row())
    db.projects[row["id"]] = row
    return response.created(serializers.project(row))


@bp.route("/signal-ops/retiming-projects/<project_id>", methods=["GET"])
@auth.roles(*STAFF)
def read_project(project_id):
    row = lookups.project(project_id)
    return response.ok(serializers.project(row))


@bp.route("/signal-ops/retiming-projects/<project_id>/turning-movement-counts", methods=["GET"])
@auth.roles(*STAFF)
def list_project_counts(project_id):
    lookups.project(project_id)
    rows = derive.counts_of_project(project_id)
    rows = lookups.apply_filter(rows, "study_role")
    return lookups.listing(rows, serializers.turning_movement_count)


@bp.route("/signal-ops/retiming-projects/<project_id>/travel-time-runs", methods=["GET"])
@auth.roles(*STAFF)
def list_project_runs(project_id):
    lookups.project(project_id)
    rows = derive.runs_of_project(project_id)
    rows = lookups.apply_filter(rows, "study_role")
    rows = lookups.apply_filter(rows, "direction")
    return lookups.listing(rows, serializers.travel_time_run)


@bp.route("/signal-ops/retiming-projects/<project_id>/timing-plans", methods=["GET"])
@auth.roles(*STAFF)
def list_project_plans(project_id):
    lookups.project(project_id)
    rows = derive.plans_of_project(project_id)
    rows = lookups.apply_filter(rows, "status")
    return lookups.listing(rows, serializers.timing_plan)


@bp.route("/signal-ops/retiming-projects/<project_id>/field-observations", methods=["GET"])
@auth.roles(*STAFF)
def list_project_observations(project_id):
    lookups.project(project_id)
    rows = derive.observations_of_project(project_id)
    rows = lookups.apply_filter(rows, "resolution_status")
    return lookups.listing(rows, serializers.field_observation)


@bp.route("/signal-ops/retiming-projects/<project_id>/complaints", methods=["GET"])
@auth.roles(*STAFF)
def list_project_complaints(project_id):
    lookups.project(project_id)
    rows = [c for c in db.complaints.values() if c.get("linked_project_id") == project_id]
    rows.sort(key=lambda c: c["_seq"])
    rows = lookups.apply_filter(rows, "status")
    return lookups.listing(rows, serializers.complaint)


@bp.route(
    "/signal-ops/retiming-projects/<project_id>/performance-evaluations", methods=["GET"]
)
@auth.roles(*STAFF)
def list_project_evaluations(project_id):
    lookups.project(project_id)
    rows = derive.evaluations_of_project(project_id)
    rows = lookups.apply_filter(rows, "status")
    return lookups.listing(rows, serializers.performance_evaluation)


@bp.route("/signal-ops/retiming-projects/<project_id>/travel-time-runs", methods=["POST"])
@auth.roles(FIELD_TECHNICIAN)
def create_run(project_id):
    project = lookups.project(project_id)
    data = validators.body()
    study_role = validators.req_enum(data, "study_role", STUDY_ROLES)
    direction = validators.req_enum(data, "direction", DIRECTIONS)
    started_at = validators.req_ts(data, "started_at")
    duration_sec = validators.req_num(data, "duration_sec", None, 3600)
    if duration_sec <= 0:
        fail("ERR_INVALID_REQUEST", "duration_sec must be greater than 0.")
    stops_count = validators.req_int(data, "stops_count", 0, None)
    arrivals_on_green_count = validators.req_int(data, "arrivals_on_green_count", 0, None)
    total_arrivals = validators.req_int(data, "total_arrivals", 1, None)
    if arrivals_on_green_count > total_arrivals:
        fail("ERR_INVALID_REQUEST", "arrivals_on_green_count may not exceed total_arrivals.")
    lookups.not_terminal(project)

    new_start = started_at
    new_end = started_at + timedelta(seconds=float(duration_sec))
    for existing in derive.runs_of_project(project["id"]):
        if existing["direction"] != direction or existing["study_role"] != study_role:
            continue
        old_start = existing["started_at"]
        old_end = old_start + timedelta(seconds=float(existing["duration_sec"]))
        if new_end < old_start:
            gap = (old_start - new_end).total_seconds()
        elif old_end < new_start:
            gap = (new_start - old_end).total_seconds()
        else:
            gap = 0
        if gap < RUN_SPACING_SEC:
            fail("ERR_RUN_SPACING_VIOLATION")

    row = {
        "project_id": project["id"],
        "study_role": study_role,
        "direction": direction,
        "started_at": started_at,
        "duration_sec": duration_sec,
        "stops_count": stops_count,
        "arrivals_on_green_count": arrivals_on_green_count,
        "total_arrivals": total_arrivals,
        "recorded_at": clock.now(),
    }
    row.update(base_row(common=False))
    db.runs[row["id"]] = row
    return response.created(serializers.travel_time_run(row))


@bp.route("/signal-ops/retiming-projects/<project_id>/advance", methods=["POST"])
@auth.roles(TIMING_ENGINEER)
def advance_project(project_id):
    project = lookups.project(project_id)
    validators.body()
    lookups.not_terminal(project)
    if project["status"] != "DATA_COLLECTION":
        fail("ERR_PROJECT_NOT_IN_DATA_COLLECTION")

    counts = derive.counts_of_project(project["id"])
    for member in derive.eligible_members(project["corridor_id"]):
        served = [
            c
            for c in counts
            if c["intersection_id"] == member["intersection_id"] and c["study_role"] == "BEFORE"
        ]
        if not served:
            fail("ERR_BEFORE_STUDY_INCOMPLETE")
    before_runs = [r for r in derive.runs_of_project(project["id"]) if r["study_role"] == "BEFORE"]
    if not before_runs:
        fail("ERR_BEFORE_STUDY_INCOMPLETE")

    deadline = clock.plus_days(project["study_window_start_at"], project["study_window_days"])
    if clock.now() >= deadline:
        fail("ERR_STUDY_WINDOW_EXPIRED")

    project["eligible_member_count"] = derive.eligible_member_count(project["corridor_id"])
    project["status"] = "PLAN_DEVELOPMENT"
    touch(project)
    return response.ok(serializers.project(project))


# ---- performance evaluation creation (provisional variant) ------------------

def _evaluation_metrics(project, weighted):
    runs = derive.runs_of_project(project["id"])
    before = [r for r in runs if r["study_role"] == "BEFORE"]
    after = [r for r in runs if r["study_role"] == "AFTER"]
    if weighted:
        cutoff = project.get("last_tuning_completed_at")
        if cutoff is not None:
            after = [r for r in after if r["recorded_at"] >= cutoff]
    if not before:
        fail("ERR_BEFORE_STUDY_INCOMPLETE")
    if not after:
        fail("ERR_NO_AFTER_STUDY")
    return calc.performance_metrics(before, after, weighted)


@bp.route(
    "/signal-ops/retiming-projects/<project_id>/performance-evaluations", methods=["POST"]
)
@auth.roles(CERTIFYING_ENGINEER)
def create_evaluation(project_id):
    project = lookups.project(project_id)
    data = validators.body()
    expected = validators.req_int(data, "expected_project_version", 0, None)
    lookups.not_terminal(project)
    if project["status"] not in ("FIELD_TUNING", "EVALUATION"):
        fail("ERR_PROJECT_NOT_IN_EVALUATION")
    if expected != project["version"]:
        fail("ERR_STALE_PROJECT_VERSION")

    metrics = _evaluation_metrics(project, weighted=False)

    previous = [
        e for e in derive.evaluations_of_project(project["id"]) if e["status"] == "PROVISIONAL"
    ]
    previous.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for old in previous:
        old["status"] = "SUPERSEDED"
        touch(old)

    row = {
        "project_id": project["id"],
        "status": "PROVISIONAL",
        "metric_variant": "PROVISIONAL_UNWEIGHTED",
        "certified_by_user_id": None,
    }
    row.update(metrics)
    row.update(base_row())
    db.evaluations[row["id"]] = row
    touch(project)
    return response.created(serializers.performance_evaluation(row))


# ---- the coordination pipeline ---------------------------------------------

@bp.route("/signal-ops/retiming-projects/<project_id>/coordinate", methods=["POST"])
@auth.roles(TIMING_ENGINEER)
def coordinate_project(project_id):
    project = lookups.project(project_id)
    validators.body()
    lookups.not_terminal(project)
    if project["status"] != "PLAN_DEVELOPMENT":
        fail("ERR_PROJECT_NOT_IN_PLAN_DEVELOPMENT")

    # SUPERSEDED plans are terminal debris and are not part of the live set.
    live = [p for p in derive.plans_of_project(project["id"]) if p["status"] != "SUPERSEDED"]
    for plan in live:
        if plan["status"] != "DRAFT":
            fail("ERR_PLAN_NOT_DRAFT")
    if not live:
        fail("ERR_INVALID_REQUEST", "The project holds no timing plan to coordinate.")

    before_counts = {}
    for count in derive.counts_of_project(project["id"]):
        if count["study_role"] == "BEFORE":
            before_counts.setdefault(count["intersection_id"], []).append(count)

    planned_intersections = set(p["intersection_id"] for p in live)
    for member in derive.eligible_members(project["corridor_id"]):
        if member["intersection_id"] not in planned_intersections:
            continue
        if not before_counts.get(member["intersection_id"]):
            fail("ERR_BEFORE_STUDY_INCOMPLETE")

    # PIPELINE STEP 1/2 -- the participants and their recommended cycles.
    asks = []
    ceilings = []
    for member in derive.members_of(project["corridor_id"]):
        intersection = db.intersections.get(member["intersection_id"])
        if intersection is None or derive.posture(intersection) not in derive.ELIGIBLE_POSTURES:
            continue
        masters = [
            p
            for p in live
            if p["intersection_id"] == member["intersection_id"]
            and p["coordination_ref"] == "MASTER"
        ]
        if not masters:
            continue
        chosen = calc.pick_pipeline_count(before_counts.get(member["intersection_id"], []))
        if chosen is None:
            continue
        cfr = calc.critical_flow_ratio(chosen["phase_volumes"])
        if calc.is_oversaturated(cfr):
            fail("ERR_OVERSATURATED_APPROACH")
        chosen["critical_flow_ratio_sum"] = calc.round_half_up(cfr, 4)
        chosen["recommended_cycle_sec"] = calc.recommended_cycle_sec(
            chosen["phase_volumes"], intersection["max_cycle_length_sec"], cfr
        )
        asks.append(chosen["recommended_cycle_sec"])
        ceilings.append(intersection["max_cycle_length_sec"])

    coordinated = calc.coordinated_cycle(asks) if asks else None
    if coordinated is not None and coordinated > min(ceilings):
        fail("ERR_CYCLE_EXCEEDS_LOCAL_MAX")

    # PIPELINE STEP 3 -- the coordinated cycle overwrites every master plan.
    if coordinated is not None:
        for plan in live:
            if plan["coordination_ref"] == "MASTER":
                plan["cycle_length_sec"] = coordinated

    # PIPELINE STEP 4 -- split rescaling against each plan's operating cycle.
    for plan in live:
        splits = derive.splits_of_plan(plan["id"])
        drafted_total, effective_total = calc.rescale_splits(splits, plan["cycle_length_sec"])
        plan["drafted_split_total_sec"] = drafted_total
        plan["effective_split_total_sec"] = effective_total

    # PIPELINE STEP 5 -- progression offsets.
    cumulative = {}
    running = 0.0
    for member in derive.members_of(project["corridor_id"]):
        running += float(member["distance_from_prev_ft"])
        cumulative.setdefault(member["intersection_id"], running)
    for plan in live:
        if plan["coordination_ref"] == "LOCAL_FREE":
            plan["offset_sec"] = 0
        else:
            plan["offset_sec"] = calc.offset_sec(
                cumulative.get(plan["intersection_id"], 0.0), plan["cycle_length_sec"]
            )

    # PIPELINE STEPS 6/7/8 -- pedestrian compliance, then the status moves.
    for plan in live:
        intersection = db.intersections.get(plan["intersection_id"])
        any_failing = False
        for split in derive.splits_of_plan(plan["id"]):
            if not split["is_pedestrian_phase"] or intersection is None:
                continue
            verdict = calc.ped_requirements(split, intersection)
            check = {
                "timing_plan_id": plan["id"],
                "phase_number": split["phase_number"],
                "waived_by_user_id": None,
                "waiver_justification": None,
            }
            check.update(verdict)
            check.update(base_row())
            db.ped_checks[check["id"]] = check
            if verdict["result"] == "FAIL":
                any_failing = True
        plan["ped_compliance_state"] = "NON_COMPLIANT" if any_failing else "COMPLIANT"
        plan["status"] = "COORDINATED"
        touch(plan)

    touch(project)
    return response.ok(serializers.project(project))


# ---- implementation, fine tuning and disposition ---------------------------

@bp.route("/signal-ops/retiming-projects/<project_id>/implement", methods=["POST"])
@auth.roles(TIMING_ENGINEER)
def implement_project(project_id):
    project = lookups.project(project_id)
    validators.body()
    lookups.not_terminal(project)
    if project["status"] != "PLAN_DEVELOPMENT":
        fail("ERR_PROJECT_NOT_IN_PLAN_DEVELOPMENT")

    certified = set(
        p["intersection_id"]
        for p in derive.plans_of_project(project["id"])
        if p["status"] == "CERTIFIED"
    )
    for member in derive.eligible_members(project["corridor_id"]):
        if member["intersection_id"] not in certified:
            fail("ERR_PLAN_COVERAGE_INCOMPLETE")

    cascades.implementation_cascade(project)
    return response.ok(serializers.project(project))


@bp.route("/signal-ops/retiming-projects/<project_id>/field-tuning", methods=["POST"])
@auth.roles(SIGNAL_OPS_ADMIN)
def field_tuning(project_id):
    project = lookups.project(project_id)
    data = validators.body()
    action = validators.req_enum(data, "action", ACTIONS)
    lookups.not_terminal(project)

    if action == "START":
        if project["status"] != "IMPLEMENTED":
            fail("ERR_PROJECT_NOT_IMPLEMENTED")
        project["status"] = "FIELD_TUNING"
        project["_field_tuning_started_at"] = clock.now()
        touch(project)
        return response.ok(serializers.project(project))

    if project["status"] != "FIELD_TUNING":
        fail("ERR_PROJECT_NOT_IN_FIELD_TUNING")
    for observation in derive.observations_of_project(project["id"]):
        if observation["resolution_status"] == "OPEN":
            fail("ERR_OBSERVATIONS_UNRESOLVED")
    project["status"] = "EVALUATION"
    project["last_tuning_completed_at"] = clock.now()
    touch(project)
    return response.ok(serializers.project(project))


@bp.route("/signal-ops/retiming-projects/<project_id>/close", methods=["POST"])
@auth.roles(SIGNAL_OPS_ADMIN)
def close_project(project_id):
    project = lookups.project(project_id)
    data = validators.body()
    disposition = validators.req_enum(data, "disposition", DISPOSITIONS)
    validators.opt_str(data, "note", 1, None)
    lookups.not_terminal(project)

    if disposition == "CLOSED":
        if project["status"] != "EVALUATION":
            fail("ERR_PROJECT_NOT_IN_EVALUATION")
        certified = [
            e for e in derive.evaluations_of_project(project["id"]) if e["status"] == "CERTIFIED"
        ]
        if not certified:
            fail("ERR_EVALUATION_NOT_FOUND")
        cascades.close_cascade(project)
        return response.ok(serializers.project(project))

    if project["status"] not in ("DATA_COLLECTION", "PLAN_DEVELOPMENT"):
        fail("ERR_PROJECT_TERMINAL")
    cascades.abandon_cascade(project)
    return response.ok(serializers.project(project))
