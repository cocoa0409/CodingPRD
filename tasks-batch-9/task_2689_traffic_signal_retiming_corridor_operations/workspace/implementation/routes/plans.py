"""Timing plans, phase splits, pedestrian checks and certification
(PRD sections 3.5, 3.7, 3.8)."""

from flask import Blueprint

import auth
import cascades
import derive
import lookups
import response
import serializers
import validators
from auth import CERTIFYING_ENGINEER, STAFF, TIMING_ENGINEER
from db import base_row, db, touch
from errors import fail

bp = Blueprint("plans", __name__)

TOD_PERIODS = ("AM_PEAK", "MID_DAY", "PM_PEAK", "OFF_PEAK")
COORDINATION_REFS = ("MASTER", "LOCAL_FREE")
PAST_DRAFTING = ("COORDINATED", "SUBMITTED", "CERTIFIED", "DEPLOYED")
LIVE_WINDOW_STATUSES = ("COORDINATED", "SUBMITTED", "CERTIFIED", "DEPLOYED")


@bp.route("/signal-ops/timing-plans", methods=["POST"])
@auth.roles(TIMING_ENGINEER)
def create_plan():
    data = validators.body()
    project_id = validators.req_id(data, "project_id")
    intersection_id = validators.req_id(data, "intersection_id")
    project = lookups.project(project_id)
    intersection = lookups.intersection(intersection_id)
    tod_period = validators.req_enum(data, "tod_period", TOD_PERIODS)
    tod_start_min = validators.req_int(data, "tod_start_min", 0, 1439)
    tod_end_min = validators.req_int(data, "tod_end_min", 1, 1440)
    if tod_end_min <= tod_start_min:
        fail("ERR_INVALID_REQUEST", "tod_end_min must be strictly greater than tod_start_min.")
    cycle_length_sec = validators.req_int(data, "cycle_length_sec", 60, 240)
    coordination_ref = validators.opt_enum(
        data, "coordination_ref", COORDINATION_REFS, "MASTER"
    )
    expected = validators.req_int(data, "expected_project_version", 0, None)

    lookups.not_terminal(project)
    if project["status"] != "PLAN_DEVELOPMENT":
        fail("ERR_PROJECT_NOT_IN_PLAN_DEVELOPMENT")
    if expected != project["version"]:
        fail("ERR_STALE_PROJECT_VERSION")
    if cycle_length_sec > intersection["max_cycle_length_sec"]:
        fail("ERR_CYCLE_EXCEEDS_LOCAL_MAX")

    siblings = [
        p
        for p in derive.plans_of_project(project["id"])
        if p["intersection_id"] == intersection["id"] and p["tod_period"] == tod_period
    ]
    for sibling in siblings:
        if sibling["status"] in PAST_DRAFTING:
            fail("ERR_DUPLICATE_TOD_PLAN")

    for sibling in siblings:
        if sibling["status"] == "DRAFT":
            sibling["status"] = "SUPERSEDED"
            touch(sibling)

    row = {
        "project_id": project["id"],
        "intersection_id": intersection["id"],
        "tod_period": tod_period,
        "tod_start_min": tod_start_min,
        "tod_end_min": tod_end_min,
        "coordination_ref": coordination_ref,
        "cycle_length_sec": cycle_length_sec,
        "drafted_cycle_length_sec": cycle_length_sec,
        "offset_sec": 0,
        "status": "DRAFT",
        "ped_compliance_state": "PENDING",
        "drafted_split_total_sec": 0,
        "effective_split_total_sec": 0,
        "authored_by_user_id": auth.user_id(),
        "certified_by_user_id": None,
        "return_count": 0,
    }
    row.update(base_row())
    db.plans[row["id"]] = row
    touch(project)
    return response.created(serializers.timing_plan(row))


@bp.route("/signal-ops/timing-plans/<plan_id>", methods=["GET"])
@auth.roles(*STAFF)
def read_plan(plan_id):
    row = lookups.plan(plan_id)
    return response.ok(serializers.timing_plan(row))


@bp.route("/signal-ops/timing-plans/<plan_id>/phase-splits", methods=["GET"])
@auth.roles(*STAFF)
def list_splits(plan_id):
    lookups.plan(plan_id)
    rows = derive.splits_of_plan(plan_id)
    return lookups.listing(rows, serializers.phase_split)


