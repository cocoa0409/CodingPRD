"""Donor medical / psychosocial evaluations, determinations and resubmissions."""

from flask import Blueprint, g

import calc
import domain
import serialize
from db import db, new_entity, now, touch
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from response import list_response, object_response
from routes.donors import find_donor
from validation import (
    get_body,
    opt_bool,
    pagination,
    q_enum,
    q_str,
    req_enum,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("evaluations", __name__)

RESUBMISSION_BLOCKED_STATUSES = ("EXCLUDED", "ADVOCATE_BLOCKED", "CHAIN_COMMITTED", "DONATED")

DIMENSION_STATUS = {"MEDICAL": "medical_status", "PSYCHOSOCIAL": "psychosocial_status"}
DIMENSION_POINTS = {
    "MEDICAL": "medical_risk_points",
    "PSYCHOSOCIAL": "psychosocial_risk_points",
}


def find_evaluation(evaluation_id):
    evaluation = db.evaluations.get(evaluation_id)
    if evaluation is None:
        raise ApiError(
            "ERR_EVALUATION_NOT_FOUND", "no DonorEvaluation with id %s" % evaluation_id
        )
    return evaluation


def read_findings(body, eval_domain):
    """Domain-shaped findings: the other domain's measurements are stored as null."""
    findings = {
        "bmi": None,
        "egfr_ml_min": None,
        "systolic_bp": None,
        "hba1c": None,
        "financial_hardship_score": None,
        "social_support_score": None,
        "coercion_flag": opt_bool(body, "coercion_flag", False),
        "unmanaged_substance_use": opt_bool(body, "unmanaged_substance_use", False),
        "decisional_capacity_ok": opt_bool(body, "decisional_capacity_ok", True),
    }
    if eval_domain == "MEDICAL":
        findings["bmi"] = req_num(body, "bmi")
        findings["egfr_ml_min"] = req_num(body, "egfr_ml_min")
        findings["systolic_bp"] = req_int(body, "systolic_bp")
        findings["hba1c"] = req_num(body, "hba1c")
    else:
        findings["financial_hardship_score"] = req_int(
            body, "financial_hardship_score", minimum=0, maximum=10
        )
        findings["social_support_score"] = req_int(
            body, "social_support_score", minimum=0, maximum=10
        )
    return findings


def screen(evaluation, donor):
    codes, hard_count, points = calc.donor_exclusion_screen(
        evaluation["domain"], evaluation, donor["age_years"]
    )
    evaluation["exclusion_codes"] = codes
    evaluation["hard_exclusion_count"] = hard_count
    evaluation["risk_points"] = points


@bp.post("/donor-evaluations")
def create_evaluation():
    authenticate(["EvaluationReviewer"])
    body = get_body()
    donor_candidate_id = req_str(body, "donor_candidate_id")
    eval_domain = req_enum(body, "domain", calc.EVAL_DOMAINS)
    findings = read_findings(body, eval_domain)

    donor = find_donor(donor_candidate_id)
    reviewer = g.staff

    # priority 10 -- role-type fitness of the authoring reviewer
    if reviewer is None or reviewer["staff_role"] != "EVALUATION_REVIEWER" or not reviewer["is_active"]:
        raise ApiError(
            "ERR_STAFF_ROLE_INVALID", "the reviewer must be an active EVALUATION_REVIEWER"
        )

    # priority 11 -- one person may not certify both halves of a donor's fitness
    other_domain = "PSYCHOSOCIAL" if eval_domain == "MEDICAL" else "MEDICAL"
    for existing in domain.evaluations_of_donor(donor):
        if existing["domain"] == other_domain and existing["reviewer_staff_id"] == reviewer["id"]:
            raise ApiError(
                "ERR_REVIEWER_SOD_CONFLICT",
                "this reviewer already authored the %s evaluation of this donor" % other_domain,
            )

    # priority 15 -- single-program containment
    domain.require_same_program([donor["program_id"], reviewer["program_id"]])

    # priority 17 -- at most one open evaluation per domain
    for existing in domain.evaluations_of_donor(donor):
        if existing["domain"] == eval_domain and existing["status"] == "SUBMITTED":
            raise ApiError(
                "ERR_DUPLICATE_OPEN_EVALUATION",
                "this donor already has a SUBMITTED %s evaluation" % eval_domain,
            )

    row = new_entity(
        "DonorEvaluation",
        {
            "donor_candidate_id": donor["id"],
            "reviewer_staff_id": reviewer["id"],
            "domain": eval_domain,
            "status": "SUBMITTED",
            "exclusion_codes": [],
            "hard_exclusion_count": 0,
            "risk_points": 0,
            "submission_count": 1,
            "determined_at": None,
        },
    )
    row.update(findings)
    screen(row, donor)
    db.evaluations[row["id"]] = row

    domain.refresh_donor_status(donor)
    return object_response(serialize.donor_evaluation(row), 201)


@bp.get("/donor-evaluations")
def list_evaluations():
    authenticate(ALL_ROLES)
    donor_candidate_id = q_str("donor_candidate_id")
    reviewer_staff_id = q_str("reviewer_staff_id")
    eval_domain = q_enum("domain", calc.EVAL_DOMAINS)
    status = q_enum("status", calc.EVAL_STATUSES)
    limit, offset = pagination()

    rows = list(db.evaluations.values())
    if donor_candidate_id is not None:
        rows = [r for r in rows if r["donor_candidate_id"] == donor_candidate_id]
    if reviewer_staff_id is not None:
        rows = [r for r in rows if r["reviewer_staff_id"] == reviewer_staff_id]
    if eval_domain is not None:
        rows = [r for r in rows if r["domain"] == eval_domain]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serialize.donor_evaluation(r) for r in page], limit, offset, total)


