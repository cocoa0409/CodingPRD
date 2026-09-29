"""Substantial-equivalency evaluations: two parallel dimensions (PRD §3.5)."""
from flask import Blueprint

import clock
import db
import response
import serializers
import validators as v
from constants import (
    ALL_ROLES, DISCIPLINE_FINDINGS, EVALUATION_OVERALL_STATUSES,
    REVIEWABLE_STATUSES, ROLE_ANALYST, ROLE_APPLICANT, ROLE_EVALUATOR,
    SCOPE_REVIEW_DECISIONS,
)
from errors import (
    ERR_APPLICATION_NOT_REVIEWABLE, ERR_CREDENTIAL_APPLICANT_MISMATCH,
    ERR_EVALUATION_ALREADY_EXISTS, ERR_EVALUATION_ALREADY_FINALIZED,
    ERR_NO_OPEN_REVIEW_ASSIGNMENT, ERR_OWNERSHIP_VIOLATION,
    ERR_REVIEW_WINDOW_LAPSED, fail, invalid,
)
from middleware import authenticate
from numbers_util import dec, rhu_cents
from services import calculations, lookups, workflow

bp = Blueprint("evaluations", __name__)


def _variant_for(pathway):
    return ("UNIVERSAL_RECOGNITION" if pathway == "UNIVERSAL_RECOGNITION"
            else "STRICT_SCOPE")


def _require_parent_reviewable(application, allowed):
    if application["status"] not in allowed:
        fail(ERR_APPLICATION_NOT_REVIEWABLE,
             "The parent application is in status %s, which this operation does "
             "not permit." % application["status"])


@bp.post("/licensure/credential-evaluations")
def create_evaluation():
    authenticate([ROLE_ANALYST])
    body = v.body()
    application_id = v.f_string(body, "application_id")
    credential_id = v.f_string(body, "credential_id")

    application = lookups.application(application_id)
    credential = lookups.credential(credential_id)

    _require_parent_reviewable(application, ("SUBMITTED",))

    for existing in db.evaluations.values():
        if existing["application_id"] == application["id"]:
            fail(ERR_EVALUATION_ALREADY_EXISTS,
                 "This application already has a credential evaluation.")

    if credential["applicant_id"] != application["applicant_id"]:
        fail(ERR_CREDENTIAL_APPLICANT_MISMATCH,
             "The nominated credential belongs to a different applicant.")

    profession = db.professions[application["profession_id"]]
    matched, missing = calculations.scope_comparison(profession, credential)

    row = db.make_row({
        "application_id": application["id"],
        "credential_id": credential["id"],
        "variant": _variant_for(application["pathway"]),
        "scope_review_status": "PENDING",
        "discipline_review_status": "PENDING",
        "overall_status": "IN_PROGRESS",
        "matched_scope_elements": matched,
        "missing_scope_elements": missing,
        "equivalency_score": None,
        "exam_waiver_granted": False,
        "finalized_at": None,
        "reviewed_by_user_id": None,
    })
    db.evaluations[row["id"]] = row

    application["status"] = "UNDER_REVIEW"
    db.touch(application)
    return response.object_response(serializers.evaluation(row), 201)


@bp.get("/licensure/credential-evaluations/<evaluation_id>")
def read_evaluation(evaluation_id):
    user_id, role = authenticate(ALL_ROLES)
    row = lookups.evaluation(evaluation_id)
    application = db.applications[row["application_id"]]
    lookups.require_applicant_ownership(role, user_id,
                                        application["applicant_id"])
    return response.object_response(serializers.evaluation(row))


@bp.get("/licensure/credential-evaluations")
def list_evaluations():
    user_id, role = authenticate(ALL_ROLES)
    limit, offset = response.pagination()
    application_id = response.query_string("application_id")
    credential_id = response.query_string("credential_id")
    overall_status = response.query_enum("overall_status",
                                         EVALUATION_OVERALL_STATUSES)
    rows = []
    for row in db.evaluations.values():
        if application_id is not None and row["application_id"] != application_id:
            continue
        if credential_id is not None and row["credential_id"] != credential_id:
            continue
        if overall_status is not None and row["overall_status"] != overall_status:
            continue
        if role == ROLE_APPLICANT:
            application = db.applications.get(row["application_id"])
            if application is None or application["applicant_id"] != user_id:
                continue
        rows.append(row)
    return response.paginate(db.ordered(rows), limit, offset,
                             serializers.evaluation)


