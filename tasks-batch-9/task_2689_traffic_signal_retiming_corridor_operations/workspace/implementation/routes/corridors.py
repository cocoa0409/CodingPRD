"""Corridor assembly, screening and program selection (PRD section 3.2)."""

from flask import Blueprint

import auth
import calc
import clock
import derive
import lookups
import response
import serializers
import validators
from auth import SIGNAL_OPS_ADMIN, STAFF
from db import base_row, db, touch
from errors import fail

bp = Blueprint("corridors", __name__)

JURISDICTION_CLASSES = ("ARTERIAL", "COLLECTOR", "LOCAL")
DECISIONS = ("SELECT", "DEFER")


@bp.route("/signal-ops/corridors", methods=["POST"])
@auth.roles(SIGNAL_OPS_ADMIN)
def create_corridor():
    data = validators.body()
    name = validators.req_str(data, "name", 1, 120)
    jurisdiction_class = validators.req_enum(data, "jurisdiction_class", JURISDICTION_CLASSES)
    volume_change = validators.opt_num(data, "annual_volume_change_pct", -100.0, 400.0, 0)
    for existing in db.corridors.values():
        if existing["name"] == name:
            fail("ERR_INVALID_REQUEST", "A corridor with that name already exists.")
    row = {
        "name": name,
        "jurisdiction_class": jurisdiction_class,
        "annual_volume_change_pct": volume_change,
        "selection_status": "UNSCREENED",
        "avg_plan_age_days": 0,
        "complaint_count_12mo": 0,
        "priority_score": 0,
        "priority_score_variant": None,
        "screened_at": None,
    }
    row.update(base_row())
    db.corridors[row["id"]] = row
    return response.created(serializers.corridor(row))


@bp.route("/signal-ops/corridors", methods=["GET"])
@auth.roles(*STAFF)
def list_corridors():
    rows = sorted(db.corridors.values(), key=lambda r: r["_seq"])
    rows = lookups.apply_filter(rows, "selection_status")
    rows = lookups.apply_filter(rows, "jurisdiction_class")
    return lookups.listing(rows, serializers.corridor)


@bp.route("/signal-ops/corridors/<corridor_id>", methods=["GET"])
@auth.roles(*STAFF)
def read_corridor(corridor_id):
    row = lookups.corridor(corridor_id)
    return response.ok(serializers.corridor(row))


@bp.route("/signal-ops/corridors/<corridor_id>/members", methods=["POST"])
@auth.roles(SIGNAL_OPS_ADMIN)
def create_member(corridor_id):
    corridor = lookups.corridor(corridor_id)
    data = validators.body()
    intersection = lookups.intersection(validators.req_id(data, "intersection_id"))
    sequence_index = validators.req_int(data, "sequence_index", 1, None)
    distance = validators.opt_num(data, "distance_from_prev_ft", 0, None, 0)
    if sequence_index == 1 and distance != 0:
        fail("ERR_INVALID_REQUEST", "distance_from_prev_ft must be exactly 0 at sequence_index 1.")

    members = derive.members_of(corridor["id"])
    for member in members:
        if member["intersection_id"] == intersection["id"]:
            fail("ERR_DUPLICATE_CORRIDOR_MEMBER")
    if sequence_index != len(members) + 1:
        fail("ERR_SEQUENCE_INDEX_GAP")

    row = {
        "corridor_id": corridor["id"],
        "intersection_id": intersection["id"],
        "sequence_index": sequence_index,
        "distance_from_prev_ft": distance,
    }
    row.update(base_row(common=False))
    db.corridor_members[row["id"]] = row
    touch(corridor)
    return response.created(serializers.corridor_member(row))


@bp.route("/signal-ops/corridors/<corridor_id>/members", methods=["GET"])
@auth.roles(*STAFF)
def list_members(corridor_id):
    lookups.corridor(corridor_id)
    rows = derive.members_of(corridor_id)
    return lookups.listing(rows, serializers.corridor_member)


@bp.route("/signal-ops/corridors/<corridor_id>/retiming-projects", methods=["GET"])
@auth.roles(*STAFF)
def list_corridor_projects(corridor_id):
    lookups.corridor(corridor_id)
    rows = derive.projects_of_corridor(corridor_id)
    rows = lookups.apply_filter(rows, "status")
    return lookups.listing(rows, serializers.project)


@bp.route("/signal-ops/corridors/<corridor_id>/complaints", methods=["GET"])
@auth.roles(*STAFF)
def list_corridor_complaints(corridor_id):
    lookups.corridor(corridor_id)
    rows = derive.complaints_of_corridor(corridor_id)
    rows.sort(key=lambda c: c["_seq"])
    rows = lookups.apply_filter(rows, "status")
    rows = lookups.apply_filter(rows, "category")
    return lookups.listing(rows, serializers.complaint)


@bp.route("/signal-ops/corridors/<corridor_id>/screen", methods=["POST"])
@auth.roles(SIGNAL_OPS_ADMIN)
def screen_corridor(corridor_id):
    corridor = lookups.corridor(corridor_id)
    validators.body()

    if not derive.eligible_members(corridor["id"]):
        fail("ERR_NO_ELIGIBLE_MEMBERS")
    if corridor["selection_status"] == "SELECTED" and derive.has_live_project(corridor["id"]):
        fail("ERR_CORRIDOR_PROJECT_ACTIVE")

    corridor["complaint_count_12mo"] = derive.complaint_count_12mo(corridor["id"])
    derive.recompute_corridor_score(corridor, screening=True)
    corridor["selection_status"] = "SCREENED"
    corridor["screened_at"] = clock.now()
    touch(corridor)
    return response.ok(serializers.corridor(corridor))


@bp.route("/signal-ops/corridors/<corridor_id>/selection-decision", methods=["POST"])
@auth.roles(SIGNAL_OPS_ADMIN)
def selection_decision(corridor_id):
    corridor = lookups.corridor(corridor_id)
    data = validators.body()
    decision = validators.req_enum(data, "decision", DECISIONS)
    validators.opt_str(data, "rationale", 1, None)

    if corridor["selection_status"] != "SCREENED":
        fail("ERR_CORRIDOR_NOT_SCREENED")

    # Recompute under the programming variant without committing anything yet:
    # a refused SELECT must write nothing at all.
    complaint_count = derive.complaint_count_12mo(corridor["id"])
    ages = derive.member_ages(corridor["id"], screening=False)
    avg_age = calc.avg_plan_age_days(ages)
    score = calc.priority_score(
        avg_age, corridor["annual_volume_change_pct"], complaint_count,
        corridor["jurisdiction_class"],
    )

    if decision == "SELECT":
        if score < calc.SELECT_SCORE_THRESHOLD:
            fail("ERR_SCORE_BELOW_SELECT_THRESHOLD")
        if derive.has_live_project(corridor["id"]):
            fail("ERR_CORRIDOR_PROJECT_ACTIVE")

    corridor["complaint_count_12mo"] = complaint_count
    corridor["avg_plan_age_days"] = avg_age
    corridor["priority_score"] = score
    corridor["priority_score_variant"] = "PROGRAMMING"
    corridor["selection_status"] = "SELECTED" if decision == "SELECT" else "DEFERRED"
    touch(corridor)
    return response.ok(serializers.corridor(corridor))
