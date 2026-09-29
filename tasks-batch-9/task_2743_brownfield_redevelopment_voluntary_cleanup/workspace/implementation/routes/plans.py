"""Remedial action plans: filing, editing, the review fork and the join."""

from flask import Blueprint

import db
import response
import validation as V
from errors import ApiError
from middleware import actor_id, endpoint
from routes.common import apply_filter, fetch
from services import calc, derive
from services.constants import (
    COST_CATEGORIES,
    ENROLLMENT_TERMINAL,
    MEDIA,
    PLAN_STATUS,
    TECHNICAL_DECISIONS,
)
from services.serialize import dump_plan

bp = Blueprint("plans", __name__)

READ_ROLES = ["EnvironmentalConsultant", "StateAgencyReviewer", "Redeveloper",
              "Insurer", "Lender"]


def _cost_lines(body, required=True):
    items = V.array_field(body, "cost_lines", required, min_len=1, max_len=12,
                          default=None)
    if items is None:
        return None
    lines = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            V.fail("Element %d of cost_lines must be an object." % index)
        category = V.enum_field(item, "cost_category", COST_CATEGORIES, True)
        media = V.enum_field(item, "media", MEDIA, True)
        quantity = V.number_field(item, "quantity", True, gt=0)
        unit_cost = V.int_field(item, "unit_cost_cents", True, minimum=1)
        lines.append({"cost_category": category, "media": media,
                      "quantity": quantity, "unit_cost_cents": unit_cost})
    return lines


def _pin_goals(plan):
    pins = []
    for goal in derive.goals_of_site(plan["site_id"]):
        pins.append({"cleanup_goal_id": goal["id"],
                     "pinned_version": goal["version"]})
    plan["pinned_cleanup_goal_versions"] = pins
    return pins


@bp.post("/remedial-action-plans")
@endpoint(["EnvironmentalConsultant"])
def create_plan():
    body = V.json_body()
    enrollment_id = V.id_field(body, "vcp_enrollment_id", True)
    site_id = V.id_field(body, "site_id", True)
    narrative = V.string_field(body, "remedy_narrative", True, 1, 600)
    basis_phase_id = V.id_field(body, "basis_assessment_phase_id", True)
    years = V.int_field(body, "years_to_construction_start", True, 0, 10)
    cost_lines = _cost_lines(body, True)
    expected_version = V.int_field(body, "expected_vcp_enrollment_version", True,
                                   minimum=0)

    site = fetch("sites", site_id)
    enrollment = fetch("vcp_enrollments", enrollment_id)
    fetch("assessment_phases", basis_phase_id)
    derive.assert_not_frozen(site)
    if enrollment["status"] in ENROLLMENT_TERMINAL:
        raise ApiError("ERR_INVALID_ENROLLMENT_STATE",
                       "A plan may not be filed against a terminal enrollment.")
    if int(enrollment["version"]) != int(expected_version):
        raise ApiError("ERR_STALE_ENROLLMENT_VERSION",
                       "Expected enrollment version %s but found %s."
                       % (expected_version, enrollment["version"]))
    if enrollment["site_id"] != site["id"]:
        raise ApiError("ERR_PLAN_SITE_MISMATCH",
                       "The plan's site_id must equal the enrollment's site_id.")

    row = db.insert("remedial_action_plans", {
        "vcp_enrollment_id": enrollment["id"],
        "site_id": site["id"],
        "remedy_narrative": narrative,
        "basis_assessment_phase_id": basis_phase_id,
        "years_to_construction_start": years,
        "cost_lines": cost_lines,
        "direct_cost_cents": 0,
        "escalation_cents": 0,
        "contingency_pct": 0,
        "contingency_cents": 0,
        "oversight_cents": 0,
        "total_estimate_cents": 0,
        "total_funding_need_cents": 0,
        "status": "DRAFT",
        "technical_review_state": "NOT_STARTED",
        "public_comment_state": "NOT_STARTED",
        "public_comment_count": 0,
        "revision_round": 0,
        "pinned_cleanup_goal_versions": [],
        "approved_by_user_id": None,
        "approved_at": None,
    })
    derive.recompute_plan_costs(row)
    db.touch(enrollment)
    return response.created(dump_plan(row))


@bp.get("/remedial-action-plans")
@endpoint(READ_ROLES)
def list_plans():
    rows = db.ordered(db.all_rows("remedial_action_plans"))
    rows = apply_filter(rows, "vcp_enrollment_id",
                        V.query_string("vcp_enrollment_id"))
    rows = apply_filter(rows, "site_id", V.query_string("site_id"))
    rows = apply_filter(rows, "status", V.query_enum("status", PLAN_STATUS))
    return response.list_response(rows, dump_plan)


