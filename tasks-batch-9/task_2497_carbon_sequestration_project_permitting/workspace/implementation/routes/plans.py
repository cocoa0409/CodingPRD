"""Monitoring, reporting and verification plan endpoints (PRD 3.7)."""

from decimal import Decimal as D

from flask import Blueprint

import db
import enums
import middleware as mw
import response
from errors import ApiError
from services import calc, derive, lookup, serialize

bp = Blueprint("plans", __name__)

ADMIN = "ProgramAdmin"
DEV = "ProjectDeveloper"
REVIEWER = "RegulatoryReviewer"
VERIFIER = "IndependentVerifier"

EDITABLE_PLAN_STATUSES = ("DRAFT", "REVISION_REQUESTED")


@bp.post("/ccs/monitoring-plans")
@mw.require(DEV)
def create_plan():
    payload = mw.body()
    project_id = mw.req_str(payload, "project_id")
    plan_label = mw.req_str(payload, "plan_label")

    project = lookup.project(project_id)
    derive.require_not_frozen(project)

    row = db.base_fields()
    row.update(
        {
            "project_id": project["id"],
            "plan_label": plan_label,
            "status": "DRAFT",
            "technical_review_complete": False,
            "public_comment_complete": False,
            "subsurface_subscore": D("0.0000"),
            "surface_subscore": D("0.0000"),
            "atmospheric_subscore": D("0.0000"),
            "coverage_score": D("0.00"),
            "condition_count": 0,
            "approved_by_user_id": None,
            "revision_round_count": 0,
        }
    )
    db.monitoring_plans[row["id"]] = row
    return response.object_response(serialize.plan(row), 201)


@bp.get("/ccs/monitoring-plans/<plan_id>")
@mw.require(ADMIN, DEV, REVIEWER, VERIFIER)
def get_plan(plan_id):
    return response.object_response(serialize.plan(lookup.plan(plan_id)))


# --------------------------------------------------------------------------- #
# Methods
# --------------------------------------------------------------------------- #


@bp.post("/ccs/monitoring-plans/<plan_id>/methods")
@mw.require(DEV)
def add_method(plan_id):
    payload = mw.body()
    domain = mw.req_enum(payload, "domain", enums.METHOD_DOMAIN)
    technique = mw.req_str(payload, "technique")
    detection_threshold = mw.req_num(payload, "detection_threshold_tpy", gt=0)
    frequency = mw.req_int(payload, "frequency_per_year", ge=1)
    spatial_coverage = mw.req_num(payload, "spatial_coverage_pct", gt=0, le=100)

    plan = lookup.plan(plan_id)
    project = db.project_of_plan(plan)
    derive.require_not_frozen(project)

    if plan["status"] not in EDITABLE_PLAN_STATUSES:
        raise ApiError(
            "ERR_INVALID_PLAN_STATE",
            "methods may only be added to a DRAFT or REVISION_REQUESTED plan",
        )

    row = db.base_fields()
    row.update(
        {
            "monitoring_plan_id": plan["id"],
            "domain": domain,
            "technique": technique,
            "detection_threshold_tpy": detection_threshold,
            "frequency_per_year": frequency,
            "spatial_coverage_pct": spatial_coverage,
            "method_score": D("0.0000"),
            "status": "ACTIVE",
        }
    )
    row["method_score"] = calc.method_score(row)
    db.monitoring_methods[row["id"]] = row

    derive.refresh_plan(plan)
    db.touch(plan)

    return response.object_response(serialize.method(row), 201)


@bp.get("/ccs/monitoring-plans/<plan_id>/methods")
@mw.require(ADMIN, DEV, REVIEWER, VERIFIER)
def list_methods(plan_id):
    domain = mw.query_enum("domain", enums.METHOD_DOMAIN)
    status = mw.query_enum("status", enums.METHOD_STATUS)
    plan = lookup.plan(plan_id)
    rows = db.methods_of(plan["id"])
    if domain is not None:
        rows = [r for r in rows if r["domain"] == domain]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = mw.paginate(rows)
    return response.list_response([serialize.method(r) for r in page], limit, offset, total)


@bp.post("/ccs/monitoring-methods/<method_id>/retire")
@mw.require(DEV)
def retire_method(method_id):
    payload = mw.body()
    mw.req_str(payload, "retirement_reason")

    method = lookup.method(method_id)
    plan = db.monitoring_plans.get(method["monitoring_plan_id"])
    project = db.project_of_method(method)
    derive.require_not_frozen(project)

    if plan is None or plan["status"] not in EDITABLE_PLAN_STATUSES:
        raise ApiError(
            "ERR_INVALID_PLAN_STATE",
            "methods may only be retired from a DRAFT or REVISION_REQUESTED plan",
        )

    method["status"] = "RETIRED"
    db.touch(method)

    derive.refresh_plan(plan)
    db.touch(plan)

    return response.object_response(serialize.method(method))


