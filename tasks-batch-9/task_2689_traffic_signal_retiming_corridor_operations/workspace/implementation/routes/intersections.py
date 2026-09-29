"""The signal inventory (PRD section 3.1)."""

from flask import Blueprint

import auth
import calc
import clock
import derive
import lookups
import response
import serializers
import validators
from auth import (
    CERTIFYING_ENGINEER,
    FIELD_TECHNICIAN,
    SIGNAL_OPS_ADMIN,
    STAFF,
)
from db import base_row, db, touch
from errors import fail

bp = Blueprint("intersections", __name__)

CONTROLLER_TYPES = ("TS2_CABINET", "ATC_CABINET", "LEGACY_170")
DETECTION_STATUSES = ("FULL", "PARTIAL", "FAILED", "NONE")
COMM_STATUSES = ("ONLINE", "INTERMITTENT", "OFFLINE")
WALKING_SPEED_STANDARDS = ("STD_3_5_FPS", "EXTENDED_3_0_FPS")
STUDY_ROLES = ("BEFORE", "AFTER")
COUNT_PERIODS = ("AM_PEAK", "MID_DAY", "PM_PEAK")


def _check_aps(aps_installed, walking_speed_standard):
    if aps_installed and walking_speed_standard != "EXTENDED_3_0_FPS":
        fail("ERR_APS_STANDARD_MISMATCH")
    if not aps_installed and walking_speed_standard == "EXTENDED_3_0_FPS":
        fail("ERR_APS_STANDARD_MISMATCH")


@bp.route("/signal-ops/intersections", methods=["POST"])
@auth.roles(SIGNAL_OPS_ADMIN)
def create_intersection():
    data = validators.body()
    row = {
        "location_name": validators.req_str(data, "location_name", 1, 120),
        "controller_type": validators.req_enum(data, "controller_type", CONTROLLER_TYPES),
        "detection_status": validators.opt_enum(
            data, "detection_status", DETECTION_STATUSES, "FULL"
        ),
        "comm_status": validators.opt_enum(data, "comm_status", COMM_STATUSES, "ONLINE"),
        "aps_installed": validators.opt_bool(data, "aps_installed", False),
        "walking_speed_standard": validators.opt_enum(
            data, "walking_speed_standard", WALKING_SPEED_STANDARDS, "STD_3_5_FPS"
        ),
        "pedestrian_recall": validators.opt_bool(data, "pedestrian_recall", False),
        "max_cycle_length_sec": validators.opt_int(data, "max_cycle_length_sec", 60, 240, 150),
        "last_retimed_at": None,
    }
    # Registration only refuses the aps-on / standard-short pairing.
    if row["aps_installed"] and row["walking_speed_standard"] != "EXTENDED_3_0_FPS":
        fail("ERR_APS_STANDARD_MISMATCH")
    row.update(base_row())
    db.intersections[row["id"]] = row
    return response.created(serializers.intersection(row))


@bp.route("/signal-ops/intersections", methods=["GET"])
@auth.roles(*STAFF)
def list_intersections():
    rows = sorted(db.intersections.values(), key=lambda r: r["_seq"])
    rows = lookups.apply_filter(rows, "controller_type")
    rows = lookups.apply_filter(rows, "comm_status")
    rows = lookups.apply_filter(rows, "detection_status")
    posture = validators.filter_arg("operational_posture")
    if posture is not None:
        rows = [r for r in rows if derive.posture(r) == posture]
    return lookups.listing(rows, serializers.intersection)


@bp.route("/signal-ops/intersections/<intersection_id>", methods=["GET"])
@auth.roles(*STAFF)
def read_intersection(intersection_id):
    row = lookups.intersection(intersection_id)
    return response.ok(serializers.intersection(row))


@bp.route("/signal-ops/intersections/<intersection_id>", methods=["PATCH"])
@auth.roles(SIGNAL_OPS_ADMIN)
def update_intersection(intersection_id):
    row = lookups.intersection(intersection_id)
    data = validators.body()
    detection_status = validators.opt_enum(
        data, "detection_status", DETECTION_STATUSES, row["detection_status"]
    )
    comm_status = validators.opt_enum(data, "comm_status", COMM_STATUSES, row["comm_status"])
    aps_installed = validators.opt_bool(data, "aps_installed", row["aps_installed"])
    walking_speed_standard = validators.opt_enum(
        data, "walking_speed_standard", WALKING_SPEED_STANDARDS, row["walking_speed_standard"]
    )
    pedestrian_recall = validators.opt_bool(
        data, "pedestrian_recall", row["pedestrian_recall"]
    )
    max_cycle_length_sec = validators.opt_int(
        data, "max_cycle_length_sec", 60, 240, row["max_cycle_length_sec"]
    )
    if "aps_installed" in data or "walking_speed_standard" in data:
        _check_aps(aps_installed, walking_speed_standard)
    row["detection_status"] = detection_status
    row["comm_status"] = comm_status
    row["aps_installed"] = aps_installed
    row["walking_speed_standard"] = walking_speed_standard
    row["pedestrian_recall"] = pedestrian_recall
    row["max_cycle_length_sec"] = max_cycle_length_sec
    touch(row)
    return response.ok(serializers.intersection(row))