@bp.get("/remedial-action-plans/<plan_id>")
@endpoint(READ_ROLES)
def get_plan(plan_id):
    return response.object_response(
        dump_plan(fetch("remedial_action_plans", plan_id)))


@bp.patch("/remedial-action-plans/<plan_id>")
@endpoint(["EnvironmentalConsultant"])
def patch_plan(plan_id):
    body = V.json_body()
    narrative = V.string_field(body, "remedy_narrative", False, 1, 600)
    basis_phase_id = V.id_field(body, "basis_assessment_phase_id", False)
    years = V.int_field(body, "years_to_construction_start", False, 0, 10)
    cost_lines = _cost_lines(body, False)

    plan = fetch("remedial_action_plans", plan_id)
    if basis_phase_id is not None:
        fetch("assessment_phases", basis_phase_id)
    site = db.get("sites", plan["site_id"])
    if site is not None:
        derive.assert_not_frozen(site)
    if plan["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_PLAN_NOT_EDITABLE",
                       "Only a DRAFT or REVISION_REQUESTED plan may be edited.")

    if narrative is not None:
        plan["remedy_narrative"] = narrative
    if basis_phase_id is not None:
        plan["basis_assessment_phase_id"] = basis_phase_id
    if years is not None:
        plan["years_to_construction_start"] = years
    if cost_lines is not None:
        plan["cost_lines"] = cost_lines
    derive.recompute_plan_costs(plan)
    db.touch(plan)
    return response.object_response(dump_plan(plan))


@bp.post("/remedial-action-plans/<plan_id>/submit")
@endpoint(["EnvironmentalConsultant"])
def submit_plan(plan_id):
    plan = fetch("remedial_action_plans", plan_id)
    site = db.get("sites", plan["site_id"])
    enrollment = db.get("vcp_enrollments", plan["vcp_enrollment_id"])
    if site is not None:
        derive.assert_not_frozen(site)
    if plan["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_PLAN_STATE",
                       "Only a DRAFT or REVISION_REQUESTED plan may be submitted.")
    if enrollment is None or enrollment["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_ENROLLMENT_STATE",
                       "The parent enrollment must be ENROLLED.")
    if int(plan["revision_round"]) > 2:
        raise ApiError("ERR_PLAN_REVISION_LIMIT",
                       "The plan has exhausted its revision rounds.")

    phase = db.get("assessment_phases", plan["basis_assessment_phase_id"])
    if (phase is None
            or phase["site_id"] != plan["site_id"]
            or phase["phase_type"] not in ("PHASE_II", "SUPPLEMENTAL")
            or phase["status"] != "APPROVED"
            or not phase["delineation_complete"]):
        raise ApiError("ERR_BASIS_PHASE_INELIGIBLE",
                       "The basis phase must be an APPROVED, fully delineated "
                       "PHASE_II or SUPPLEMENTAL phase on this parcel.")
    if not derive.goals_of_site(plan["site_id"]):
        raise ApiError("ERR_NO_CLEANUP_GOALS",
                       "At least one cleanup goal must exist on the parcel.")

    plan["technical_review_state"] = "NOT_STARTED"
    plan["public_comment_state"] = "OPEN"
    _pin_goals(plan)
    derive.recompute_plan_costs(plan)
    plan["status"] = "SUBMITTED"
    plan["status"] = "UNDER_TECHNICAL_REVIEW"
    db.touch(plan)
    return response.object_response(dump_plan(plan))


@bp.post("/remedial-action-plans/<plan_id>/technical-review")
@endpoint(["StateAgencyReviewer"])
def technical_review(plan_id):
    body = V.json_body()
    decision = V.enum_field(body, "decision", TECHNICAL_DECISIONS, True)
    V.string_field(body, "review_comment", False, 1, 2000)

    plan = fetch("remedial_action_plans", plan_id)
    site = db.get("sites", plan["site_id"])
    if decision == "PASS" and site is not None:
        derive.assert_not_frozen(site)
    if plan["status"] != "UNDER_TECHNICAL_REVIEW":
        raise ApiError("ERR_INVALID_PLAN_STATE",
                       "Only a plan UNDER_TECHNICAL_REVIEW may be decided.")

    if decision == "PASS":
        for goal in derive.goals_of_site(plan["site_id"]):
            if goal["basis"] != "RESTRICTED":
                continue
            if calc.D(goal["goal_ugl"]) < calc.D(goal["screening_level_ugl"]):
                raise ApiError(
                    "ERR_INVALID_PLAN_STATE",
                    "Restricted cleanup goal %s is stricter than its screening "
                    "level; the risk basis is incoherent." % goal["id"])
        plan["technical_review_state"] = "PASSED"
        plan["status"] = "PUBLIC_COMMENT"
        db.touch(plan)
        return response.object_response(dump_plan(plan))

    if int(plan["revision_round"]) > 1:
        raise ApiError("ERR_PLAN_REVISION_LIMIT",
                       "A third revision request is not permitted.")
    plan["status"] = "REVISION_REQUESTED"
    plan["revision_round"] = int(plan["revision_round"]) + 1
    plan["public_comment_state"] = "NOT_STARTED"
    plan["public_comment_count"] = 0
    plan["pinned_cleanup_goal_versions"] = []
    db.touch(plan)
    for policy in db.ordered(db.all_rows("cost_cap_policies")):
        if (policy["remedial_action_plan_id"] == plan["id"]
                and policy["status"] == "QUOTED"):
            policy["status"] = "CANCELLED"
            db.touch(policy)
    return response.object_response(dump_plan(plan))