@bp.route("/signal-ops/timing-plans/<plan_id>/pedestrian-checks", methods=["GET"])
@auth.roles(*STAFF)
def list_checks(plan_id):
    lookups.plan(plan_id)
    rows = derive.checks_of_plan(plan_id)
    rows = lookups.apply_filter(rows, "result")
    return lookups.listing(rows, serializers.ped_check)


@bp.route("/signal-ops/timing-plans/<plan_id>/phase-splits", methods=["POST"])
@auth.roles(TIMING_ENGINEER)
def create_split(plan_id):
    plan = lookups.plan(plan_id)
    data = validators.body()
    phase_number = validators.req_int(data, "phase_number", 1, 8)
    split_sec = validators.req_int(data, "split_sec", 5, 240)
    min_green_sec = validators.req_int(data, "min_green_sec", 1, 60)
    yellow_sec = validators.req_num(data, "yellow_sec", 3.0, 6.0)
    red_clearance_sec = validators.req_num(data, "red_clearance_sec", 0.0, 6.0)
    is_pedestrian_phase = validators.opt_bool(data, "is_pedestrian_phase", False)
    walk_sec = validators.opt_num(data, "walk_sec", 0, None, 0)
    ped_clear_sec = validators.opt_num(data, "ped_clear_sec", 0, None, 0)
    crosswalk_length_ft = validators.opt_num(data, "crosswalk_length_ft", 0, None, 0)
    if is_pedestrian_phase and (
        walk_sec <= 0 or ped_clear_sec <= 0 or crosswalk_length_ft <= 0
    ):
        fail(
            "ERR_INVALID_REQUEST",
            "walk_sec, ped_clear_sec and crosswalk_length_ft must exceed 0 on a pedestrian phase.",
        )

    if plan["status"] != "DRAFT":
        fail("ERR_PLAN_NOT_DRAFT")
    for existing in derive.splits_of_plan(plan["id"]):
        if existing["phase_number"] == phase_number:
            fail("ERR_DUPLICATE_PHASE_NUMBER")

    row = {
        "timing_plan_id": plan["id"],
        "phase_number": phase_number,
        "split_sec": split_sec,
        "effective_split_sec": split_sec,
        "min_green_sec": min_green_sec,
        "yellow_sec": yellow_sec,
        "red_clearance_sec": red_clearance_sec,
        "is_pedestrian_phase": is_pedestrian_phase,
        "walk_sec": walk_sec,
        "ped_clear_sec": ped_clear_sec,
        "crosswalk_length_ft": crosswalk_length_ft,
    }
    row.update(base_row())
    db.phase_splits[row["id"]] = row
    derive.refresh_plan_totals(plan)
    touch(plan)
    return response.created(serializers.phase_split(row))


@bp.route("/signal-ops/phase-splits/<split_id>", methods=["PATCH"])
@auth.roles(TIMING_ENGINEER)
def update_split(split_id):
    row = lookups.phase_split(split_id)
    data = validators.body()
    split_sec = validators.opt_int(data, "split_sec", 5, 240, row["split_sec"])
    min_green_sec = validators.opt_int(data, "min_green_sec", 1, 60, row["min_green_sec"])
    yellow_sec = validators.opt_num(data, "yellow_sec", 3.0, 6.0, row["yellow_sec"])
    red_clearance_sec = validators.opt_num(
        data, "red_clearance_sec", 0.0, 6.0, row["red_clearance_sec"]
    )
    walk_sec = validators.opt_num(data, "walk_sec", 0, None, row["walk_sec"])
    ped_clear_sec = validators.opt_num(data, "ped_clear_sec", 0, None, row["ped_clear_sec"])
    crosswalk_length_ft = validators.opt_num(
        data, "crosswalk_length_ft", 0, None, row["crosswalk_length_ft"]
    )
    if row["is_pedestrian_phase"] and (
        walk_sec <= 0 or ped_clear_sec <= 0 or crosswalk_length_ft <= 0
    ):
        fail(
            "ERR_INVALID_REQUEST",
            "walk_sec, ped_clear_sec and crosswalk_length_ft must exceed 0 on a pedestrian phase.",
        )

    plan = db.plans.get(row["timing_plan_id"])
    if plan is None or plan["status"] != "DRAFT":
        fail("ERR_PLAN_NOT_DRAFT")

    row["split_sec"] = split_sec
    row["effective_split_sec"] = split_sec
    row["min_green_sec"] = min_green_sec
    row["yellow_sec"] = yellow_sec
    row["red_clearance_sec"] = red_clearance_sec
    row["walk_sec"] = walk_sec
    row["ped_clear_sec"] = ped_clear_sec
    row["crosswalk_length_ft"] = crosswalk_length_ft
    touch(row)
    derive.refresh_plan_totals(plan)
    touch(plan)
    return response.ok(serializers.phase_split(row))


