"""Deficiency correction plans and officer adjudication."""

from flask import Blueprint

import clock
import db
import domain
import helpers
import response
import validators
from errors import api_error
from middleware import authenticate

bp = Blueprint("deficiencies", __name__)

DECISIONS = ("ACCEPT_PLAN", "REJECT_PLAN", "VERIFY_CORRECTION", "WAIVE")


@bp.get("/accreditation/deficiencies/<deficiency_id>")
def get_deficiency(deficiency_id):
    ident = authenticate(("CampDirector", "AccreditationOfficer"))
    deficiency = helpers.deficiency_or_404(deficiency_id)
    helpers.scope(ident, domain.camp_id_of_deficiency(deficiency))
    return response.ok(helpers.public(deficiency))


@bp.get("/accreditation/deficiencies")
def list_deficiencies():
    authenticate(("CampDirector", "AccreditationOfficer"))
    return helpers.collection_response(db.deficiencies, helpers.DEFICIENCY_FILTERS)


def _cycle_of(deficiency):
    visit = db.visits.get(deficiency["visit_id"])
    return db.cycles.get(visit["cycle_id"]) if visit else None


@bp.post("/accreditation/deficiencies/<deficiency_id>/correction-plan")
def file_correction_plan(deficiency_id):
    ident = authenticate(("CampDirector",))
    data = validators.body()
    text = validators.req_str(data, "correction_plan_text", 1, 5000)

    deficiency = helpers.deficiency_or_404(deficiency_id)
    helpers.scope(ident, domain.camp_id_of_deficiency(deficiency))

    if deficiency["status"] not in ("OPEN", "PLAN_SUBMITTED"):
        raise api_error(
            "ERR_DEFICIENCY_INVALID_STATE",
            "A correction plan may only be filed against an open finding.",
        )
    if deficiency["plan_revision_count"] >= domain.PLAN_REVISION_LIMIT:
        raise api_error(
            "ERR_PLAN_REVISION_LIMIT", "The correction plan revision limit is exhausted."
        )
    if clock.today().isoformat() > deficiency["correction_due_date"]:
        raise api_error(
            "ERR_CORRECTION_WINDOW_EXPIRED", "The correction window has expired."
        )

    deficiency["status"] = "PLAN_SUBMITTED"
    deficiency["plan_revision_count"] = deficiency["plan_revision_count"] + 1
    deficiency["correction_plan_text"] = text
    deficiency["last_plan_submitted_at"] = clock.now_iso()
    db.touch(deficiency)
    return response.ok(helpers.public(deficiency))


@bp.post("/accreditation/deficiencies/<deficiency_id>/review")
def review_deficiency(deficiency_id):
    ident = authenticate(("AccreditationOfficer",))
    data = validators.body()
    decision = validators.req_enum(data, "decision", DECISIONS)
    note = validators.opt_str(data, "reviewer_note", 0, 2000)

    deficiency = helpers.deficiency_or_404(deficiency_id)
    cycle = _cycle_of(deficiency)
    camp = db.camps.get(cycle["camp_id"]) if cycle else None

    required = {
        "ACCEPT_PLAN": "PLAN_SUBMITTED",
        "REJECT_PLAN": "PLAN_SUBMITTED",
        "VERIFY_CORRECTION": "PLAN_ACCEPTED",
        "WAIVE": "OPEN",
    }[decision]
    if deficiency["status"] != required:
        raise api_error(
            "ERR_DEFICIENCY_INVALID_STATE",
            "%s requires the finding to be in %s." % (decision, required),
        )
    if decision == "WAIVE" and deficiency["severity"] != "SCORED":
        raise api_error(
            "ERR_DEFICIENCY_INVALID_STATE",
            "Only a SCORED finding may be waived.",
        )
    if decision in ("ACCEPT_PLAN", "REJECT_PLAN", "VERIFY_CORRECTION") and (
        clock.today().isoformat() > deficiency["correction_due_date"]
    ):
        raise api_error(
            "ERR_CORRECTION_WINDOW_EXPIRED", "The correction window has expired."
        )

    deficiency["reviewer_user_id"] = ident.user_id
    if note is not None:
        deficiency["reviewer_note"] = note

    terminated = False
    if decision == "ACCEPT_PLAN":
        deficiency["status"] = "PLAN_ACCEPTED"
    elif decision == "VERIFY_CORRECTION":
        deficiency["status"] = "CORRECTED"
    elif decision == "WAIVE":
        deficiency["status"] = "WAIVED"
    else:
        if deficiency["plan_revision_count"] >= domain.PLAN_REVISION_LIMIT:
            deficiency["status"] = "ESCALATED"
            terminated = True
        else:
            deficiency["status"] = "OPEN"
    db.touch(deficiency)

    if terminated and cycle is not None:
        if cycle["status"] == "IN_CORRECTION":
            cycle["status"] = "TERMINATED"
            db.touch(cycle)
        camp["accreditation_status"] = "REVOKED"
        db.touch(camp)

    if camp is not None:
        domain.recompute_penalty_balance(camp)
        domain.recompute_posture(camp)

    if cycle is not None:
        count = domain.recompute_open_deficiency_count(cycle)
        if count == 0 and cycle["status"] == "IN_CORRECTION":
            cycle["status"] = "CLOSED"
            cycle["correction_deadline_at"] = None
            db.touch(cycle)
            domain.archive_prior_reports(camp["id"], cycle["cycle_year"])
            if cycle["decision_level"] == "ACCREDITED_WITH_CORRECTION":
                camp["accreditation_status"] = "ACCREDITED"
                camp["prior_accredited_cycle_count"] = (
                    camp["prior_accredited_cycle_count"] + 1
                )
                camp["last_accredited_year"] = cycle["cycle_year"]
                db.touch(camp)

    return response.ok(helpers.public(deficiency))
