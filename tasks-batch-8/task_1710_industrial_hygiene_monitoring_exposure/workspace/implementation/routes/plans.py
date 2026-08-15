"""Sampling plans: creation, OCC-guarded revision, and lifecycle transitions."""

from flask import Blueprint, request

import db
from errors import (
    ERR_INSUFFICIENT_VALID_SAMPLES,
    ERR_INVALID_DATE_RANGE,
    ERR_PLAN_INVALID_STATE,
    ERR_SOD_PLAN_APPROVER,
    ERR_STALE_VERSION,
    raise_error,
)
from helpers import (
    reject_unknown,
    body, get_or_404, list_response, opt_enum, parse_date, req_date, req_int,
    req_string, stamp_new, touch,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from serializers import plan_out
from services import required_sample_count

bp = Blueprint("plans", __name__)

IH = ("IndustrialHygienist",)
CIH = ("CIHDirector",)

PURPOSES = ("INITIAL", "FOLLOWUP", "VERIFICATION")
UNSAMPLED_TIME_RULES = ("ZERO_FILL", "WORST_CASE")
VOLUME_BASES = ("MEAN_FLOW", "PRE_FLOW")


@bp.route("/ih/sampling-plans", methods=["POST"])
def create_plan():
    user_id, _ = require_auth(IH)
    data = body()
    reject_unknown(data, {"seg_id", "purpose", "planned_start_date", "planned_end_date", "unsampled_time_rule", "volume_basis"})
    seg_id = req_string(data, "seg_id")
    purpose = opt_enum(data, "purpose", PURPOSES, "INITIAL")
    start = req_date(data, "planned_start_date")
    end = req_date(data, "planned_end_date")
    if end < start:
        raise_error(ERR_INVALID_DATE_RANGE,
                    "planned_end_date must be >= planned_start_date")
    unsampled_time_rule = opt_enum(data, "unsampled_time_rule", UNSAMPLED_TIME_RULES, "ZERO_FILL")
    volume_basis = opt_enum(data, "volume_basis", VOLUME_BASES, "MEAN_FLOW")
    seg = get_or_404(db.segs, seg_id, "SimilarExposureGroup")
    plan = {
        "seg_id": seg_id,
        "purpose": purpose,
        "planned_start_date": start.isoformat(),
        "planned_end_date": end.isoformat(),
        "unsampled_time_rule": unsampled_time_rule,
        "volume_basis": volume_basis,
        "required_sample_count": required_sample_count(
            seg["headcount"], seg["current_class"], purpose),
        "active_sample_count": 0,
        "analyzed_valid_count": 0,
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
        "status": "DRAFT",
    }
    stamp_new(plan)
    db.sampling_plans[plan["id"]] = plan
    return success_object(plan_out(plan), 201)


@bp.route("/ih/sampling-plans", methods=["GET"])
def list_plans():
    require_auth(ALL_ROLES)
    return list_response(list(db.sampling_plans.values()), plan_out,
                         {"seg_id": request.args.get("seg_id")})


@bp.route("/ih/sampling-plans/<pid>", methods=["GET"])
def get_plan(pid):
    require_auth(ALL_ROLES)
    return success_object(plan_out(get_or_404(db.sampling_plans, pid, "SamplingPlan")))


@bp.route("/ih/sampling-plans/<pid>", methods=["PUT"])
def revise_plan(pid):
    require_auth(IH)
    data = body()
    reject_unknown(data, {"planned_start_date", "planned_end_date", "unsampled_time_rule", "volume_basis", "expected_plan_version"})
    # Stage 3 schema: OCC field required; optional fields validated.
    expected_plan_version = req_int(data, "expected_plan_version")
    new_start = None
    new_end = None
    if "planned_start_date" in data and data["planned_start_date"] is not None:
        new_start = parse_date(data["planned_start_date"], "planned_start_date")
    if "planned_end_date" in data and data["planned_end_date"] is not None:
        new_end = parse_date(data["planned_end_date"], "planned_end_date")
    if new_start is not None and new_end is not None and new_end < new_start:
        raise_error(ERR_INVALID_DATE_RANGE,
                    "planned_end_date must be >= planned_start_date")
    new_unsampled = opt_enum(data, "unsampled_time_rule", UNSAMPLED_TIME_RULES, None)
    new_basis = opt_enum(data, "volume_basis", VOLUME_BASES, None)
    # Stage 4 existence.
    plan = get_or_404(db.sampling_plans, pid, "SamplingPlan")
    # Merged window validation (partial updates check against stored values).
    if new_start is not None or new_end is not None:
        merged_start = new_start if new_start is not None else _d(plan["planned_start_date"])
        merged_end = new_end if new_end is not None else _d(plan["planned_end_date"])
        if merged_end < merged_start:
            raise_error(ERR_INVALID_DATE_RANGE,
                        "planned_end_date must be >= planned_start_date")
    # Stage 5 OCC: after existence, before any state or business rule.
    if expected_plan_version != plan["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_plan_version does not match the plan's current version")
    # Stage 6 state: revision is a DRAFT-only privilege.
    if plan["status"] != "DRAFT":
        raise_error(ERR_PLAN_INVALID_STATE, "Only a DRAFT plan can be revised")
    if new_start is not None:
        plan["planned_start_date"] = new_start.isoformat()
    if new_end is not None:
        plan["planned_end_date"] = new_end.isoformat()
    if new_unsampled is not None:
        plan["unsampled_time_rule"] = new_unsampled
    if new_basis is not None:
        plan["volume_basis"] = new_basis
    seg = db.segs[plan["seg_id"]]
    plan["required_sample_count"] = required_sample_count(
        seg["headcount"], seg["current_class"], plan["purpose"])
    touch(plan)
    return success_object(plan_out(plan), 200)


def _d(s):
    from datetime import date as _date
    return _date.fromisoformat(s)


@bp.route("/ih/sampling-plans/<pid>/submit", methods=["POST"])
def submit_plan(pid):
    require_auth(IH)
    plan = get_or_404(db.sampling_plans, pid, "SamplingPlan")
    if plan["status"] != "DRAFT":
        raise_error(ERR_PLAN_INVALID_STATE, "submit requires DRAFT")
    plan["status"] = "PENDING_APPROVAL"
    touch(plan)
    return success_object(plan_out(plan), 200)


@bp.route("/ih/sampling-plans/<pid>/approve", methods=["POST"])
def approve_plan(pid):
    user_id, _ = require_auth(CIH)
    plan = get_or_404(db.sampling_plans, pid, "SamplingPlan")
    if plan["status"] != "PENDING_APPROVAL":
        raise_error(ERR_PLAN_INVALID_STATE, "approve requires PENDING_APPROVAL")
    if user_id == plan["created_by_user_id"]:
        raise_error(ERR_SOD_PLAN_APPROVER,
                    "Plan approver must differ from plan creator")
    plan["approved_by_user_id"] = user_id
    plan["status"] = "APPROVED"
    touch(plan)
    return success_object(plan_out(plan), 200)


@bp.route("/ih/sampling-plans/<pid>/reject", methods=["POST"])
def reject_plan(pid):
    require_auth(CIH)
    plan = get_or_404(db.sampling_plans, pid, "SamplingPlan")
    if plan["status"] != "PENDING_APPROVAL":
        raise_error(ERR_PLAN_INVALID_STATE, "reject requires PENDING_APPROVAL")
    plan["status"] = "DRAFT"
    touch(plan)
    return success_object(plan_out(plan), 200)


@bp.route("/ih/sampling-plans/<pid>/complete-field", methods=["POST"])
def complete_field(pid):
    require_auth(IH)
    plan = get_or_404(db.sampling_plans, pid, "SamplingPlan")
    if plan["status"] != "APPROVED":
        raise_error(ERR_PLAN_INVALID_STATE, "complete-field requires APPROVED")
    if plan["active_sample_count"] < plan["required_sample_count"]:
        raise_error(ERR_INSUFFICIENT_VALID_SAMPLES,
                    "active_sample_count below required_sample_count")
    plan["status"] = "FIELD_COMPLETE"
    touch(plan)
    return success_object(plan_out(plan), 200)
