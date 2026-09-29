"""Reports on compliance: drafting, QA, attestation and submission."""

from datetime import timedelta

from flask import Blueprint

import middleware as mw
from db import db, fmt_day, ordered
from errors import ApiError
from response import collection, single
from routes.ccws import guard_independence
from routes.engagements import guard_certified
from services import calc, derive, serialize

bp = Blueprint("rocs", __name__)

QA_DECISIONS = ("APPROVE", "REJECT")
SUBMISSION_TARGETS = ("ACQUIRER", "CARD_BRAND")
UNTESTED_STATUSES = ("NOT_STARTED", "IN_TESTING")


def _write_projection(report, engagement_id):
    projection = derive.compliance_projection(engagement_id)
    report["applicable_requirement_count"] = projection["applicable_requirement_count"]
    report["in_place_count"] = projection["in_place_count"]
    report["ccw_covered_count"] = projection["ccw_covered_count"]
    report["not_in_place_count"] = projection["not_in_place_count"]
    report["as_found_compliance_percentage"] = projection["as_found_compliance_percentage"]
    report["as_attested_compliance_percentage"] = projection["as_attested_compliance_percentage"]
    report["compliance_result"] = projection["compliance_result"]


@bp.post("/engagements/<engagement_id>/rocs")
def create_roc(engagement_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    body = mw.json_body()
    roc_version_label = mw.v_str(body, "roc_version_label", allow_empty=False)

    engagement = mw.fetch(db.engagements, engagement_id, "ERR_ENGAGEMENT_NOT_FOUND")
    mw.require_lead(engagement, user_id)
    derive.guard_restricted(engagement)

    if engagement.get("status") != "FIELDWORK":
        raise ApiError("ERR_INVALID_ENGAGEMENT_STATE")

    requirements = derive.requirements_of(engagement_id)
    applicable = [row for row in requirements if row.get("applicability") == "APPLICABLE"]
    if not applicable:
        raise ApiError("ERR_NO_APPLICABLE_REQUIREMENTS")
    if any(row.get("test_status") in UNTESTED_STATUSES for row in requirements):
        raise ApiError("ERR_REQUIREMENT_TESTING_INCOMPLETE")
    if derive.rocs_of(engagement_id):
        raise ApiError("ERR_ROC_ALREADY_EXISTS")

    row = {
        "engagement_id": engagement_id,
        "roc_version_label": roc_version_label,
        "status": "DRAFTING",
        "attestation_signature_name": None,
        "attesting_assessor_id": None,
        "attested_at": None,
        "submitted_to": None,
        "submission_reference": None,
        "qa_decision_note": None,
        "revision_count": 0,
    }
    db.stamp_new(row)
    _write_projection(row, engagement_id)
    db.rocs[row["id"]] = row

    engagement["status"] = "REPORTING"
    db.touch(engagement)
    return single(serialize.roc_report(row), 201)


@bp.get("/rocs")
def list_rocs():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    payload = [serialize.roc_report(row) for row in ordered(db.rocs.values())]
    payload = mw.apply_filters(payload, {
        "engagement_id": ("engagement_id", "str"),
        "attesting_assessor_id": ("attesting_assessor_id", "str"),
        "status": ("status", "str"),
        "compliance_result": ("compliance_result", "str"),
    })
    return collection(mw.page(payload, limit, offset), limit, offset, len(payload))


@bp.get("/rocs/<row_id>")
def get_roc(row_id):
    mw.authenticate(mw.ALL_ROLES)
    row = mw.fetch(db.rocs, row_id, "ERR_ROC_NOT_FOUND")
    return single(serialize.roc_report(row))


@bp.post("/rocs/<row_id>/qa-submit")
def qa_submit_roc(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    report = mw.fetch(db.rocs, row_id, "ERR_ROC_NOT_FOUND")
    engagement = db.engagements.get(report.get("engagement_id"))
    mw.require_lead(engagement, user_id)

    if report.get("status") != "DRAFTING":
        raise ApiError("ERR_INVALID_ROC_STATE")
    if not engagement.get("qa_reviewer_id"):
        raise ApiError("ERR_QA_REVIEWER_NOT_ASSIGNED")

    report["status"] = "IN_QA"
    db.touch(report)
    return single(serialize.roc_report(report))


@bp.post("/rocs/<row_id>/qa-review")
def qa_review_roc(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_QA,))
    body = mw.json_body()
    decision = mw.v_enum(body, "decision", QA_DECISIONS)
    qa_decision_note = mw.v_str(body, "qa_decision_note", allow_empty=False)

    report = mw.fetch(db.rocs, row_id, "ERR_ROC_NOT_FOUND")
    engagement = db.engagements.get(report.get("engagement_id"))
    mw.require_qa_reviewer(engagement, user_id)

    if report.get("status") != "IN_QA":
        raise ApiError("ERR_INVALID_ROC_STATE")

    # Rung 11 independence is checked before the rung 12 certification window.
    guard_independence(engagement, user_id)
    guard_certified(db.assessors.get(user_id))

    report["qa_decision_note"] = qa_decision_note
    if decision == "APPROVE":
        report["status"] = "QA_APPROVED"
        _write_projection(report, engagement["id"])
    else:
        report["status"] = "QA_REJECTED"
    db.touch(report)
    return single(serialize.roc_report(report))


@bp.post("/rocs/<row_id>/revise")
def revise_roc(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    body = mw.json_body()
    mw.v_str(body, "revision_note", allow_empty=False)

    report = mw.fetch(db.rocs, row_id, "ERR_ROC_NOT_FOUND")
    engagement = db.engagements.get(report.get("engagement_id"))
    mw.require_lead(engagement, user_id)

    if report.get("status") != "QA_REJECTED":
        raise ApiError("ERR_INVALID_ROC_STATE")

    report["status"] = "DRAFTING"
    report["revision_count"] = int(report.get("revision_count") or 0) + 1
    db.touch(report)

    engagement["status"] = "FIELDWORK"
    db.touch(engagement)
    return single(serialize.roc_report(report))


@bp.post("/rocs/<row_id>/attest")
def attest_roc(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    body = mw.json_body()
    attestation_signature_name = mw.v_str(body, "attestation_signature_name", allow_empty=False)

    report = mw.fetch(db.rocs, row_id, "ERR_ROC_NOT_FOUND")
    engagement = db.engagements.get(report.get("engagement_id"))
    mw.require_lead(engagement, user_id)

    if report.get("status") != "QA_APPROVED":
        raise ApiError("ERR_INVALID_ROC_STATE")

    lead = db.assessors.get(engagement.get("lead_assessor_id"))
    guard_certified(lead)
    if not derive.quarterly_scan_compliant(engagement["id"]):
        raise ApiError("ERR_NO_PASSING_SCAN")
    if attestation_signature_name != (lead or {}).get("full_name"):
        raise ApiError("ERR_ATTESTATION_SIGNATURE_MISMATCH")

    stamped = db.now_iso()
    report["status"] = "ATTESTED"
    report["attestation_signature_name"] = attestation_signature_name
    report["attesting_assessor_id"] = user_id
    report["attested_at"] = stamped
    db.touch(report)

    engagement["status"] = "ATTESTED"
    engagement["attested_at"] = stamped
    db.touch(engagement)
    return single(serialize.roc_report(report))


@bp.post("/rocs/<row_id>/submission")
def submit_roc(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    body = mw.json_body()
    submitted_to = mw.v_enum(body, "submitted_to", SUBMISSION_TARGETS)
    submission_reference = mw.v_str(body, "submission_reference", allow_empty=False)

    report = mw.fetch(db.rocs, row_id, "ERR_ROC_NOT_FOUND")
    engagement = db.engagements.get(report.get("engagement_id"))
    mw.require_lead(engagement, user_id)

    if report.get("status") != "ATTESTED":
        raise ApiError("ERR_INVALID_ROC_STATE")

    report["status"] = "SUBMITTED"
    report["submitted_to"] = submitted_to
    report["submission_reference"] = submission_reference
    db.touch(report)

    engagement["status"] = "SUBMITTED"
    # An accelerated due date is never pushed back out again (PRD 3.9).
    if not derive.reassessment_required(engagement["id"]):
        engagement["reassessment_due_date"] = fmt_day(
            db.today() + timedelta(days=calc.REASSESSMENT_INTERVAL_DAYS))
    db.touch(engagement)
    return single(serialize.roc_report(report))