@bp.route("/signal-ops/intersections/<intersection_id>/corridor-memberships", methods=["GET"])
@auth.roles(*STAFF)
def list_intersection_memberships(intersection_id):
    lookups.intersection(intersection_id)
    rows = derive.memberships_of_intersection(intersection_id)
    return lookups.listing(rows, serializers.corridor_member)


@bp.route("/signal-ops/intersections/<intersection_id>/timing-plans", methods=["GET"])
@auth.roles(*STAFF)
def list_intersection_plans(intersection_id):
    lookups.intersection(intersection_id)
    rows = [p for p in db.plans.values() if p["intersection_id"] == intersection_id]
    rows.sort(key=lambda p: p["_seq"])
    rows = lookups.apply_filter(rows, "status")
    rows = lookups.apply_filter(rows, "tod_period")
    return lookups.listing(rows, serializers.timing_plan)


@bp.route("/signal-ops/intersections/<intersection_id>/priority-configs", methods=["GET"])
@auth.roles(*STAFF)
def list_intersection_configs(intersection_id):
    lookups.intersection(intersection_id)
    rows = derive.configs_of(intersection_id)
    rows.sort(key=lambda c: c["_seq"])
    rows = lookups.apply_filter(rows, "priority_type")
    rows = lookups.apply_filter(rows, "approval_status")
    rows = lookups.apply_filter(rows, "deployment_status")
    return lookups.listing(rows, serializers.priority_config)


@bp.route("/signal-ops/intersections/<intersection_id>/field-observations", methods=["GET"])
@auth.roles(*STAFF)
def list_intersection_observations(intersection_id):
    lookups.intersection(intersection_id)
    rows = [o for o in db.observations.values() if o["intersection_id"] == intersection_id]
    rows.sort(key=lambda o: o["_seq"])
    rows = lookups.apply_filter(rows, "resolution_status")
    return lookups.listing(rows, serializers.field_observation)


@bp.route(
    "/signal-ops/intersections/<intersection_id>/turning-movement-counts", methods=["GET"]
)
@auth.roles(*STAFF)
def list_intersection_counts(intersection_id):
    lookups.intersection(intersection_id)
    rows = [c for c in db.counts.values() if c["intersection_id"] == intersection_id]
    rows.sort(key=lambda c: c["_seq"])
    rows = lookups.apply_filter(rows, "study_role")
    rows = lookups.apply_filter(rows, "period")
    return lookups.listing(rows, serializers.turning_movement_count)


@bp.route(
    "/signal-ops/intersections/<intersection_id>/turning-movement-counts", methods=["POST"]
)
@auth.roles(FIELD_TECHNICIAN)
def create_count(intersection_id):
    intersection = lookups.intersection(intersection_id)
    data = validators.body()
    project = lookups.project(validators.req_id(data, "project_id"))
    study_role = validators.req_enum(data, "study_role", STUDY_ROLES)
    count_date = validators.req_ts(data, "count_date")
    period = validators.req_enum(data, "period", COUNT_PERIODS)
    volumes = validators.phase_volumes(data)
    lookups.not_terminal(project)

    cfr_exact = calc.critical_flow_ratio(volumes)
    if calc.is_oversaturated(cfr_exact):
        fail("ERR_OVERSATURATED_APPROACH")
    row = {
        "project_id": project["id"],
        "intersection_id": intersection["id"],
        "study_role": study_role,
        "count_date": count_date,
        "period": period,
        "phase_volumes": volumes,
        "critical_flow_ratio_sum": calc.round_half_up(cfr_exact, 4),
        "recommended_cycle_sec": calc.recommended_cycle_sec(
            volumes, intersection["max_cycle_length_sec"], cfr_exact
        ),
    }
    row.update(base_row(common=False))
    db.counts[row["id"]] = row
    return response.created(serializers.turning_movement_count(row))
