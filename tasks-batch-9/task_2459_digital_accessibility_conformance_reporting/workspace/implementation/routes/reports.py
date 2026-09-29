"""Conformance report authoring, review, publication and withdrawal (PRD 3.7)."""
from flask import Blueprint, g

from calc import conformance_index, in_scope_components, in_scope_criteria
from db import db, new_row, now_iso, sort_key, touch
from derive import (
    mark_correction_required,
    recompute_product,
    refresh_questionnaire_counters,
)
from errors import ApiError
from middleware import ALL_ROLES, endpoint, require_product_ownership
from response import list_response, obj_response
from serialize import report_out
from validate import (
    PUBLICATION_CHANNELS,
    REPORT_STATES,
    body,
    fk_product,
    fk_standard,
    pagination,
    paginate,
    path_report,
    q_enum,
    q_str,
    v_enum,
    v_int,
    v_str,
)

bp = Blueprint("reports", __name__)

OPEN_REPORT_STATES = ("DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED")


@bp.post("/conformance-reports")
@endpoint(["AccessibilityLead"])
def create_report():
    data = body()
    product = fk_product(data.get("product_id"))       # step 5
    standard = fk_standard(data.get("standard_id"))    # step 5

    v_str(data, "product_id", required=True, min_len=1)
    v_str(data, "standard_id", required=True, min_len=1)
    title = v_str(data, "report_title", required=True, min_len=1, max_len=200)
    expected = v_int(data, "expected_product_version", required=True, min_value=0)

    # step 7: optimistic concurrency on the parent product
    if expected != product["version"]:
        raise ApiError("ERR_STALE_PRODUCT_VERSION",
                       "Product %s is at version %d, not %d"
                       % (product["id"], product["version"], expected))

    # step 33: the report must be written against the product's own standard
    if standard["id"] != product["standard_id"]:
        raise ApiError("ERR_REPORT_STANDARD_MISMATCH",
                       "Product %s is enrolled against standard %s"
                       % (product["id"], product["standard_id"]))

    # step 36: at most one open report per product and standard
    for existing in db.reports.values():
        if (existing["product_id"] == product["id"]
                and existing["standard_id"] == standard["id"]
                and existing["state"] in OPEN_REPORT_STATES):
            raise ApiError("ERR_REPORT_ALREADY_OPEN",
                           "Report %s is already open for this product and standard"
                           % existing["id"])

    row = new_row({
        "product_id": product["id"],
        "standard_id": standard["id"],
        "report_title": title,
        "state": "DRAFT",
        "submitted_by_user_id": None,
        "_submitted_at": None,
        "approved_by_user_id": None,
        "_approved_at": None,
        "change_request_count": 0,
        "pinned_assessment_ids": [],
        "pinned_assessment_versions": [],
        "criterion_support_snapshot": [],
        "conformance_index_certified": None,
        "published_issue_count": 0,
        "publication_channel": None,
        "published_at": None,
        "withdrawal_reason": None,
        "superseded_by_report_id": None,
    })
    db.reports[row["id"]] = row
    touch(product)
    return obj_response(report_out(row), 201)


@bp.get("/conformance-reports/<report_id>")
@endpoint(ALL_ROLES)
def get_report(report_id):
    return obj_response(report_out(path_report(report_id)))


