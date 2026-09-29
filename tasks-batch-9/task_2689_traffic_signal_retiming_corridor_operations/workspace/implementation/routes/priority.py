"""Transit and emergency vehicle priority (PRD section 3.9)."""

from flask import Blueprint

import auth
import derive
import lookups
import response
import serializers
import validators
from auth import CERTIFYING_ENGINEER, SIGNAL_OPS_ADMIN, TIMING_ENGINEER
from db import base_row, db, touch
from errors import fail

bp = Blueprint("priority", __name__)

PRIORITY_TYPES = ("TSP", "EVP")
DECISIONS = ("APPROVE", "REJECT")


@bp.route("/signal-ops/priority-configs", methods=["POST"])
@auth.roles(TIMING_ENGINEER)
def create_config():
    data = validators.body()
    intersection = lookups.intersection(validators.req_id(data, "intersection_id"))
    priority_type = validators.req_enum(data, "priority_type", PRIORITY_TYPES)
    requested = validators.req_int(data, "requested_max_extension_sec", 1, 40)
    max_early_green_sec = validators.opt_int(data, "max_early_green_sec", 0, 20, 0)
    rank = validators.req_int(data, "conflict_resolution_rank", 1, 9)
    expected = validators.req_int(data, "expected_intersection_version", 0, None)

    if expected != intersection["version"]:
        fail("ERR_STALE_INTERSECTION_VERSION")

    # A rank is held only by configurations that are not SUSPENDED, per type.
    for existing in derive.configs_of(intersection["id"]):
        if existing["priority_type"] != priority_type:
            continue
        if existing["conflict_resolution_rank"] != rank:
            continue
        if existing["deployment_status"] != "SUSPENDED":
            fail("ERR_DUPLICATE_PRIORITY_RANK")

    row = {
        "intersection_id": intersection["id"],
        "priority_type": priority_type,
        "approval_status": "PROPOSED",
        "deployment_status": "NOT_DEPLOYED",
        "requested_max_extension_sec": requested,
        "max_early_green_sec": max_early_green_sec,
        "conflict_resolution_rank": rank,
        "proposed_by_user_id": auth.user_id(),
        "approved_by_user_id": None,
    }
    row.update(base_row())
    db.priority_configs[row["id"]] = row
    touch(intersection)
    return response.created(serializers.priority_config(row))


@bp.route("/signal-ops/priority-configs/<config_id>/approve", methods=["POST"])
@auth.roles(CERTIFYING_ENGINEER)
def approve_config(config_id):
    config = lookups.priority_config(config_id)
    auth.segregation(config["proposed_by_user_id"])
    data = validators.body()
    decision = validators.req_enum(data, "decision", DECISIONS)
    validators.opt_str(data, "note", 1, None)
    if config["approval_status"] != "PROPOSED":
        fail("ERR_CONFIG_NOT_PROPOSED")
    if decision == "APPROVE":
        config["approval_status"] = "APPROVED"
        config["approved_by_user_id"] = auth.user_id()
    else:
        config["approval_status"] = "REJECTED"
    touch(config)
    return response.ok(serializers.priority_config(config))


@bp.route("/signal-ops/priority-configs/<config_id>/deploy", methods=["POST"])
@auth.roles(SIGNAL_OPS_ADMIN)
def deploy_config(config_id):
    config = lookups.priority_config(config_id)
    validators.body()
    if config["approval_status"] != "APPROVED":
        fail("ERR_CONFIG_NOT_APPROVED")
    if config["deployment_status"] not in ("NOT_DEPLOYED", "SUSPENDED"):
        fail("ERR_CONFIG_NOT_DEPLOYED")
    intersection = db.intersections.get(config["intersection_id"])
    if intersection is None or derive.posture(intersection) != "READY":
        fail("ERR_POSTURE_BLOCKS_DEPLOYMENT")
    if not derive.deployed_plans_of(intersection["id"]):
        fail("ERR_PLAN_COVERAGE_INCOMPLETE")
    if derive.budget_fields(intersection["id"])["unallocated_priority_budget_sec"] <= 0:
        fail("ERR_PRIORITY_BUDGET_EXHAUSTED")

    # granted_extension_sec is derived from the waterfall on every read, so
    # flipping the deployment status re-runs it for every config here.
    config["deployment_status"] = "DEPLOYED"
    touch(config)
    touch(intersection)
    return response.ok(serializers.priority_config(config))


@bp.route("/signal-ops/priority-configs/<config_id>/suspend", methods=["POST"])
@auth.roles(SIGNAL_OPS_ADMIN)
def suspend_config(config_id):
    config = lookups.priority_config(config_id)
    data = validators.body()
    validators.opt_str(data, "reason", 1, None)
    if config["deployment_status"] != "DEPLOYED":
        fail("ERR_CONFIG_NOT_DEPLOYED")
    config["deployment_status"] = "SUSPENDED"
    touch(config)
    intersection = db.intersections.get(config["intersection_id"])
    if intersection is not None:
        touch(intersection)
    return response.ok(serializers.priority_config(config))