# --------------------------------------------------------------------------- #
# Two-track review
# --------------------------------------------------------------------------- #


@bp.post("/ccs/monitoring-plans/<plan_id>/submit")
@mw.require(DEV)
def submit_plan(plan_id):
    payload = mw.body()
    mw.opt_str(payload, "submission_note")

    plan = lookup.plan(plan_id)
    project = db.project_of_plan(plan)
    derive.require_not_frozen(project)

    if plan["status"] not in EDITABLE_PLAN_STATUSES:
        raise ApiError(
            "ERR_INVALID_PLAN_STATE", "a plan may only be submitted from DRAFT or REVISION_REQUESTED"
        )
    if not any(m["status"] == "ACTIVE" for m in db.methods_of(plan["id"])):
        raise ApiError("ERR_INVALID_PLAN_STATE", "the plan holds no ACTIVE monitoring method")

    plan["technical_review_complete"] = False
    plan["public_comment_complete"] = False
    plan["revision_round_count"] = plan["revision_round_count"] + 1
    derive.refresh_plan(plan)
    plan["status"] = "SUBMITTED"
    db.touch(plan)
    return response.object_response(serialize.plan(plan))


@bp.post("/ccs/monitoring-plans/<plan_id>/review")
@mw.require(REVIEWER)
def review_plan(plan_id):
    payload = mw.body()
    decision = mw.req_enum(payload, "decision", enums.PLAN_REVIEW_DECISION)
    condition_count = mw.opt_int(payload, "condition_count", ge=0)
    mw.opt_str(payload, "review_note")

    plan = lookup.plan(plan_id)
    project = db.project_of_plan(plan)
    derive.require_not_frozen(project)

    if decision in ("COMPLETE_TECHNICAL_REVIEW", "COMPLETE_PUBLIC_COMMENT"):
        track = (
            "technical_review_complete"
            if decision == "COMPLETE_TECHNICAL_REVIEW"
            else "public_comment_complete"
        )
        other = (
            "public_comment_complete"
            if decision == "COMPLETE_TECHNICAL_REVIEW"
            else "technical_review_complete"
        )
        if plan["status"] != "SUBMITTED" or plan[track]:
            raise ApiError(
                "ERR_INVALID_PLAN_STATE", "this review track is not open on a SUBMITTED plan"
            )
        plan[track] = True
        if plan[other]:
            plan["status"] = "REVIEW_COMPLETE"
        db.touch(plan)
        return response.object_response(serialize.plan(plan))

    if plan["status"] != "REVIEW_COMPLETE":
        raise ApiError(
            "ERR_INVALID_PLAN_STATE", "a ruling is only admissible from REVIEW_COMPLETE"
        )

    if decision == "REQUEST_REVISION":
        plan["technical_review_complete"] = False
        plan["public_comment_complete"] = False
        plan["status"] = "REVISION_REQUESTED"
        db.touch(plan)
        return response.object_response(serialize.plan(plan))

    if decision == "REJECT":
        plan["status"] = "REJECTED"
        db.touch(plan)
        return response.object_response(serialize.plan(plan))

    # APPROVE — two quality gates, in order.
    if (
        plan["subsurface_subscore"] <= 0
        or plan["surface_subscore"] <= 0
        or plan["atmospheric_subscore"] <= 0
    ):
        raise ApiError(
            "ERR_MRV_DOMAIN_COVERAGE_MISSING",
            "each of the three monitoring domains must carry a positive subscore",
        )
    if plan["coverage_score"] < calc.MRV_MINIMUM_COVERAGE:
        raise ApiError(
            "ERR_MRV_COVERAGE_BELOW_MINIMUM", "the plan's coverage score is below 70.00"
        )

    if plan["coverage_score"] >= calc.MRV_FULL_APPROVAL_THRESHOLD:
        plan["condition_count"] = 0
        plan["status"] = "APPROVED"
        # PRD 3.7: an unconditioned approval carries no cost uplift and leaves the
        # project's effective cost untouched — the uplift persists for as long as
        # any plan of the project still holds APPROVED_WITH_CONDITIONS.
    else:
        plan["condition_count"] = condition_count if condition_count is not None else 0
        plan["status"] = "APPROVED_WITH_CONDITIONS"
        project["effective_annual_monitoring_cost_usd"] = calc.q2(
            D(project["annual_monitoring_cost_usd"]) * D("1.15")
        )

    plan["approved_by_user_id"] = mw.caller_id()
    db.touch(plan)

    derive.recompute_required_assurance(project)
    db.touch(project)

    return response.object_response(serialize.plan(plan))
