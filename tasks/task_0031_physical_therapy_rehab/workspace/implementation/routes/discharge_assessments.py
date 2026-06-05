"""DischargeAssessment routes (scaffold §1.5; PRD §3.8)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_GOALS_INCONSISTENT, ERR_INVALID_STATE
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services import calculations as calc
from services.validation import (
    lookup_or_404,
    require_date,
    require_fields,
    require_int,
    require_string,
)


bp = Blueprint("discharge_assessments", __name__)


@bp.post("/rehab/discharge-assessments")
def create_assessment():
    require_auth(["Therapist"])()
    body = get_json_body()
    require_fields(
        body,
        [
            "plan_of_care_id",
            "assessing_therapist_id",
            "final_functional_score",
            "goals_met_count",
            "total_goals_count",
            "assessed_on",
        ],
    )
    poc_id = require_string(body["plan_of_care_id"], "plan_of_care_id")
    therapist_id = require_string(body["assessing_therapist_id"], "assessing_therapist_id")
    final_score = require_int(
        body["final_functional_score"], "final_functional_score", min_value=0, max_value=100
    )
    goals_met = require_int(
        body["goals_met_count"], "goals_met_count", min_value=0, max_value=20
    )
    total_goals = require_int(
        body["total_goals_count"], "total_goals_count", min_value=1, max_value=20
    )
    assessed_on = require_date(body["assessed_on"], "assessed_on")

    poc = lookup_or_404(db.plans_of_care, poc_id, "PlanOfCare")
    lookup_or_404(db.therapists, therapist_id, "Therapist")

    # State precondition (priority 300): POC must be ACTIVE or RECERT_DUE.
    if poc["status"] not in {"ACTIVE", "RECERT_DUE"}:
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"DischargeAssessment requires PlanOfCare ACTIVE or RECERT_DUE; current={poc['status']}",
        )

    # priority 450
    if goals_met > total_goals:
        raise APIError(
            ERR_GOALS_INCONSISTENT,
            422,
            "total_goals_count must be >= goals_met_count",
        )

    with db.mutation_lock:
        assessment = {
            "plan_of_care_id": poc_id,
            "assessing_therapist_id": therapist_id,
            "final_functional_score": final_score,
            "goals_met_count": goals_met,
            "total_goals_count": total_goals,
            "discharge_outcome": calc.discharge_outcome(goals_met, total_goals),
            "assessed_on": assessed_on.isoformat(),
        }
        db.stamp_common(assessment)
        db.discharge_assessments[assessment["id"]] = assessment
        return ok_object(assessment, 201)


@bp.get("/rehab/discharge-assessments/<aid>")
def get_assessment(aid: str):
    require_auth(["PlatformAdmin", "Therapist", "CaseManager"])()
    a = lookup_or_404(db.discharge_assessments, aid, "DischargeAssessment")
    return ok_object(a, 200)


@bp.get("/rehab/discharge-assessments")
def list_assessments():
    require_auth(["PlatformAdmin", "Therapist", "CaseManager"])()
    limit, offset = paginate_params(request.args)
    items = list(db.discharge_assessments.values())
    for key in ("plan_of_care_id", "assessing_therapist_id"):
        if key in request.args:
            items = [a for a in items if a.get(key) == request.args.get(key)]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)
