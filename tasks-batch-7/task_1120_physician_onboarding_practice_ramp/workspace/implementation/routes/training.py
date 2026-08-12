"""Training plan and module endpoints (PRD 3.4)."""

from flask import Blueprint, request

import domain as D
from db import store, new_record, bump
from errors import (
    ApiError, ERR_VALIDATION, ERR_TRAINING_PLAN_NOT_FOUND,
    ERR_TRAINING_MODULE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_MODULE_NOT_SCHEDULED, ERR_TEMPLATES_INSUFFICIENT,
    ERR_PLAN_NOT_AWAITING_SIGNOFF,
)
from middleware import get_context, require_role, forbid
from response import success_object, paginate

bp = Blueprint("training", __name__)


def _get_plan(pid):
    plan = store.training_plans.get(pid)
    if plan is None:
        raise ApiError(ERR_TRAINING_PLAN_NOT_FOUND, 404, "TrainingPlan not found")
    return plan


def _get_module(mid):
    module = store.training_modules.get(mid)
    if module is None:
        raise ApiError(ERR_TRAINING_MODULE_NOT_FOUND, 404, "TrainingModule not found")
    return module


def _case_for_plan(plan):
    return store.cases.get(plan["onboarding_case_id"])


def _bubble_plan_progress(plan):
    """IN_PROGRESS -> AWAITING_SIGNOFF when every required module is COMPLETED."""
    if plan["status"] != "IN_PROGRESS":
        return
    modules = D.modules_of_plan(plan["id"])
    if all(m["status"] == "COMPLETED" for m in modules if m["required"]):
        plan["status"] = "AWAITING_SIGNOFF"
        bump(plan)
        case = _case_for_plan(plan)
        if case is not None:
            bump(case)


@bp.route("/onboarding/training-plans/<pid>", methods=["GET"])
def get_plan(pid):
    get_context()
    return success_object(D.serialize_plan(_get_plan(pid)))


@bp.route("/onboarding/training-plans", methods=["GET"])
def list_plans():
    get_context()
    case_id = request.args.get("onboarding_case_id")
    status = request.args.get("status")
    records = sorted(store.training_plans.values(), key=lambda r: r["_seq"])
    if case_id is not None:
        records = [r for r in records if r["onboarding_case_id"] == case_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate([D.serialize_plan(r) for r in records], request.args)


@bp.route("/onboarding/training-plans/<pid>/signoff", methods=["POST"])
def signoff_plan(pid):
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    plan = _get_plan(pid)
    if plan["status"] != "AWAITING_SIGNOFF":
        raise ApiError(ERR_PLAN_NOT_AWAITING_SIGNOFF, 409,
                       "Plan must be AWAITING_SIGNOFF for signoff")
    plan["status"] = "COMPLETE"
    bump(plan)
    case = _case_for_plan(plan)
    if case is not None:
        D.recompute_training_status(case)
        D.recompute_posture(case)
        bump(case)
    return success_object(D.serialize_plan(plan))


@bp.route("/onboarding/training-modules", methods=["POST"])
def create_module():
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    body = D.get_body()
    plan_id = D.req_str(body, "training_plan_id")
    module_code = D.req_enum(body, "module_code", D.MODULE_CODES)
    required = D.opt_bool(body, "required", default=False)
    plan = store.training_plans.get(plan_id)
    if plan is None:
        raise ApiError(ERR_TRAINING_PLAN_NOT_FOUND, 404, "TrainingPlan not found")
    for m in D.modules_of_plan(plan_id):
        if m["module_code"] == module_code:
            raise ApiError(ERR_VALIDATION, 400,
                           "module_code must be unique within a plan")
    rec = new_record()
    rec.update({
        "training_plan_id": plan_id,
        "module_code": module_code,
        "required": required,
        "scheduled_on": None,
        "score": None,
        "templates_built_count": None,
        "status": "NOT_STARTED",
    })
    store.training_modules[rec["id"]] = rec
    return success_object(D.serialize_module(rec), status=201)


@bp.route("/onboarding/training-modules/<mid>", methods=["GET"])
def get_module(mid):
    get_context()
    return success_object(D.serialize_module(_get_module(mid)))


@bp.route("/onboarding/training-modules", methods=["GET"])
def list_modules():
    get_context()
    plan_id = request.args.get("training_plan_id")
    status = request.args.get("status")
    module_code = request.args.get("module_code")
    records = sorted(store.training_modules.values(),
                     key=lambda r: (r["module_code"], r["_seq"]))
    if plan_id is not None:
        records = [r for r in records if r["training_plan_id"] == plan_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if module_code is not None:
        records = [r for r in records if r["module_code"] == module_code]
    return paginate([D.serialize_module(r) for r in records], request.args)


@bp.route("/onboarding/training-modules/<mid>/schedule", methods=["POST"])
def schedule_module(mid):
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    module = _get_module(mid)
    body = D.get_body()
    scheduled_on = D.opt_str(body, "scheduled_on")
    if scheduled_on is not None:
        D.parse_date(scheduled_on, "scheduled_on")
    if module["status"] not in ("NOT_STARTED", "FAILED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a NOT_STARTED or FAILED module can be scheduled")
    module["status"] = "SCHEDULED"
    module["scheduled_on"] = scheduled_on if scheduled_on is not None \
        else D.clock_date().isoformat()
    bump(module)
    plan = store.training_plans.get(module["training_plan_id"])
    case = _case_for_plan(plan) if plan else None
    if plan is not None and plan["status"] == "PLANNED":
        plan["status"] = "IN_PROGRESS"
        bump(plan)
    if case is not None:
        D.recompute_training_status(case)
        bump(case)
    return success_object(D.serialize_module(module))


@bp.route("/onboarding/training-modules/<mid>/complete", methods=["POST"])
def complete_module(mid):
    uid, role = get_context()
    require_role(role, ["Physician"])
    module = _get_module(mid)
    plan = store.training_plans.get(module["training_plan_id"])
    case = _case_for_plan(plan) if plan else None
    if case is None or case["physician_id"] != uid:
        forbid("A Physician may complete only modules of their own case's plan")
    body = D.get_body()
    score = D.req_int(body, "score")
    if not (0 <= score <= 100):
        raise ApiError(ERR_VALIDATION, 400, "score must be between 0 and 100")
    templates_built_count = D.opt_int(body, "templates_built_count")
    if templates_built_count is not None and templates_built_count < 0:
        raise ApiError(ERR_VALIDATION, 400, "templates_built_count must not be negative")
    if module["status"] != "SCHEDULED":
        raise ApiError(ERR_MODULE_NOT_SCHEDULED, 409,
                       "Module must be SCHEDULED before completion")
    module["score"] = score
    if score >= D.PASS_SCORE:
        if module["module_code"] == "NOTE_TEMPLATES":
            built = templates_built_count if templates_built_count is not None else 0
            if plan is not None and built < plan["templates_required"]:
                raise ApiError(ERR_TEMPLATES_INSUFFICIENT, 422,
                               "templates_built_count is below the plan's templates_required")
        module["status"] = "COMPLETED"
        if templates_built_count is not None:
            module["templates_built_count"] = templates_built_count
    else:
        module["status"] = "FAILED"
    bump(module)
    if case is not None:
        bump(case)
    if module["status"] == "COMPLETED" and plan is not None:
        _bubble_plan_progress(plan)
    return success_object(D.serialize_module(module))
