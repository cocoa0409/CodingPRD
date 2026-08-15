"""LegionellaRiskPlan endpoints: create/activate/validate/declare-delinquent/
suspend/return-to-draft."""

from datetime import timedelta

from flask import Blueprint, g

import errors
from calc import recompute_posture, DELINQUENCY_GRACE_DAYS
from db import db, create_entity, touch, now
from helpers import list_response, account_of_plan, query_filter
from response import success_object
from serializers import legionella_plan as ser
from validate import (get_body, validate_shape, resolve, resolve_body_fk,
                      check_cc_ownership)

bp = Blueprint("legionella_plans", __name__)


@bp.route("/wt/legionella-plans", methods=["POST"])
def create_plan():
    body = get_body()
    asset = resolve_body_fk(body, "asset_id", "assets")
    vals = validate_shape(body, [
        ("asset_id", "str", True),
        ("plan_text", "str", True),
        ("validation_interval_days", "int", True),
    ])
    if not (7 <= vals["validation_interval_days"] <= 365):
        raise errors.field_constraint("validation_interval_days must be between 7 and 365 inclusive")
    ent = create_entity("legionella_plans", {
        "asset_id": asset["id"],
        "plan_text": vals["plan_text"],
        "validation_interval_days": vals["validation_interval_days"],
        "last_validated_at": None,
        "validation_due_at": None,
        "status": "DRAFT",
    })
    return success_object(ser(ent), 201)


@bp.route("/wt/legionella-plans", methods=["GET"])
def list_plans():
    user = (g.role, g.user_id)
    items = list(db["legionella_plans"].values())
    asset_id = query_filter("asset_id")
    if asset_id is not None:
        items = [p for p in items if p["asset_id"] == asset_id]
    status = query_filter("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response(items, ser, account_of_plan, user)


@bp.route("/wt/legionella-plans/<planId>", methods=["GET"])
def get_plan(planId):
    ent = db["legionella_plans"].get(planId)
    if ent is not None:
        check_cc_ownership(g.user_id, g.role, account_of_plan(ent))
    ent = resolve("legionella_plans", planId)
    return success_object(ser(ent), 200)


@bp.route("/wt/legionella-plans/<planId>/activate", methods=["POST"])
def activate_plan(planId):
    ent = resolve("legionella_plans", planId)
    get_body()
    if ent["status"] != "DRAFT":
        raise errors.invalid_state("Plan must be DRAFT to activate")
    asset = db["assets"].get(ent["asset_id"])
    if asset is None or asset["status"] != "IN_SERVICE":
        raise errors.ApiError(errors.ERR_ASSET_NOT_IN_SERVICE, 409,
                              "Activating a plan requires the asset to be IN_SERVICE")
    ent["validation_due_at"] = now() + timedelta(days=ent["validation_interval_days"])
    ent["status"] = "ACTIVE"
    touch(ent)
    return success_object(ser(ent), 200)


@bp.route("/wt/legionella-plans/<planId>/validate", methods=["POST"])
def validate_plan(planId):
    ent = resolve("legionella_plans", planId)
    get_body()
    if ent["status"] not in ("VALIDATION_DUE", "DELINQUENT"):
        raise errors.invalid_state("Plan must be VALIDATION_DUE or DELINQUENT to validate")
    current = now()
    ent["last_validated_at"] = current
    ent["validation_due_at"] = current + timedelta(days=ent["validation_interval_days"])
    ent["status"] = "ACTIVE"
    touch(ent)
    asset = db["assets"].get(ent["asset_id"])
    if asset is not None:
        recompute_posture(asset)
    return success_object(ser(ent), 200)


@bp.route("/wt/legionella-plans/<planId>/declare-delinquent", methods=["POST"])
def declare_delinquent(planId):
    ent = resolve("legionella_plans", planId)
    get_body()
    if ent["status"] != "VALIDATION_DUE":
        raise errors.invalid_state("Plan must be VALIDATION_DUE to declare delinquent")
    grace_end = ent["validation_due_at"] + timedelta(days=DELINQUENCY_GRACE_DAYS)
    if not now() > grace_end:
        raise errors.ApiError(errors.ERR_GRACE_NOT_ELAPSED, 422,
                              "Delinquency requires the clock to be strictly past validation_due_at + 14 days")
    ent["status"] = "DELINQUENT"
    touch(ent)
    asset = db["assets"].get(ent["asset_id"])
    if asset is not None:
        recompute_posture(asset)
    return success_object(ser(ent), 200)


@bp.route("/wt/legionella-plans/<planId>/suspend", methods=["POST"])
def suspend_plan(planId):
    ent = resolve("legionella_plans", planId)
    get_body()
    if ent["status"] not in ("ACTIVE", "VALIDATION_DUE", "DELINQUENT"):
        raise errors.invalid_state("Plan must be ACTIVE, VALIDATION_DUE, or DELINQUENT to suspend")
    ent["status"] = "SUSPENDED"
    touch(ent)
    asset = db["assets"].get(ent["asset_id"])
    if asset is not None:
        recompute_posture(asset)
    return success_object(ser(ent), 200)


@bp.route("/wt/legionella-plans/<planId>/return-to-draft", methods=["POST"])
def return_to_draft(planId):
    ent = resolve("legionella_plans", planId)
    get_body()
    if ent["status"] != "SUSPENDED":
        raise errors.invalid_state("Plan must be SUSPENDED to return to draft")
    ent["status"] = "DRAFT"
    touch(ent)
    asset = db["assets"].get(ent["asset_id"])
    if asset is not None:
        recompute_posture(asset)
    return success_object(ser(ent), 200)
