"""StudyReport drafting, segregated QA review, client review and release
(PRD §3.7)."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_FORBIDDEN_ROLE, ERR_INVALID_STUDY_STATE,
    ERR_INVALID_REPORT_STATE, ERR_RECO_NOT_PROPOSED,
    ERR_REPORT_STUDY_MISMATCH, ERR_NO_ACCEPTED_RECOMMENDATION,
    ERR_REPORT_REQUIRES_REVISION, ERR_SEGREGATION_OF_DUTIES,
    ERR_UNVERIFIED_CLAIMS,
)
from flask import Blueprint, g, request
from response import respond, respond_list
from routes.studies import complete_study
from services import ser_report
from util import body, paginate, req_str, sort_created, touch

bp = Blueprint("reports", __name__)


def get_report(report_id):
    r = db.store["reports"].get(report_id)
    if r is None:
        raise_err(ERR_NOT_FOUND, f"StudyReport {report_id} not found")
    return r


@bp.route("/study-reports", methods=["POST"])
@require_roles("SensoryScientist")
def create_report():
    b = body()
    study_id = req_str(b, "study_id")
    title = req_str(b, "title")
    study = db.store["studies"].get(study_id)
    if study is None:
        raise_err(ERR_NOT_FOUND, f"Study {study_id} not found")
    if study["status"] not in ("ANALYSIS", "REPORTING"):
        raise_err(ERR_INVALID_STUDY_STATE,
                  "reports may be drafted only while the study is ANALYSIS "
                  "or REPORTING")
    now = clock.now()
    report = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "study_id": study_id,
        "title": title,
        "author_user_id": g.user_id,
        "pinned_recommendation_id": None,
        "snapshot_days": None,
        "requires_revision": False,
        "revision_count": 0,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["reports"][report["id"]] = report
    return respond(ser_report(report), 201)


@bp.route("/study-reports", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_reports():
    items = sort_created(db.store["reports"].values())
    for field in ("study_id", "status", "pinned_recommendation_id"):
        v = request.args.get(field)
        if v is not None:
            items = [r for r in items if r[field] == v]
    page, pagination = paginate(items)
    return respond_list([ser_report(r) for r in page], pagination)


@bp.route("/study-reports/<report_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_report(report_id):
    return respond(ser_report(get_report(report_id)), 200)


@bp.route("/study-reports/<report_id>/attach-recommendation",
          methods=["POST"])
@require_roles("SensoryScientist")
def attach_recommendation(report_id):
    report = get_report(report_id)
    # Author-only (PRD §2.6 rung 2 ownership precedes state gates).
    if report["author_user_id"] != g.user_id:
        raise_err(ERR_FORBIDDEN_ROLE,
                  "only the report author may attach a recommendation")
    b = body()
    recommendation_id = req_str(b, "recommendation_id")
    rec = db.store["recommendations"].get(recommendation_id)
    if rec is None:
        raise_err(ERR_NOT_FOUND,
                  f"DateCodeRecommendation {recommendation_id} not found")
    if report["status"] != "DRAFT":
        raise_err(ERR_INVALID_REPORT_STATE,
                  "attach-recommendation requires the report to be DRAFT")
    if rec["status"] != "ACCEPTED":
        raise_err(ERR_RECO_NOT_PROPOSED,
                  "the recommendation must be ACCEPTED")
    if rec["study_id"] != report["study_id"]:
        raise_err(ERR_REPORT_STUDY_MISMATCH,
                  "the recommendation belongs to a different study")
    report["pinned_recommendation_id"] = recommendation_id
    report["requires_revision"] = False
    touch(report)
    return respond(ser_report(report), 200)


@bp.route("/study-reports/<report_id>/submit", methods=["POST"])
@require_roles("SensoryScientist")
def submit_report(report_id):
    report = get_report(report_id)
    if report["author_user_id"] != g.user_id:
        raise_err(ERR_FORBIDDEN_ROLE,
                  "only the report author may submit the report")
    if report["status"] != "DRAFT":
        raise_err(ERR_INVALID_REPORT_STATE,
                  "submit requires the report to be DRAFT")
    rec = None
    if report["pinned_recommendation_id"] is not None:
        rec = db.store["recommendations"].get(
            report["pinned_recommendation_id"])
    if rec is None or rec["status"] != "ACCEPTED":
        raise_err(ERR_NO_ACCEPTED_RECOMMENDATION,
                  "submit requires a pinned ACCEPTED recommendation")
    if report["requires_revision"]:
        raise_err(ERR_REPORT_REQUIRES_REVISION,
                  "report requires revision before it can be submitted")
    # Version-pin the pinned recommendation's computed_days at submit.
    report["snapshot_days"] = rec["computed_days"]
    report["status"] = "INTERNAL_REVIEW"
    touch(report)
    return respond(ser_report(report), 200)


@bp.route("/study-reports/<report_id>/qa-approve", methods=["POST"])
@require_roles("QAOfficer")
def qa_approve(report_id):
    report = get_report(report_id)
    if report["status"] != "INTERNAL_REVIEW":
        raise_err(ERR_INVALID_REPORT_STATE,
                  "qa-approve requires the report to be INTERNAL_REVIEW")
    if report["author_user_id"] == g.user_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "a QAOfficer may not approve a report they authored")
    if report["requires_revision"]:
        raise_err(ERR_REPORT_REQUIRES_REVISION,
                  "report requires revision before it can be approved")
    report["status"] = "CLIENT_REVIEW"
    touch(report)
    return respond(ser_report(report), 200)


@bp.route("/study-reports/<report_id>/qa-return", methods=["POST"])
@require_roles("QAOfficer")
def qa_return(report_id):
    report = get_report(report_id)
    if report["status"] != "INTERNAL_REVIEW":
        raise_err(ERR_INVALID_REPORT_STATE,
                  "qa-return requires the report to be INTERNAL_REVIEW")
    report["status"] = "DRAFT"
    report["revision_count"] += 1
    touch(report)
    return respond(ser_report(report), 200)


@bp.route("/study-reports/<report_id>/qa-reject", methods=["POST"])
@require_roles("QAOfficer")
def qa_reject(report_id):
    report = get_report(report_id)
    if report["status"] != "INTERNAL_REVIEW":
        raise_err(ERR_INVALID_REPORT_STATE,
                  "qa-reject requires the report to be INTERNAL_REVIEW")
    if report["author_user_id"] == g.user_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "a QAOfficer may not reject a report they authored")
    report["status"] = "REJECTED"
    touch(report)
    return respond(ser_report(report), 200)


@bp.route("/study-reports/<report_id>/request-changes", methods=["POST"])
@require_roles("Client")
def request_changes(report_id):
    report = get_report(report_id)
    study = db.store["studies"][report["study_id"]]
    # Ownership: the acting Client must own the study (PRD §2.1).
    if study["client_id"] != g.user_id:
        raise_err(ERR_FORBIDDEN_ROLE,
                  "a client may request changes only on their own study's "
                  "report")
    if report["status"] != "CLIENT_REVIEW":
        raise_err(ERR_INVALID_REPORT_STATE,
                  "request-changes requires the report to be CLIENT_REVIEW")
    report["status"] = "DRAFT"
    report["requires_revision"] = False
    report["revision_count"] += 1
    touch(report)
    return respond(ser_report(report), 200)


@bp.route("/study-reports/<report_id>/release", methods=["POST"])
@require_roles("LabDirector")
def release_report(report_id):
    report = get_report(report_id)
    if report["status"] != "CLIENT_REVIEW":
        raise_err(ERR_INVALID_REPORT_STATE,
                  "release requires the report to be CLIENT_REVIEW")
    if report["requires_revision"]:
        raise_err(ERR_REPORT_REQUIRES_REVISION,
                  "report requires revision before it can be released")
    for claim in db.store["claims"].values():
        if claim["report_id"] == report_id and claim["verdict"] != "SUPPORTED":
            raise_err(ERR_UNVERIFIED_CLAIMS,
                      "every claim of the report must be SUPPORTED before "
                      "release")
    study = db.store["studies"][report["study_id"]]
    if study["status"] != "REPORTING":
        raise_err(ERR_INVALID_STUDY_STATE,
                  "release requires the study to be REPORTING")
    report["status"] = "RELEASED"
    touch(report)
    complete_study(study)
    return respond(ser_report(report), 200)