@bp.get("/conformance-reports")
@endpoint(ALL_ROLES)
def list_reports():
    product_id = q_str("product_id")
    standard_id = q_str("standard_id")
    state = q_enum("state", REPORT_STATES)
    superseded_by = q_str("superseded_by_report_id")
    limit, offset = pagination()
    rows = list(db.reports.values())
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if standard_id is not None:
        rows = [r for r in rows if r["standard_id"] == standard_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    if superseded_by is not None:
        rows = [r for r in rows if r["superseded_by_report_id"] == superseded_by]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return list_response([report_out(r) for r in page], limit, offset, total)


@bp.post("/conformance-reports/<report_id>/submit")
@endpoint(["ProductOwner"])
def submit_report(report_id):
    report = path_report(report_id)
    require_product_ownership(report["product_id"])        # step 3
    data = body()
    note = v_str(data, "submission_note", required=True, min_len=1, max_len=2000)

    # step 10: from-state
    if report["state"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_REPORT_NOT_SUBMITTABLE",
                       "Report %s is %s" % (report["id"], report["state"]))

    report["state"] = "IN_REVIEW"
    report["submitted_by_user_id"] = g.user_id
    report["_submitted_at"] = now_iso()
    touch(report)
    return obj_response(report_out(report))


@bp.post("/conformance-reports/<report_id>/request-changes")
@endpoint(["ConformanceReviewer"])
def request_changes(report_id):
    report = path_report(report_id)
    data = body()
    note = v_str(data, "change_request_note", required=True, min_len=1, max_len=2000)

    # step 10: from-state
    if report["state"] != "IN_REVIEW":
        raise ApiError("ERR_REPORT_NOT_IN_REVIEW",
                       "Report %s is %s" % (report["id"], report["state"]))

    report["state"] = "CHANGES_REQUESTED"
    report["change_request_count"] += 1
    report["pinned_assessment_ids"] = []
    report["pinned_assessment_versions"] = []
    touch(report)
    return obj_response(report_out(report))


@bp.post("/conformance-reports/<report_id>/approve")
@endpoint(["ConformanceReviewer"])
def approve_report(report_id):
    report = path_report(report_id)
    data = body()
    note = v_str(data, "approval_note", required=True, min_len=1, max_len=2000)

    # step 10: from-state
    if report["state"] != "IN_REVIEW":
        raise ApiError("ERR_REPORT_NOT_IN_REVIEW",
                       "Report %s is %s" % (report["id"], report["state"]))
    # step 16: segregation of duties against the submitter
    if g.user_id == report["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "User %s may not both submit and approve conformance report %s"
                       % (g.user_id, report["id"]))

    product = db.products[report["product_id"]]
    in_scope_ids = {c["id"] for c in in_scope_components(product)}
    pinned = [a for a in db.assessments.values()
              if a["attestation_state"] == "ATTESTED"
              and a["component_id"] in in_scope_ids]
    pinned.sort(key=sort_key)

    report["state"] = "APPROVED"
    report["approved_by_user_id"] = g.user_id
    report["_approved_at"] = now_iso()
    report["pinned_assessment_ids"] = [a["id"] for a in pinned]
    report["pinned_assessment_versions"] = [a["version"] for a in pinned]
    touch(report)
    return obj_response(report_out(report))


@bp.post("/conformance-reports/<report_id>/publish")
@endpoint(["AccessibilityLead"])
def publish_report(report_id):
    report = path_report(report_id)
    data = body()
    channel = v_enum(data, "publication_channel", PUBLICATION_CHANNELS, required=True)

    product = db.products[report["product_id"]]

    # step 10: from-state
    if report["state"] != "APPROVED":
        raise ApiError("ERR_REPORT_NOT_APPROVED",
                       "Report %s is %s" % (report["id"], report["state"]))
    # step 15: posture gate
    if product["publication_posture"] == "FROZEN":
        raise ApiError("ERR_PRODUCT_POSTURE_FROZEN",
                       "Product %s is FROZEN" % product["id"])

    components = in_scope_components(product)
    criteria = in_scope_criteria(product)
    required_categories = set()
    for criterion in criteria:
        required_categories.update(criterion["disability_categories"])

    # step 18: disability-category validation coverage
    for component in components:
        validated = set(component["validated_disability_categories"])
        if not required_categories.issubset(validated):
            raise ApiError("ERR_DISABILITY_COVERAGE_GAP",
                           "Component %s has not validated every in-scope disability "
                           "category" % component["id"])
    # step 20: design-review sign-off
    for component in components:
        if component["design_review_state"] != "REVIEWED_PASS":
            raise ApiError("ERR_DESIGN_REVIEW_INCOMPLETE",
                           "Component %s is %s"
                           % (component["id"], component["design_review_state"]))
    # step 28: non-empty inventory
    if not components:
        raise ApiError("ERR_NO_IN_SCOPE_COMPONENTS",
                       "Product %s has no in-scope components" % product["id"])
    # step 29: pinned evidence unchanged
    for index, assessment_id in enumerate(report["pinned_assessment_ids"]):
        pinned_row = db.assessments.get(assessment_id)
        if pinned_row is None:
            raise ApiError("ERR_PINNED_ASSESSMENT_CHANGED",
                           "Pinned assessment %s no longer exists" % assessment_id)
        if pinned_row["version"] != report["pinned_assessment_versions"][index]:
            raise ApiError("ERR_PINNED_ASSESSMENT_CHANGED",
                           "Pinned assessment %s has changed" % assessment_id)
        if pinned_row["attestation_state"] != "ATTESTED":
            raise ApiError("ERR_PINNED_ASSESSMENT_CHANGED",
                           "Pinned assessment %s is no longer ATTESTED" % assessment_id)

    certified, _denominator, snapshot = conformance_index(product, "CERTIFIED")

    report["state"] = "PUBLISHED"
    report["publication_channel"] = channel
    report["published_at"] = now_iso()
    report["conformance_index_certified"] = certified
    report["criterion_support_snapshot"] = snapshot

    # supersede the previously published report for this product and standard
    for existing in db.reports.values():
        if existing["id"] == report["id"]:
            continue
        if (existing["product_id"] == report["product_id"]
                and existing["standard_id"] == report["standard_id"]
                and existing["state"] == "PUBLISHED"):
            existing["state"] = "SUPERSEDED"
            existing["superseded_by_report_id"] = report["id"]
            touch(existing)

    # publish the customer-facing known-issue roadmap
    published = 0
    for issue in db.issues.values():
        if issue["product_id"] != product["id"]:
            continue
        if issue["state"] != "COMMITTED" or issue["publish_intent"] != "INCLUDED":
            continue
        issue["state"] = "PUBLISHED_COMMITTED"
        issue["public_target_date"] = issue["target_remediation_date"]
        issue["_public_target_date"] = issue["_target_date"]
        issue["published_report_id"] = report["id"]
        touch(issue)
        published += 1
    report["published_issue_count"] = published
    touch(report)

    recompute_product(product)
    touch(product)
    return obj_response(report_out(report))


@bp.post("/conformance-reports/<report_id>/withdraw")
@endpoint(["AccessibilityLead"])
def withdraw_report(report_id):
    report = path_report(report_id)
    data = body()
    reason = v_str(data, "withdrawal_reason", required=True, min_len=1, max_len=2000)

    # step 10: from-state
    if report["state"] not in ("PUBLISHED", "APPROVED"):
        raise ApiError("ERR_REPORT_NOT_WITHDRAWABLE",
                       "Report %s is %s" % (report["id"], report["state"]))

    was_published = report["state"] == "PUBLISHED"
    report["state"] = "WITHDRAWN"
    report["withdrawal_reason"] = reason
    touch(report)

    product = db.products[report["product_id"]]
    if was_published:
        for issue in db.issues.values():
            if (issue.get("published_report_id") == report["id"]
                    and issue["state"] == "PUBLISHED_COMMITTED"):
                issue["state"] = "COMMITTED"
                issue["public_target_date"] = None
                issue["_public_target_date"] = None
                issue["published_report_id"] = None
                touch(issue)
        for questionnaire in db.questionnaires.values():
            if (questionnaire["report_id"] == report["id"]
                    and questionnaire["accuracy_status"] in ("CURRENT", "STALE")):
                mark_correction_required(questionnaire)
        refresh_questionnaire_counters(product)
        recompute_product(product)
    touch(product)
    return obj_response(report_out(report))