# ---- submission, certification, return -------------------------------------

@bp.route("/signal-ops/timing-plans/<plan_id>/submit", methods=["POST"])
@auth.roles(TIMING_ENGINEER)
def submit_plan(plan_id):
    plan = lookups.plan(plan_id)
    validators.body()
    if plan["status"] != "COORDINATED":
        fail("ERR_PLAN_NOT_COORDINATED")
    if plan["ped_compliance_state"] not in ("COMPLIANT", "WAIVED"):
        fail("ERR_PED_CLEARANCE_INSUFFICIENT")
    for split in derive.splits_of_plan(plan["id"]):
        required = (
            float(split["min_green_sec"])
            + float(split["yellow_sec"])
            + float(split["red_clearance_sec"])
        )
        if float(split["effective_split_sec"]) < required:
            fail("ERR_MIN_GREEN_VIOLATION")

    # Half-open [tod_start_min, tod_end_min) overlap, no buffer, adjacency fine.
    for other in db.plans.values():
        if other["id"] == plan["id"]:
            continue
        if other["intersection_id"] != plan["intersection_id"]:
            continue
        if other["status"] not in LIVE_WINDOW_STATUSES:
            continue
        if plan["tod_start_min"] < other["tod_end_min"] and (
            other["tod_start_min"] < plan["tod_end_min"]
        ):
            fail("ERR_TOD_WINDOW_OVERLAP")

    plan["status"] = "SUBMITTED"
    touch(plan)
    return response.ok(serializers.timing_plan(plan))


@bp.route("/signal-ops/timing-plans/<plan_id>/certify", methods=["POST"])
@auth.roles(CERTIFYING_ENGINEER)
def certify_plan(plan_id):
    plan = lookups.plan(plan_id)
    auth.segregation(plan["authored_by_user_id"])
    validators.body()
    if plan["status"] != "SUBMITTED":
        fail("ERR_PLAN_NOT_SUBMITTED")
    intersection = db.intersections.get(plan["intersection_id"])
    if intersection is None or derive.posture(intersection) == "BLOCKED":
        fail("ERR_POSTURE_BLOCKS_CERTIFICATION")
    plan["status"] = "CERTIFIED"
    plan["certified_by_user_id"] = auth.user_id()
    touch(plan)
    return response.ok(serializers.timing_plan(plan))


@bp.route("/signal-ops/timing-plans/<plan_id>/return", methods=["POST"])
@auth.roles(CERTIFYING_ENGINEER)
def return_plan(plan_id):
    plan = lookups.plan(plan_id)
    data = validators.body()
    validators.req_str(data, "reason", 1, None)
    if plan["status"] != "SUBMITTED":
        fail("ERR_PLAN_NOT_SUBMITTED")
    cascades.compensate_plan(plan)
    plan["status"] = "DRAFT"
    plan["return_count"] = plan["return_count"] + 1
    touch(plan)
    return response.ok(serializers.timing_plan(plan))


@bp.route("/signal-ops/pedestrian-checks/<check_id>/waive", methods=["POST"])
@auth.roles(CERTIFYING_ENGINEER)
def waive_check(check_id):
    check = lookups.ped_check(check_id)
    plan = db.plans.get(check["timing_plan_id"])
    auth.segregation(plan["authored_by_user_id"] if plan else None)
    data = validators.body()
    justification = validators.req_str(data, "waiver_justification", 1, None)
    if check["result"] != "FAIL":
        fail("ERR_PED_CHECK_NOT_FAILING")
    if plan is None or plan["status"] != "COORDINATED":
        fail("ERR_PLAN_NOT_COORDINATED")

    check["result"] = "WAIVED"
    check["failure_reason"] = check.get("failure_reason")
    check["waived_by_user_id"] = auth.user_id()
    check["waiver_justification"] = justification
    touch(check)

    remaining = [c for c in derive.checks_of_plan(plan["id"]) if c["result"] == "FAIL"]
    if not remaining:
        plan["ped_compliance_state"] = "WAIVED"
        touch(plan)
    return response.ok(serializers.ped_check(check))
