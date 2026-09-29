"""Accreditation cycles: opening, self-assessment submission and the decision."""

from flask import Blueprint

import clock
import db
import domain
import helpers
import response
import validators
from errors import api_error
from middleware import authenticate

bp = Blueprint("cycles", __name__)


@bp.get("/accreditation/cycles/<cycle_id>")
def get_cycle(cycle_id):
    ident = authenticate(("CampDirector", "AccreditationOfficer", "Visitor"))
    cycle = helpers.cycle_or_404(cycle_id)
    helpers.scope(ident, cycle["camp_id"])
    return response.ok(helpers.public(cycle))


@bp.get("/accreditation/cycles")
def list_cycles():
    authenticate(("CampDirector", "AccreditationOfficer", "Visitor"))
    return helpers.collection_response(db.cycles, helpers.CYCLE_FILTERS)


@bp.get("/accreditation/cycles/<cycle_id>/compliance-summary")
def compliance_summary(cycle_id):
    ident = authenticate(("CampDirector", "AccreditationOfficer", "Visitor"))
    cycle = helpers.cycle_or_404(cycle_id)
    helpers.scope(ident, cycle["camp_id"])
    camp = db.camps.get(cycle["camp_id"])

    p_den, p_num, p_pct = domain.provisional_figures(cycle["id"])
    f_den, f_num, f_pct = domain.final_figures(cycle["id"])
    w_total, w_met, w_pct = domain.weighted_figures(cycle["id"])
    return response.ok(
        {
            "cycle_id": cycle["id"],
            "applicable_standard_count": cycle["applicable_standard_count"],
            "applicable_mandatory_count": cycle["applicable_mandatory_count"],
            "provisional_denominator": p_den,
            "provisional_numerator": p_num,
            "provisional_mandatory_pct": p_pct,
            "final_denominator": f_den,
            "final_numerator": f_num,
            "final_mandatory_pct": f_pct,
            "weighted_total": w_total,
            "weighted_met": w_met,
            "final_weighted_pct": w_pct,
            "open_deficiency_count": domain.open_deficiency_count(cycle["id"]),
            "projected_decision_level": domain.decision_level(camp, f_pct, w_pct),
        }
    )


@bp.post("/accreditation/cycles")
def open_cycle():
    ident = authenticate(("AccreditationOfficer",))
    data = validators.body()
    camp_id = validators.require(data, "camp_id")
    set_id = validators.require(data, "standards_set_id")
    if not isinstance(camp_id, str) or not isinstance(set_id, str):
        raise api_error("ERR_INVALID_REQUEST", "Identifier fields must be strings.")
    cycle_year = validators.req_int(data, "cycle_year", 2000, 2100)
    expected_camp_version = validators.req_int(data, "expected_camp_version", 0)

    camp = helpers.camp_or_404(camp_id)
    standards_set = helpers.set_or_404(set_id)

    if expected_camp_version != camp["version"]:
        raise api_error(
            "ERR_STALE_CAMP_VERSION",
            "The camp has moved on since the version you pinned.",
        )
    if standards_set["status"] != "PUBLISHED":
        raise api_error(
            "ERR_STANDARDS_SET_NOT_PUBLISHED",
            "Only a PUBLISHED edition may be pinned by a cycle.",
        )
    if camp["compliance_posture"] == "FROZEN":
        raise api_error(
            "ERR_CAMP_POSTURE_FROZEN", "The camp's compliance posture is FROZEN."
        )
    for existing in domain.camp_cycles(camp_id):
        if existing["cycle_year"] == cycle_year:
            raise api_error(
                "ERR_DUPLICATE_CYCLE_YEAR",
                "A cycle already exists for that camp and cycle year.",
            )

    cycle = db.common_fields()
    cycle.update(
        {
            "camp_id": camp_id,
            "standards_set_id": set_id,
            "cycle_year": cycle_year,
            "status": "SELF_ASSESSMENT",
            "decision_level": None,
            "applicable_standard_count": 0,
            "applicable_mandatory_count": 0,
            "self_assessment_submitted_at": None,
            "provisional_mandatory_pct": None,
            "final_mandatory_pct": None,
            "final_weighted_pct": None,
            "open_deficiency_count": 0,
            "assessed_fee_cents": None,
            "correction_deadline_at": None,
            "decision_issued_at": None,
            "decision_issued_by_user_id": None,
        }
    )

    applicable_count = 0
    applicable_mandatory = 0
    edition_standards = db.ordered(
        db.standards, lambda s: s["standards_set_id"] == set_id
    )
    for standard in edition_standards:
        applicable = domain.standard_applies(standard, camp)
        evaluation = db.common_fields()
        evaluation.update(
            {
                "cycle_id": cycle["id"],
                "standard_id": standard["id"],
                "visit_id": None,
                "scored_by_visitor_id": None,
                "written_plan_id": None,
                "applicable": applicable,
                "mandatory": standard["mandatory"],
                "scoring_weight": standard["scoring_weight"],
                "self_score": None,
                "self_status": "DRAFT",
                "visitor_score": None,
                "score_source": None,
                "visit_status": "UNSCORED",
                "note": None,
            }
        )
        db.evaluations[evaluation["id"]] = evaluation
        if applicable:
            applicable_count += 1
            if standard["mandatory"]:
                applicable_mandatory += 1
    cycle["applicable_standard_count"] = applicable_count
    cycle["applicable_mandatory_count"] = applicable_mandatory
    db.cycles[cycle["id"]] = cycle

    # Supersede: any prior cycle of this camp still in SELF_ASSESSMENT.
    for prior in domain.camp_cycles(camp_id):
        if prior["id"] == cycle["id"] or prior["status"] != "SELF_ASSESSMENT":
            continue
        prior["status"] = "TERMINATED"
        db.touch(prior)
        standing = domain.standing_visit(prior["id"])
        if standing is not None:
            domain.rescind_visit(standing)

    db.touch(camp)
    domain.recompute_risk_index(camp)
    return response.created(helpers.public(cycle))