@bp.get("/donor-evaluations/<evaluation_id>")
def get_evaluation(evaluation_id):
    authenticate(ALL_ROLES)
    evaluation = find_evaluation(evaluation_id)
    return object_response(serialize.donor_evaluation(evaluation))


@bp.post("/donor-evaluations/<evaluation_id>/determination")
def determine_evaluation(evaluation_id):
    authenticate(["EvaluationReviewer"])
    evaluation = find_evaluation(evaluation_id)

    body = get_body()
    outcome = req_enum(body, "outcome", calc.DETERMINATION_OUTCOMES)

    # priority 7
    if evaluation["reviewer_staff_id"] != g.user_id:
        raise ApiError(
            "ERR_NOT_ASSIGNED_REVIEWER", "the caller is not this evaluation's assigned reviewer"
        )

    # priority 8 -- a determination is only accepted while the evaluation is SUBMITTED
    if evaluation["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "an evaluation in %s accepts no determination" % evaluation["status"],
        )

    donor = db.donors[evaluation["donor_candidate_id"]]
    eval_domain = evaluation["domain"]
    status_field = DIMENSION_STATUS[eval_domain]
    points_field = DIMENSION_POINTS[eval_domain]

    if (
        outcome == "DEFERRED"
        and donor[status_field] == "CLEARED"
        and donor["overall_status"] == "CHAIN_COMMITTED"
    ):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "a CHAIN_COMMITTED donor's cleared dimension may not be deferred",
        )

    # priority 12
    if outcome == "CLEARED" and evaluation["hard_exclusion_count"] > 0:
        raise ApiError(
            "ERR_HARD_EXCLUSION_PRESENT",
            "a hard exclusion must be resolved by resubmission, not overridden",
        )

    evaluation["status"] = outcome
    evaluation["determined_at"] = now()
    touch(evaluation)

    if outcome == "CLEARED":
        donor[status_field] = "CLEARED"
        donor[points_field] = evaluation["risk_points"]
        touch(donor)
        domain.refresh_donor_status(donor)
    elif outcome == "DEFERRED":
        donor[status_field] = "DEFERRED"
        donor["deferral_count"] = donor["deferral_count"] + 1
        touch(donor)
        domain.refresh_donor_status(donor)
    else:
        donor[status_field] = "EXCLUDED"
        touch(donor)
        domain.refresh_donor_status(donor)
        domain.cascade_participant_withdrawal(
            domain.segments_of_donor(donor), "DONOR_EXCLUDED"
        )

    return object_response(serialize.donor_evaluation(evaluation))


@bp.post("/donor-evaluations/<evaluation_id>/resubmission")
def resubmit_evaluation(evaluation_id):
    authenticate(["EvaluationReviewer"])
    evaluation = find_evaluation(evaluation_id)

    body = get_body()
    findings = read_findings(body, evaluation["domain"])

    # priority 7
    if evaluation["reviewer_staff_id"] != g.user_id:
        raise ApiError(
            "ERR_NOT_ASSIGNED_REVIEWER", "the caller is not this evaluation's assigned reviewer"
        )

    # priority 8
    if evaluation["status"] != "DEFERRED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "only a DEFERRED evaluation may be resubmitted (current %s)" % evaluation["status"],
        )
    donor = db.donors[evaluation["donor_candidate_id"]]
    if donor["overall_status"] in RESUBMISSION_BLOCKED_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "a donor in %s accepts no resubmission" % donor["overall_status"],
        )

    evaluation.update(findings)
    screen(evaluation, donor)
    evaluation["status"] = "SUBMITTED"
    evaluation["submission_count"] = evaluation["submission_count"] + 1
    evaluation["determined_at"] = None
    touch(evaluation)

    # the donor's matching risk-points field and screening_risk_index are recomputed;
    # deferral_count is deliberately left untouched.
    donor[DIMENSION_POINTS[evaluation["domain"]]] = evaluation["risk_points"]
    touch(donor)
    domain.refresh_donor_status(donor)

    return object_response(serialize.donor_evaluation(evaluation))