@bp.post("/remedial-action-plans/<plan_id>/public-comment-close")
@endpoint(["StateAgencyReviewer"])
def public_comment_close(plan_id):
    body = V.json_body()
    count = V.int_field(body, "public_comment_count", True, minimum=0)

    plan = fetch("remedial_action_plans", plan_id)
    if plan["status"] not in ("UNDER_TECHNICAL_REVIEW", "PUBLIC_COMMENT"):
        raise ApiError("ERR_INVALID_PLAN_STATE",
                       "The plan is not in a public-participation state.")
    if (plan["technical_review_state"] != "PASSED"
            or plan["public_comment_state"] != "OPEN"):
        raise ApiError("ERR_JOIN_NOT_SATISFIED",
                       "The technical branch must have PASSED and the comment "
                       "period must be OPEN.")

    plan["public_comment_count"] = count
    plan["public_comment_state"] = "CLOSED"
    db.touch(plan)
    return response.object_response(dump_plan(plan))


@bp.post("/remedial-action-plans/<plan_id>/approve")
@endpoint(["StateAgencyReviewer"])
def approve_plan(plan_id):
    plan = fetch("remedial_action_plans", plan_id)
    site = db.get("sites", plan["site_id"])
    if site is not None:
        derive.assert_not_frozen(site)
    if plan["status"] != "PUBLIC_COMMENT":
        raise ApiError("ERR_INVALID_PLAN_STATE",
                       "Only a plan in PUBLIC_COMMENT may be approved.")
    if (plan["technical_review_state"] != "PASSED"
            or plan["public_comment_state"] != "CLOSED"):
        raise ApiError("ERR_JOIN_NOT_SATISFIED",
                       "Both review branches must be complete before approval.")

    controls = derive.controls_of_plan(plan["id"])
    for goal in derive.goals_of_site(plan["site_id"]):
        if goal["basis"] != "RESTRICTED":
            continue
        wanted = goal.get("control_credit_type")
        if not any(c["control_type"] == wanted
                   and c["status"] in ("PROPOSED", "APPROVED", "OPERATING")
                   for c in controls):
            raise ApiError("ERR_CREDITED_CONTROL_MISSING",
                           "The remedy does not build the control credited by "
                           "cleanup goal %s." % goal["id"])
    for pin in plan["pinned_cleanup_goal_versions"]:
        goal = db.get("cleanup_goals", pin["cleanup_goal_id"])
        if goal is None or int(goal["version"]) != int(pin["pinned_version"]):
            raise ApiError("ERR_PINNED_GOAL_VERSION_STALE",
                           "Cleanup goal %s has changed since the plan was "
                           "submitted." % pin["cleanup_goal_id"])

    plan["status"] = "APPROVED"
    plan["approved_by_user_id"] = actor_id()
    plan["approved_at"] = db.now_ts()
    db.touch(plan)

    for control in controls:
        if control["status"] != "PROPOSED":
            continue
        control["status"] = "APPROVED"
        control["next_certification_due_on"] = db.add_days(
            db.parse_date(control["coverage_from"]),
            int(control["inspection_interval_days"])).isoformat()
        db.touch(control)

    enrollment = db.get("vcp_enrollments", plan["vcp_enrollment_id"])
    if enrollment is not None and enrollment["status"] == "ENROLLED":
        enrollment["status"] = "REMEDY_APPROVED"
        db.touch(enrollment)

    for sibling in derive.plans_of_enrollment(plan["vcp_enrollment_id"]):
        if sibling["id"] == plan["id"]:
            continue
        if sibling["status"] in ("DRAFT", "REVISION_REQUESTED"):
            sibling["status"] = "WITHDRAWN"
            db.touch(sibling)

    if site is not None:
        derive.rederive_funding(site)
    return response.object_response(dump_plan(plan))