# ---------------------------------------------------------------------------
# first parallel dimension — the analyst's scope opinion
# ---------------------------------------------------------------------------
@bp.post("/licensure/credential-evaluations/<evaluation_id>/scope-review")
def record_scope_review(evaluation_id):
    user_id, role = authenticate([ROLE_ANALYST])
    body = v.body()
    decision = v.f_enum(body, "decision", SCOPE_REVIEW_DECISIONS)
    v.f_string(body, "note", required=False, default=None)

    evaluation = lookups.evaluation(evaluation_id)
    application = db.applications[evaluation["application_id"]]
    _require_parent_reviewable(application, ("UNDER_REVIEW", "DEFICIENT"))

    if (evaluation["finalized_at"] is not None
            or evaluation["scope_review_status"] != "PENDING"):
        fail(ERR_EVALUATION_ALREADY_FINALIZED,
             "The scope dimension of this evaluation is no longer writable.")

    profession = db.professions[application["profession_id"]]
    if decision == "EQUIVALENT":
        critical = set(profession["critical_scope_elements"])
        if any(element in critical
               for element in evaluation["missing_scope_elements"]):
            # PRD §3.5: refused with ERR_INVALID_REQUEST, evaluated after the
            # evaluation write-state check of §2.8.
            invalid("A critical scope element is missing, so the scope review "
                    "must be recorded as DEFICIENT_SCOPE.")

    evaluation["scope_review_status"] = decision
    evaluation["reviewed_by_user_id"] = user_id
    evaluation["overall_status"] = calculations.evaluation_overall_status(evaluation)
    db.touch(evaluation)

    application["scope_reviewed_by_user_id"] = user_id
    db.touch(application)
    return response.object_response(serializers.evaluation(evaluation))


# ---------------------------------------------------------------------------
# second parallel dimension — the contract reviewer's finding
# ---------------------------------------------------------------------------
@bp.post("/licensure/credential-evaluations/<evaluation_id>/discipline-finding")
def record_discipline_finding(evaluation_id):
    user_id, role = authenticate([ROLE_EVALUATOR])
    body = v.body()
    finding = v.f_enum(body, "finding", DISCIPLINE_FINDINGS)
    if "databases_checked" not in body or body["databases_checked"] is None:
        invalid("Field 'databases_checked' is required.")

    evaluation = lookups.evaluation(evaluation_id)
    open_rows = workflow.open_assignments(evaluation["application_id"])

    # Check 6 (§2.8): the Evaluator clause is evaluated only when at least one
    # ASSIGNED assignment exists for the target application.
    if open_rows and not any(a["evaluator_id"] == user_id for a in open_rows):
        fail(ERR_OWNERSHIP_VIOLATION,
             "This evaluator holds no review assignment for the application.")

    if (evaluation["finalized_at"] is not None
            or evaluation["discipline_review_status"] != "PENDING"):
        fail(ERR_EVALUATION_ALREADY_FINALIZED,
             "The disciplinary dimension of this evaluation is no longer "
             "writable.")

    mine = [a for a in open_rows if a["evaluator_id"] == user_id]
    if not mine:
        fail(ERR_NO_OPEN_REVIEW_ASSIGNMENT,
             "No ASSIGNED review assignment exists for this application.")

    assignment = mine[0]
    if clock.now() > assignment["window_end_at"]:
        fail(ERR_REVIEW_WINDOW_LAPSED,
             "The review window of this assignment has lapsed.")

    evaluation["discipline_review_status"] = finding
    evaluation["overall_status"] = calculations.evaluation_overall_status(evaluation)
    db.touch(evaluation)
    return response.object_response(serializers.evaluation(evaluation))


# ---------------------------------------------------------------------------
# finalisation
# ---------------------------------------------------------------------------
@bp.post("/licensure/credential-evaluations/<evaluation_id>/finalize")
def finalize_evaluation(evaluation_id):
    authenticate([ROLE_ANALYST])
    evaluation = lookups.evaluation(evaluation_id)
    application = db.applications[evaluation["application_id"]]
    _require_parent_reviewable(application, ("UNDER_REVIEW", "DEFICIENT"))

    if (evaluation["finalized_at"] is not None
            or evaluation["scope_review_status"] == "PENDING"
            or evaluation["discipline_review_status"] == "PENDING"):
        fail(ERR_EVALUATION_ALREADY_FINALIZED,
             "The evaluation cannot be finalised in its current state.")

    profession = db.professions[application["profession_id"]]
    applicant = db.applicants[application["applicant_id"]]
    credential = db.credentials[evaluation["credential_id"]]

    score = calculations.substantial_equivalency_score(
        evaluation, profession, credential, applicant)
    compact = calculations.unexpired_compact(profession["id"],
                                             applicant["state_code"])
    waiver = (score >= profession["exam_waiver_min_score"]
              or (compact is not None and compact["exam_waiver_allowed"]))

    evaluation["equivalency_score"] = score
    evaluation["exam_waiver_granted"] = bool(waiver)
    evaluation["finalized_at"] = clock.now()
    evaluation["overall_status"] = calculations.evaluation_overall_status(evaluation)
    db.touch(evaluation)

    if evaluation["exam_waiver_granted"]:
        already_waived = rhu_cents(dec(profession["exam_fee_cents"])
                                   * application["statutory_waiver_pct"])
        reversal = profession["exam_fee_cents"] - already_waived
        workflow.append_ledger(application, "EXAM_FEE_REVERSAL", -reversal)
        workflow.recompute_balance(application)
        db.touch(application)

    return response.object_response(serializers.evaluation(evaluation))
