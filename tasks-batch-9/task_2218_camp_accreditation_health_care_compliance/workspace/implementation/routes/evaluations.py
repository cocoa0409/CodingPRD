"""Standard evaluations: the self-assessment and visit-scoring dimensions."""

from flask import Blueprint

import db
import domain
import helpers
import response
import validators
from errors import api_error
from middleware import authenticate

bp = Blueprint("evaluations", __name__)


@bp.get("/accreditation/standard-evaluations/<evaluation_id>")
def get_evaluation(evaluation_id):
    ident = authenticate(("CampDirector", "AccreditationOfficer", "Visitor"))
    evaluation = helpers.evaluation_or_404(evaluation_id)
    helpers.scope(ident, helpers.camp_id_of_evaluation(evaluation))
    return response.ok(helpers.public(evaluation))


@bp.get("/accreditation/standard-evaluations")
def list_evaluations():
    authenticate(("CampDirector", "AccreditationOfficer", "Visitor"))
    return helpers.collection_response(db.evaluations, helpers.EVALUATION_FILTERS)


@bp.patch("/accreditation/standard-evaluations/<evaluation_id>/self-assessment")
def record_self_assessment(evaluation_id):
    ident = authenticate(("CampDirector",))
    data = validators.body()
    self_score = validators.req_enum(data, "self_score", domain.SELF_SCORES)
    plan_id = data.get("written_plan_id")
    if plan_id is not None and not isinstance(plan_id, str):
        raise api_error("ERR_INVALID_REQUEST", "Field 'written_plan_id' must be a string.")
    note = validators.opt_str(data, "note", 0, 2000)

    evaluation = helpers.evaluation_or_404(evaluation_id)
    plan = helpers.plan_or_404(plan_id) if plan_id is not None else None

    cycle = db.cycles.get(evaluation["cycle_id"])
    helpers.scope(ident, cycle["camp_id"])
    camp = db.camps.get(cycle["camp_id"])
    standard = db.standards.get(evaluation["standard_id"])

    if cycle["status"] != "SELF_ASSESSMENT":
        raise api_error(
            "ERR_CYCLE_NOT_IN_SELF_ASSESSMENT", "The cycle is not in SELF_ASSESSMENT."
        )
    if evaluation["self_status"] == "VERIFIED":
        raise api_error(
            "ERR_EVALUATION_LOCKED", "A verified self score may not be rewritten."
        )

    required_type = standard["written_plan_type_required"] if standard else None
    if self_score == "MET" and required_type is not None:
        if (
            plan is None
            or plan["plan_type"] != required_type
            or plan["camp_id"] != cycle["camp_id"]
            or plan["status"] != "VERIFIED"
        ):
            raise api_error(
                "ERR_WRITTEN_PLAN_NOT_VERIFIED",
                "A verified %s plan must be cited to claim MET." % required_type,
            )
    if not evaluation["applicable"]:
        raise api_error(
            "ERR_STANDARD_NOT_APPLICABLE", "The standard is not applicable to this camp."
        )
    if plan is not None and plan["camp_id"] != cycle["camp_id"]:
        raise api_error(
            "ERR_PLAN_CAMP_MISMATCH", "The cited plan belongs to a different camp."
        )

    evaluation["self_score"] = self_score
    if plan_id is not None:
        evaluation["written_plan_id"] = plan_id
    if note is not None:
        evaluation["note"] = note
    evaluation["self_status"] = "SUBMITTED"
    db.touch(evaluation)
    domain.recompute_risk_index(camp)
    return response.ok(helpers.public(evaluation))


@bp.patch("/accreditation/standard-evaluations/<evaluation_id>/visitor-score")
def record_visitor_score(evaluation_id):
    ident = authenticate(("Visitor",))
    data = validators.body()
    visitor_score = validators.req_enum(data, "visitor_score", domain.VISITOR_SCORES)
    score_source = validators.req_enum(data, "score_source", domain.SCORE_SOURCES)
    note = validators.opt_str(data, "note", 0, 2000)

    evaluation = helpers.evaluation_or_404(evaluation_id)
    cycle = db.cycles.get(evaluation["cycle_id"])
    standard = db.standards.get(evaluation["standard_id"])
    row_visit = domain.active_visit(cycle["id"])
    visitor = db.visitors.get(ident.user_id)

    seats = [
        seat
        for seat in domain.visitor_assignments(ident.user_id)
        if seat["status"] == "ASSIGNED"
    ]
    # The reference visit is the one the acting visitor holds their seat on: normally the
    # row's own cycle visit, otherwise whichever visit of theirs is live.
    visit = None
    if row_visit is not None and any(seat["visit_id"] == row_visit["id"] for seat in seats):
        visit = row_visit
    else:
        for seat in seats:
            other = db.visits.get(seat["visit_id"])
            if other is not None and other["status"] == "IN_PROGRESS":
                visit = other
                break
    if visit is None:
        visit = row_visit

    if visit is None or not any(seat["visit_id"] == visit["id"] for seat in seats):
        raise api_error(
            "ERR_FORBIDDEN_SCOPE",
            "Only a seated visitor of the cycle's visit may score it.",
        )

    if visit["status"] != "IN_PROGRESS":
        raise api_error("ERR_VISIT_INVALID_STATE", "The visit is not IN_PROGRESS.")
    if evaluation["visit_status"] == "LOCKED":
        raise api_error("ERR_EVALUATION_LOCKED", "The evaluation is locked.")
    if standard is not None and standard["domain"] in domain.SPECIALIST_DOMAINS:
        certification = domain.DOMAIN_CERTIFICATION[standard["domain"]]
        held = (visitor["certifications"] or []) if visitor else []
        if certification not in held:
            raise api_error(
                "ERR_SPECIALIST_CERTIFICATION_REQUIRED",
                "Scoring a %s standard requires %s." % (standard["domain"], certification),
            )
    if not evaluation["applicable"]:
        raise api_error(
            "ERR_STANDARD_NOT_APPLICABLE", "The standard is not applicable to this camp."
        )
    if visit["cycle_id"] != cycle["id"]:
        raise api_error(
            "ERR_VISIT_CYCLE_MISMATCH",
            "The evaluation belongs to a different cycle than the visitor's visit.",
        )

    evaluation["visitor_score"] = visitor_score
    evaluation["score_source"] = score_source
    if note is not None:
        evaluation["note"] = note
    evaluation["visit_status"] = "SCORED"
    evaluation["visit_id"] = visit["id"]
    evaluation["scored_by_visitor_id"] = ident.user_id
    db.touch(evaluation)
    domain.recompute_visit_scoring_counts(visit, cycle["id"])
    return response.ok(helpers.public(evaluation))
