"""ImpactAssessment routes: price, reprice, accept, waive, dispute."""
from flask import Blueprint, request

import calc
from authz import ALL_ROLES, OWNER_REP, PROJECT_ENGINEER, PROJECT_MANAGER, require_roles
from db import store
from errors import (
    assessment_not_estimated,
    assessment_not_found,
    assessment_not_priced,
    contingency_exhausted,
    project_not_found,
    segregation_of_duties,
)
from respond import success
from serialize import ser_assessment
from services import apply_schedule_cascade, require_active
from store_ops import (
    json_body,
    paginate,
    req_int,
    sorted_by_creation,
    touch,
)

bp = Blueprint("impact_assessments", __name__)


def get_assessment_or_404(assessment_id):
    a = store.impact_assessments.get(assessment_id)
    if a is None:
        raise assessment_not_found()
    return a


def _recompute_available(project):
    project["contingency_available_cents"] = (
        project["initial_contingency_cents"]
        - project["contingency_reserved_cents"]
        - project["contingency_spent_cents"]
    )


@bp.route("/v1/projects/<projectId>/impact-assessments", methods=["GET"])
def list_project_assessments(projectId):
    require_roles(ALL_ROLES)
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    items = sorted_by_creation(
        [a for a in store.impact_assessments.values() if a["project_id"] == projectId]
    )
    page, pagination = paginate(items)
    return success([ser_assessment(a) for a in page], response_type="array", pagination=pagination)


@bp.route("/v1/impact-assessments", methods=["GET"])
def list_assessments():
    require_roles(ALL_ROLES)
    items = list(store.impact_assessments.values())
    project_id = request.args.get("project_id")
    if project_id:
        items = [a for a in items if a["project_id"] == project_id]
    rfi_id = request.args.get("rfi_id")
    if rfi_id:
        items = [a for a in items if a["rfi_id"] == rfi_id]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_assessment(a) for a in page], response_type="array", pagination=pagination)


@bp.route("/v1/impact-assessments/<assessmentId>", methods=["GET"])
def get_assessment(assessmentId):
    require_roles(ALL_ROLES)
    a = get_assessment_or_404(assessmentId)
    return success(ser_assessment(a))


@bp.route("/v1/impact-assessments/<assessmentId>/price", methods=["POST"])
def price_assessment(assessmentId):
    uid, role = require_roles([PROJECT_ENGINEER])
    a = get_assessment_or_404(assessmentId)
    project = store.projects.get(a["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if a["status"] != "ESTIMATED":
        raise assessment_not_estimated()
    data = json_body()
    sub_quote_cents = req_int(data, "sub_quote_cents", minimum=0)
    spent_before = project["contingency_spent_cents"]
    tier = calc.select_gc_tier(spent_before, project["gc_tier_threshold_cents"])
    final_delta = calc.impact_cost_delta_final(sub_quote_cents, tier)
    if project["contingency_available_cents"] < final_delta:
        raise contingency_exhausted()
    a["sub_quote_cents"] = sub_quote_cents
    a["gc_markup_tier"] = tier
    a["final_delta_cents"] = final_delta
    a["priced_by_user_id"] = uid
    a["price_cycle"] = 1
    a["status"] = "PRICED"
    project["contingency_reserved_cents"] += final_delta
    _recompute_available(project)
    touch(project)
    touch(a)
    return success(ser_assessment(a))


@bp.route("/v1/impact-assessments/<assessmentId>/reprice", methods=["POST"])
def reprice_assessment(assessmentId):
    uid, role = require_roles([PROJECT_ENGINEER])
    a = get_assessment_or_404(assessmentId)
    project = store.projects.get(a["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if a["status"] != "DISPUTED":
        raise assessment_not_priced("reprice requires DISPUTED")
    data = json_body()
    sub_quote_cents = req_int(data, "sub_quote_cents", minimum=0)
    spent_before = project["contingency_spent_cents"]
    tier = calc.select_gc_tier(spent_before, project["gc_tier_threshold_cents"])
    new_final = calc.impact_cost_delta_final(sub_quote_cents, tier)
    old_final = a["final_delta_cents"] or 0
    delta = new_final - old_final
    if delta > 0 and project["contingency_available_cents"] < delta:
        raise contingency_exhausted()
    a["sub_quote_cents"] = sub_quote_cents
    a["gc_markup_tier"] = tier
    a["final_delta_cents"] = new_final
    a["priced_by_user_id"] = uid
    a["price_cycle"] += 1
    a["status"] = "PRICED"
    project["contingency_reserved_cents"] += delta
    _recompute_available(project)
    touch(project)
    touch(a)
    return success(ser_assessment(a))


@bp.route("/v1/impact-assessments/<assessmentId>/accept", methods=["POST"])
def accept_assessment(assessmentId):
    uid, role = require_roles([PROJECT_MANAGER])
    a = get_assessment_or_404(assessmentId)
    project = store.projects.get(a["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if a["status"] != "PRICED":
        raise assessment_not_priced()
    if uid == a.get("priced_by_user_id"):
        raise segregation_of_duties()
    final_delta = a["final_delta_cents"] or 0
    project["contingency_reserved_cents"] -= final_delta
    project["contingency_spent_cents"] += final_delta
    _recompute_available(project)
    touch(project)
    a["decided_by_user_id"] = uid
    a["status"] = "ACCEPTED"
    # Schedule cascade
    rfi = store.rfis.get(a["rfi_id"])
    if rfi is not None and rfi.get("schedule_impact_flag"):
        apply_schedule_cascade(project, rfi)
    touch(a)
    return success(ser_assessment(a))


@bp.route("/v1/impact-assessments/<assessmentId>/waive", methods=["POST"])
def waive_assessment(assessmentId):
    uid, role = require_roles([PROJECT_MANAGER])
    a = get_assessment_or_404(assessmentId)
    project = store.projects.get(a["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if a["status"] != "PRICED":
        raise assessment_not_priced()
    final_delta = a["final_delta_cents"] or 0
    project["contingency_reserved_cents"] -= final_delta
    _recompute_available(project)
    touch(project)
    a["decided_by_user_id"] = uid
    a["status"] = "WAIVED"
    touch(a)
    return success(ser_assessment(a))


@bp.route("/v1/impact-assessments/<assessmentId>/dispute", methods=["POST"])
def dispute_assessment(assessmentId):
    uid, role = require_roles([OWNER_REP])
    a = get_assessment_or_404(assessmentId)
    project = store.projects.get(a["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if a["status"] != "PRICED":
        raise assessment_not_priced()
    a["decided_by_user_id"] = uid
    a["status"] = "DISPUTED"
    touch(a)
    return success(ser_assessment(a))