@bp.post("/accreditation/cycles/<cycle_id>/submit-self-assessment")
def submit_self_assessment(cycle_id):
    ident = authenticate(("CampDirector",))
    cycle = helpers.cycle_or_404(cycle_id)
    helpers.scope(ident, cycle["camp_id"])
    camp = db.camps.get(cycle["camp_id"])

    if cycle["status"] != "SELF_ASSESSMENT":
        raise api_error(
            "ERR_CYCLE_NOT_IN_SELF_ASSESSMENT",
            "The cycle is not in SELF_ASSESSMENT.",
        )
    if domain.rank(camp["health_staffing_level"]) < domain.rank(
        camp["required_health_staffing_level"]
    ):
        raise api_error(
            "ERR_HEALTH_STAFFING_INSUFFICIENT",
            "The camp's health staffing is below the required level.",
        )
    rows = domain.cycle_evaluations(cycle["id"])
    for row in rows:
        if not row["applicable"]:
            continue
        if row["self_score"] is None or row["self_status"] != "SUBMITTED":
            raise api_error(
                "ERR_SELF_ASSESSMENT_INCOMPLETE",
                "Every applicable standard must carry a submitted self score.",
            )

    for row in rows:
        if row["applicable"] and row["self_status"] == "SUBMITTED":
            row["self_status"] = "VERIFIED"
            db.touch(row)
    cycle["self_assessment_submitted_at"] = clock.now_iso()
    db.touch(cycle)
    domain.recompute_risk_index(camp)
    return response.ok(helpers.public(cycle))


@bp.post("/accreditation/cycles/<cycle_id>/decision")
def issue_decision(cycle_id):
    ident = authenticate(("AccreditationOfficer",))
    cycle = helpers.cycle_or_404(cycle_id)
    camp = db.camps.get(cycle["camp_id"])
    visit = domain.active_visit(cycle["id"])

    if visit is not None and visit["scheduled_by_user_id"] == ident.user_id:
        raise api_error(
            "ERR_SEGREGATION_OF_DUTIES",
            "The officer who confirmed the visit may not issue the decision.",
        )
    if cycle["status"] != "VISIT_COMPLETED":
        raise api_error(
            "ERR_CYCLE_NOT_IN_SELF_ASSESSMENT",
            "A decision may only be issued for a cycle in VISIT_COMPLETED.",
        )
    if visit is None or visit["status"] != "SCORED":
        raise api_error(
            "ERR_VISIT_INVALID_STATE",
            "The cycle must carry exactly one non-rescinded visit in SCORED.",
        )

    _, _, final_pct = domain.final_figures(cycle["id"])
    _, _, weighted_pct = domain.weighted_figures(cycle["id"])
    level = domain.decision_level(camp, final_pct, weighted_pct)
    fee = domain.assess_fee(cycle, camp)
    open_count = domain.open_deficiency_count(cycle["id"])

    cycle["final_mandatory_pct"] = final_pct
    cycle["final_weighted_pct"] = weighted_pct
    cycle["decision_level"] = level
    cycle["assessed_fee_cents"] = fee
    cycle["open_deficiency_count"] = open_count
    cycle["decision_issued_at"] = clock.now_iso()
    cycle["decision_issued_by_user_id"] = ident.user_id
    db.touch(cycle)

    camp["accreditation_status"] = {
        "ACCREDITED": "ACCREDITED",
        "ACCREDITED_WITH_CORRECTION": "ACCREDITED_WITH_CORRECTION",
        "PROVISIONAL": "PROVISIONAL",
        "DENIED": "REVOKED",
    }[level]
    db.touch(camp)

    if level == "DENIED":
        cycle["status"] = "TERMINATED"
        for deficiency in domain.visit_deficiencies(visit["id"]):
            if deficiency["status"] in domain.OPEN_DEFICIENCY_STATUSES:
                deficiency["status"] = "ESCALATED"
                db.touch(deficiency)
        domain.recompute_open_deficiency_count(cycle)
        domain.recompute_penalty_balance(camp)
        domain.recompute_posture(camp)
    elif open_count > 0:
        cycle["status"] = "IN_CORRECTION"
        due_dates = [
            x["correction_due_date"]
            for x in domain.visit_deficiencies(visit["id"])
            if x["correction_due_date"] is not None
        ]
        if due_dates:
            cycle["correction_deadline_at"] = "%sT23:59:59.999Z" % max(due_dates)
    else:
        cycle["status"] = "CLOSED"
        domain.archive_prior_reports(camp["id"], cycle["cycle_year"])
        if level == "ACCREDITED":
            camp["prior_accredited_cycle_count"] = (
                camp["prior_accredited_cycle_count"] + 1
            )
            camp["last_accredited_year"] = cycle["cycle_year"]

    domain.recompute_risk_index(camp)
    return response.ok(helpers.public(cycle))
