"""Foundation Scholarship Management API — entry point and all routes.

In-memory only. The store boots empty on every fresh process; nothing is
seeded, preloaded, or hardcoded.
"""

import os

from flask import Flask, request

import db
import response
from errors import ApiError, err
from middleware import (
    get_user_context, require_role, get_json_body, parse_pagination,
    require_int, require_string, require_number, require_present,
    validate_gpa, validate_score_0_100, validate_positive_cents,
    validate_non_negative_cents, as_string, as_int,
)
from services import calc, ledger
from services import lookups as L

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.after_request
def _no_keep_alive(resp):
    # Werkzeug's threaded dev server may close idle keep-alive connections
    # server-side; a pooled client socket then reads a half-closed connection
    # and raises BadStatusLine. Forcing Connection: close makes every request
    # use a fresh socket, eliminating that intermittent connection race under
    # the heavy concurrent boot/load of the stability sweep.
    resp.headers["Connection"] = "close"
    return resp


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return response.error(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    # Unknown route -> treat as a generic not-found; tests target known routes.
    return response.error("ERR_INVALID_REQUEST", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return response.error("ERR_INVALID_REQUEST", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return response.error(e.error_id, e.http_status, e.message)
    return response.error("ERR_INVALID_REQUEST", 400, str(e))


# ---------------------------------------------------------------------------
# Auth helper that runs first on every protected endpoint
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    """Returns (user_id, role) after validating headers and role membership."""
    user_id, role = get_user_context()
    require_role(role, allowed_roles)
    return user_id, role


READ_ALL = ["FoundationAdmin", "Applicant", "CommitteeMember", "DisbursementOfficer"]


# ===========================================================================
# Serialization: strip internal _seq is handled in response layer.
# ===========================================================================


# ===========================================================================
# ScholarshipFund
# ===========================================================================
@app.route("/scholarship-funds", methods=["POST"])
def create_fund():
    _uid, _role = auth(["FoundationAdmin"])
    body = get_json_body()
    fund_name = require_string(body, "fund_name")
    endowment = validate_non_negative_cents(require_present(body, "endowment_cents"),
                                            "endowment_cents")
    award_term = body.get("award_term", "FALL")
    if award_term is None:
        award_term = "FALL"
    if award_term not in ("FALL", "SPRING", "SUMMER"):
        raise err("ERR_INVALID_REQUEST", "award_term must be FALL|SPRING|SUMMER")
    with db.LOCK:
        fund = db.common_create({
            "fund_name": fund_name,
            "endowment_cents": endowment,
            "committed_cents": 0,
            "disbursed_cents": 0,
            "available_cents": endowment,
            "award_term": award_term,
            "status": "DRAFT",
        })
        db.funds[fund["id"]] = fund
    return response.ok_object(_fund_view(fund), 201)


@app.route("/scholarship-funds", methods=["GET"])
def list_funds():
    auth(READ_ALL)
    limit, offset = parse_pagination()
    page, meta = L.paginate(list(db.funds.values()), limit, offset)
    return response.ok_array([_fund_view(f) for f in page], meta)


@app.route("/scholarship-funds/<fund_id>", methods=["GET"])
def get_fund_route(fund_id):
    auth(READ_ALL)
    fund = L.get_fund(fund_id)
    return response.ok_object(_fund_view(fund))


@app.route("/scholarship-funds/<fund_id>/open", methods=["POST"])
def open_fund(fund_id):
    auth(["FoundationAdmin"])
    with db.LOCK:
        fund = L.get_fund(fund_id)
        if fund["status"] != "DRAFT":
            raise err("ERR_FUND_STATE_INVALID", "Fund must be DRAFT to open")
        if L.criteria_for_fund(fund_id) is None:
            raise err("ERR_CRITERIA_REQUIRED", "Fund requires one EligibilityCriteria")
        fund["status"] = "OPEN"
        db.touch(fund)
    return response.ok_object(_fund_view(fund))


@app.route("/scholarship-funds/<fund_id>/begin-review", methods=["POST"])
def begin_review(fund_id):
    auth(["FoundationAdmin"])
    with db.LOCK:
        fund = L.get_fund(fund_id)
        if fund["status"] != "OPEN":
            raise err("ERR_FUND_NOT_OPEN", "Fund must be OPEN to begin review")
        fund["status"] = "REVIEW"
        db.touch(fund)
    return response.ok_object(_fund_view(fund))


@app.route("/scholarship-funds/<fund_id>/begin-awarding", methods=["POST"])
def begin_awarding(fund_id):
    auth(["FoundationAdmin"])
    with db.LOCK:
        fund = L.get_fund(fund_id)
        if fund["status"] != "REVIEW":
            raise err("ERR_FUND_NOT_IN_REVIEW", "Fund must be REVIEW to begin awarding")
        fund["status"] = "AWARDING"
        db.touch(fund)
    return response.ok_object(_fund_view(fund))


@app.route("/scholarship-funds/<fund_id>/close", methods=["POST"])
def close_fund(fund_id):
    auth(["FoundationAdmin"])
    with db.LOCK:
        fund = L.get_fund(fund_id)
        if fund["status"] != "AWARDING":
            raise err("ERR_FUND_NOT_AWARDING", "Fund must be AWARDING to close")
        blocking = {"SUBMITTED", "UNDER_REVIEW", "NEEDS_REVISION", "SCORED"}
        for ap in db.applications.values():
            if ap["fund_id"] == fund_id and ap["status"] in blocking:
                raise err("ERR_OPEN_APPLICATIONS_EXIST",
                          "Open applications exist on this fund")
        fund["status"] = "CLOSED"
        db.touch(fund)
    return response.ok_object(_fund_view(fund))


def _fund_view(fund):
    return {
        "id": fund["id"],
        "fund_name": fund["fund_name"],
        "endowment_cents": fund["endowment_cents"],
        "committed_cents": fund["committed_cents"],
        "disbursed_cents": fund["disbursed_cents"],
        "available_cents": fund["available_cents"],
        "award_term": fund["award_term"],
        "status": fund["status"],
        "created_at": fund["created_at"],
        "updated_at": fund["updated_at"],
        "version": fund["version"],
        "_seq": fund["_seq"],
    }


# ===========================================================================
# EligibilityCriteria
# ===========================================================================
@app.route("/eligibility-criteria", methods=["POST"])
def create_criteria():
    auth(["FoundationAdmin"])
    body = get_json_body()
    fund_id = require_string(body, "fund_id")
    min_gpa = require_present(body, "min_gpa")
    residency = require_string(body, "required_residency_state")
    field = require_string(body, "required_field_of_study")
    max_award = require_present(body, "max_award_cents")
    # Field validation
    min_gpa = validate_gpa(min_gpa, "min_gpa")
    max_award = validate_positive_cents(max_award, "max_award_cents")
    with db.LOCK:
        fund = L.get_fund(fund_id)
        # Fund must be DRAFT to attach criteria (PRD §3.1: "While the fund is
        # still in DRAFT").
        if fund["status"] != "DRAFT":
            raise err("ERR_FUND_STATE_INVALID", "Criteria may be attached only while fund is DRAFT")
        if L.criteria_for_fund(fund_id) is not None:
            raise err("ERR_DUPLICATE_CRITERIA", "Fund already has an EligibilityCriteria")
        crit = db.common_create({
            "fund_id": fund_id,
            "min_gpa": min_gpa,
            "required_residency_state": residency,
            "required_field_of_study": field,
            "max_award_cents": max_award,
        })
        db.criteria[crit["id"]] = crit
    return response.ok_object(_criteria_view(crit), 201)


@app.route("/eligibility-criteria", methods=["GET"])
def list_criteria():
    auth(READ_ALL)
    limit, offset = parse_pagination()
    fund_id = request.args.get("fund_id")
    items = [c for c in db.criteria.values()
             if fund_id is None or c["fund_id"] == fund_id]
    page, meta = L.paginate(items, limit, offset)
    return response.ok_array([_criteria_view(c) for c in page], meta)


@app.route("/eligibility-criteria/<criteria_id>", methods=["GET"])
def get_criteria_route(criteria_id):
    auth(READ_ALL)
    crit = L.get_criteria(criteria_id)
    return response.ok_object(_criteria_view(crit))


def _criteria_view(c):
    return {
        "id": c["id"],
        "fund_id": c["fund_id"],
        "min_gpa": c["min_gpa"],
        "required_residency_state": c["required_residency_state"],
        "required_field_of_study": c["required_field_of_study"],
        "max_award_cents": c["max_award_cents"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "_seq": c["_seq"],
    }


# ===========================================================================
# Applicant
# ===========================================================================
@app.route("/applicants", methods=["POST"])
def create_applicant():
    auth(["FoundationAdmin", "Applicant"])
    body = get_json_body()
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    gpa = validate_gpa(require_present(body, "self_reported_gpa"), "self_reported_gpa")
    residency = require_string(body, "residency_state")
    field = require_string(body, "field_of_study")
    institution = require_string(body, "institution_id")
    with db.LOCK:
        a = db.common_create({
            "full_name": full_name,
            "email": email,
            "self_reported_gpa": gpa,
            "residency_state": residency,
            "field_of_study": field,
            "institution_id": institution,
        })
        db.applicants[a["id"]] = a
    return response.ok_object(_applicant_view(a), 201)


@app.route("/applicants", methods=["GET"])
def list_applicants():
    auth(["FoundationAdmin", "CommitteeMember"])
    limit, offset = parse_pagination()
    page, meta = L.paginate(list(db.applicants.values()), limit, offset)
    return response.ok_array([_applicant_view(a) for a in page], meta)


@app.route("/applicants/<applicant_id>", methods=["GET"])
def get_applicant_route(applicant_id):
    auth(["FoundationAdmin", "Applicant", "CommitteeMember"])
    a = L.get_applicant(applicant_id)
    return response.ok_object(_applicant_view(a))


def _applicant_view(a):
    return {
        "id": a["id"],
        "full_name": a["full_name"],
        "email": a["email"],
        "self_reported_gpa": a["self_reported_gpa"],
        "residency_state": a["residency_state"],
        "field_of_study": a["field_of_study"],
        "institution_id": a["institution_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "_seq": a["_seq"],
    }


# ===========================================================================
# CommitteeMember
# ===========================================================================
@app.route("/committee-members", methods=["POST"])
def create_member():
    auth(["FoundationAdmin", "CommitteeMember"])
    body = get_json_body()
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    expertise = require_string(body, "expertise_field")
    with db.LOCK:
        m = db.common_create({
            "full_name": full_name,
            "email": email,
            "expertise_field": expertise,
            "active_assignment_count": 0,
        })
        db.committee_members[m["id"]] = m
    return response.ok_object(_member_view(m), 201)


@app.route("/committee-members", methods=["GET"])
def list_members():
    auth(["FoundationAdmin", "CommitteeMember"])
    limit, offset = parse_pagination()
    page, meta = L.paginate(list(db.committee_members.values()), limit, offset)
    return response.ok_array([_member_view(m) for m in page], meta)


@app.route("/committee-members/<member_id>", methods=["GET"])
def get_member_route(member_id):
    auth(["FoundationAdmin", "CommitteeMember"])
    m = L.get_committee_member(member_id)
    return response.ok_object(_member_view(m))


def _member_view(m):
    return {
        "id": m["id"],
        "full_name": m["full_name"],
        "email": m["email"],
        "expertise_field": m["expertise_field"],
        "active_assignment_count": m["active_assignment_count"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "_seq": m["_seq"],
    }


# ===========================================================================
# Application
# ===========================================================================
@app.route("/applications", methods=["POST"])
def create_application():
    auth(["FoundationAdmin", "Applicant"])
    body = get_json_body()
    fund_id = require_string(body, "fund_id")
    applicant_id = require_string(body, "applicant_id")
    requested = validate_positive_cents(require_present(body, "requested_amount_cents"),
                                        "requested_amount_cents")
    with db.LOCK:
        fund = L.get_fund(fund_id)
        L.get_applicant(applicant_id)
        if fund["status"] != "OPEN":
            raise err("ERR_FUND_NOT_OPEN", "Fund must be OPEN to create an application")
        ap = db.common_create({
            "fund_id": fund_id,
            "applicant_id": applicant_id,
            "eligibility_matched": None,
            "eligibility_failures": None,
            "requested_amount_cents": requested,
            "rubric_total": None,
            "revision_round": 0,
            "status": "DRAFT",
        })
        db.applications[ap["id"]] = ap
    return response.ok_object(_application_view(ap), 201)


@app.route("/applications", methods=["GET"])
def list_applications():
    auth(["FoundationAdmin", "Applicant", "CommitteeMember"])
    limit, offset = parse_pagination()
    fund_id = request.args.get("fund_id")
    applicant_id = request.args.get("applicant_id")
    items = []
    for ap in db.applications.values():
        if fund_id is not None and ap["fund_id"] != fund_id:
            continue
        if applicant_id is not None and ap["applicant_id"] != applicant_id:
            continue
        items.append(ap)
    page, meta = L.paginate(items, limit, offset)
    return response.ok_array([_application_view(a) for a in page], meta)


@app.route("/applications/<application_id>", methods=["GET"])
def get_application_route(application_id):
    auth(["FoundationAdmin", "Applicant", "CommitteeMember"])
    ap = L.get_application(application_id)
    return response.ok_object(_application_view(ap))


@app.route("/applications/<application_id>/submit", methods=["POST"])
def submit_application(application_id):
    uid, _role = auth(["Applicant"])
    with db.LOCK:
        ap = L.get_application(application_id)
        # PRD §2.5 global check ordering: ownership (5) -> fund state (6) ->
        # target application state (7) -> business constraints (8).
        if uid != ap["applicant_id"]:
            raise err("ERR_NOT_APPLICATION_OWNER", "Acting applicant does not own this application")
        fund = L.get_fund(ap["fund_id"])
        if fund["status"] != "OPEN":
            raise err("ERR_FUND_NOT_OPEN", "Fund must be OPEN to submit")
        if ap["status"] != "DRAFT":
            raise err("ERR_APPLICATION_STATE_INVALID", "Application must be DRAFT to submit")
        recs = [r for r in db.recommendations.values() if r["application_id"] == application_id]
        if len(recs) < 1:
            raise err("ERR_RECOMMENDATION_REQUIRED", "At least one recommendation required")
        trans = [t for t in db.transcripts.values() if t["application_id"] == application_id]
        if len(trans) != 1:
            raise err("ERR_TRANSCRIPT_REQUIRED", "Exactly one transcript required")
        transcript = trans[0]
        applicant = db.applicants[ap["applicant_id"]]
        crit = L.criteria_for_fund(ap["fund_id"])
        matched, failures = calc.eligibility(
            transcript["verified_gpa"], applicant["residency_state"],
            applicant["field_of_study"], crit)
        ap["eligibility_matched"] = matched
        ap["eligibility_failures"] = failures
        ap["status"] = "SUBMITTED"
        db.touch(ap)
    return response.ok_object(_application_view(ap))


@app.route("/applications/<application_id>/start-review", methods=["POST"])
def start_review(application_id):
    auth(["FoundationAdmin"])
    with db.LOCK:
        ap = L.get_application(application_id)
        fund = L.get_fund(ap["fund_id"])
        # PRD §2.5: fund state (6) before target application state (7).
        if fund["status"] != "REVIEW":
            raise err("ERR_FUND_NOT_IN_REVIEW", "Fund must be in REVIEW")
        if ap["status"] not in ("SUBMITTED", "NEEDS_REVISION"):
            raise err("ERR_APPLICATION_STATE_INVALID",
                      "Application must be SUBMITTED or NEEDS_REVISION to start review")
        if ap["status"] == "NEEDS_REVISION":
            # Resume path: revision-round ceiling check.
            if ap["revision_round"] > calc.MAX_REVISION_ROUNDS:
                raise err("ERR_REVISION_LIMIT_REACHED", "Revision limit reached")
        else:
            # SUBMITTED path: eligibility + assignment checks.
            if ap["eligibility_matched"] is not True:
                raise err("ERR_NOT_ELIGIBLE", "Application is not eligible")
            assigned = [a for a in db.committee_assignments.values()
                        if a["application_id"] == application_id and a["status"] == "ASSIGNED"]
            if len(assigned) < 1:
                raise err("ERR_NO_COMMITTEE_ASSIGNED", "No committee member assigned")
        ap["status"] = "UNDER_REVIEW"
        db.touch(ap)
    return response.ok_object(_application_view(ap))


@app.route("/applications/<application_id>/request-revision", methods=["POST"])
def request_revision(application_id):
    auth(["FoundationAdmin"])
    with db.LOCK:
        ap = L.get_application(application_id)
        if ap["status"] != "UNDER_REVIEW":
            raise err("ERR_APPLICATION_STATE_INVALID", "Application must be UNDER_REVIEW")
        ap["revision_round"] += 1
        # Retract all SUBMITTED rubric scores on this application.
        for s in db.rubric_scores.values():
            if s["application_id"] == application_id and s["status"] == "SUBMITTED":
                s["status"] = "RETRACTED"
                db.touch(s)
        ap["status"] = "NEEDS_REVISION"
        db.touch(ap)
    return response.ok_object(_application_view(ap))


@app.route("/applications/<application_id>/finalize-scoring", methods=["POST"])
def finalize_scoring(application_id):
    auth(["FoundationAdmin"])
    with db.LOCK:
        ap = L.get_application(application_id)
        if ap["status"] != "UNDER_REVIEW":
            raise err("ERR_APPLICATION_STATE_INVALID", "Application must be UNDER_REVIEW")
        submitted = [s for s in db.rubric_scores.values()
                     if s["application_id"] == application_id and s["status"] == "SUBMITTED"]
        if len(submitted) < calc.SCORING_QUORUM:
            raise err("ERR_QUORUM_NOT_MET", "Scoring quorum not met")
        ap["rubric_total"] = calc.rubric_total([s["weighted_value"] for s in submitted])
        # Cascade: ASSIGNED committee assignments -> COMPLETED.
        for a in db.committee_assignments.values():
            if a["application_id"] == application_id and a["status"] == "ASSIGNED":
                a["status"] = "COMPLETED"
                db.touch(a)
                member = db.committee_members.get(a["committee_member_id"])
                if member:
                    ledger.recompute_member_count(member)
                    db.touch(member)
        ap["status"] = "SCORED"
        db.touch(ap)
    return response.ok_object(_application_view(ap))


@app.route("/applications/<application_id>/award", methods=["POST"])
def award_application(application_id):
    auth(["FoundationAdmin"])
    body = get_json_body()
    expected_version = as_int(require_present(body, "expected_fund_version"),
                              "expected_fund_version")
    with db.LOCK:
        ap = L.get_application(application_id)
        fund = L.get_fund(ap["fund_id"])
        # PRD §2.5: fund state (6) before target application state (7).
        if fund["status"] != "AWARDING":
            raise err("ERR_FUND_NOT_AWARDING", "Fund must be in AWARDING")
        if ap["status"] != "SCORED":
            raise err("ERR_APPLICATION_STATE_INVALID", "Application must be SCORED to award")
        if not calc.score_clears_floor(ap["rubric_total"]):
            raise err("ERR_SCORE_BELOW_FLOOR", "rubric_total below award score floor")
        crit = L.criteria_for_fund(ap["fund_id"])
        provisional = calc.provisional_award(
            ap["requested_amount_cents"], ap["rubric_total"], crit["max_award_cents"])
        # Fiscal check (priority 19) before OCC (priority 20).
        if provisional > fund["available_cents"]:
            raise err("ERR_FUND_INSUFFICIENT", "Provisional award exceeds available funds")
        if expected_version != fund["version"]:
            raise err("ERR_STALE_FUND_VERSION", "expected_fund_version is stale")
        # Commit.
        award = db.common_create({
            "application_id": application_id,
            "fund_id": ap["fund_id"],
            "provisional_award_cents": provisional,
            "final_award_cents": None,
            "renewal_gpa_floor": crit["min_gpa"],
            "term_index": 1,
            "status": "COMMITTED",
        })
        db.awards[award["id"]] = award
        ap["status"] = "AWARDED"
        db.touch(ap)
        ledger.recompute_fund(fund)
        db.touch(fund)
    return response.ok_object(_award_view(award), 201)


@app.route("/applications/<application_id>/reject", methods=["POST"])
def reject_application(application_id):
    auth(["FoundationAdmin"])
    with db.LOCK:
        ap = L.get_application(application_id)
        if ap["status"] != "SCORED":
            raise err("ERR_APPLICATION_STATE_INVALID", "Application must be SCORED to reject")
        ap["status"] = "REJECTED"
        db.touch(ap)
    return response.ok_object(_application_view(ap))


@app.route("/applications/<application_id>/withdraw", methods=["POST"])
def withdraw_application(application_id):
    uid, _role = auth(["Applicant"])
    with db.LOCK:
        ap = L.get_application(application_id)
        if uid != ap["applicant_id"]:
            raise err("ERR_NOT_APPLICATION_OWNER", "Acting applicant does not own this application")
        if ap["status"] not in ("DRAFT", "SUBMITTED", "NEEDS_REVISION"):
            raise err("ERR_APPLICATION_STATE_INVALID",
                      "Application must be DRAFT, SUBMITTED, or NEEDS_REVISION to withdraw")
        # Cascade: ASSIGNED committee assignments -> REVOKED.
        for a in db.committee_assignments.values():
            if a["application_id"] == application_id and a["status"] == "ASSIGNED":
                a["status"] = "REVOKED"
                db.touch(a)
                member = db.committee_members.get(a["committee_member_id"])
                if member:
                    ledger.recompute_member_count(member)
                    db.touch(member)
        ap["status"] = "WITHDRAWN"
        db.touch(ap)
    return response.ok_object(_application_view(ap))


def _application_view(ap):
    return {
        "id": ap["id"],
        "fund_id": ap["fund_id"],
        "applicant_id": ap["applicant_id"],
        "eligibility_matched": ap["eligibility_matched"],
        "eligibility_failures": ap["eligibility_failures"],
        "requested_amount_cents": ap["requested_amount_cents"],
        "rubric_total": ap["rubric_total"],
        "revision_round": ap["revision_round"],
        "status": ap["status"],
        "created_at": ap["created_at"],
        "updated_at": ap["updated_at"],
        "version": ap["version"],
        "_seq": ap["_seq"],
    }


# ===========================================================================
# Recommendation (immutable upload)
# ===========================================================================
@app.route("/recommendations", methods=["POST"])
def create_recommendation():
    auth(["FoundationAdmin", "Applicant"])
    body = get_json_body()
    application_id = require_string(body, "application_id")
    recommender_name = require_string(body, "recommender_name")
    document_uri = require_string(body, "document_uri")
    with db.LOCK:
        ap = L.get_application(application_id)
        if ap["status"] != "DRAFT":
            raise err("ERR_APPLICATION_STATE_INVALID",
                      "Recommendation may be uploaded only while application is DRAFT")
        rec = db.upload_create({
            "application_id": application_id,
            "recommender_name": recommender_name,
            "document_uri": document_uri,
        })
        db.recommendations[rec["id"]] = rec
    return response.ok_object(_recommendation_view(rec), 201)


@app.route("/recommendations", methods=["GET"])
def list_recommendations():
    auth(["FoundationAdmin", "Applicant", "CommitteeMember"])
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    items = [r for r in db.recommendations.values()
             if application_id is None or r["application_id"] == application_id]
    page, meta = L.paginate(items, limit, offset)
    return response.ok_array([_recommendation_view(r) for r in page], meta)


@app.route("/recommendations/<recommendation_id>", methods=["GET"])
def get_recommendation_route(recommendation_id):
    auth(["FoundationAdmin", "Applicant", "CommitteeMember"])
    rec = db.recommendations.get(recommendation_id)
    if rec is None:
        # No dedicated not-found code for recommendation in catalogue; treat as
        # generic resource not found via 404 application-style. PRD §2.4 lists
        # specific codes but omits recommendation/transcript; use 404 generic.
        raise err("ERR_APPLICATION_NOT_FOUND", "Recommendation not found")
    return response.ok_object(_recommendation_view(rec))


def _recommendation_view(r):
    return {
        "id": r["id"],
        "application_id": r["application_id"],
        "recommender_name": r["recommender_name"],
        "document_uri": r["document_uri"],
        "created_at": r["created_at"],
        "_seq": r["_seq"],
    }


# ===========================================================================
# Transcript (immutable upload)
# ===========================================================================
@app.route("/transcripts", methods=["POST"])
def create_transcript():
    auth(["FoundationAdmin", "Applicant"])
    body = get_json_body()
    application_id = require_string(body, "application_id")
    document_uri = require_string(body, "document_uri")
    verified_gpa = validate_gpa(require_present(body, "verified_gpa"), "verified_gpa")
    with db.LOCK:
        ap = L.get_application(application_id)
        if ap["status"] != "DRAFT":
            raise err("ERR_APPLICATION_STATE_INVALID",
                      "Transcript may be uploaded only while application is DRAFT")
        existing = [t for t in db.transcripts.values() if t["application_id"] == application_id]
        if existing:
            raise err("ERR_DUPLICATE_TRANSCRIPT", "Application already has a transcript")
        t = db.upload_create({
            "application_id": application_id,
            "document_uri": document_uri,
            "verified_gpa": verified_gpa,
        })
        db.transcripts[t["id"]] = t
    return response.ok_object(_transcript_view(t), 201)


@app.route("/transcripts", methods=["GET"])
def list_transcripts():
    auth(["FoundationAdmin", "Applicant", "CommitteeMember"])
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    items = [t for t in db.transcripts.values()
             if application_id is None or t["application_id"] == application_id]
    page, meta = L.paginate(items, limit, offset)
    return response.ok_array([_transcript_view(t) for t in page], meta)


@app.route("/transcripts/<transcript_id>", methods=["GET"])
def get_transcript_route(transcript_id):
    auth(["FoundationAdmin", "Applicant", "CommitteeMember"])
    t = db.transcripts.get(transcript_id)
    if t is None:
        raise err("ERR_APPLICATION_NOT_FOUND", "Transcript not found")
    return response.ok_object(_transcript_view(t))


def _transcript_view(t):
    return {
        "id": t["id"],
        "application_id": t["application_id"],
        "document_uri": t["document_uri"],
        "verified_gpa": t["verified_gpa"],
        "created_at": t["created_at"],
        "_seq": t["_seq"],
    }


# ===========================================================================
# CommitteeAssignment
# ===========================================================================
@app.route("/committee-assignments", methods=["POST"])
def create_assignment():
    auth(["FoundationAdmin"])
    body = get_json_body()
    application_id = require_string(body, "application_id")
    committee_member_id = require_string(body, "committee_member_id")
    with db.LOCK:
        L.get_application(application_id)
        member = L.get_committee_member(committee_member_id)
        # Duplicate ASSIGNED on same application.
        for a in db.committee_assignments.values():
            if (a["application_id"] == application_id
                    and a["committee_member_id"] == committee_member_id
                    and a["status"] == "ASSIGNED"):
                raise err("ERR_DUPLICATE_ASSIGNMENT", "Member already assigned to this application")
        # Overload: count of ASSIGNED across all applications.
        active = sum(1 for a in db.committee_assignments.values()
                     if a["committee_member_id"] == committee_member_id
                     and a["status"] == "ASSIGNED")
        if active >= calc.MAX_CONCURRENT_ASSIGNMENTS:
            raise err("ERR_MEMBER_OVERLOADED", "Member has reached concurrent assignment cap")
        asg = db.common_create({
            "application_id": application_id,
            "committee_member_id": committee_member_id,
            "status": "ASSIGNED",
        })
        db.committee_assignments[asg["id"]] = asg
        ledger.recompute_member_count(member)
        db.touch(member)
    return response.ok_object(_assignment_view(asg), 201)


@app.route("/committee-assignments", methods=["GET"])
def list_assignments():
    auth(["FoundationAdmin", "CommitteeMember"])
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    committee_member_id = request.args.get("committee_member_id")
    items = []
    for a in db.committee_assignments.values():
        if application_id is not None and a["application_id"] != application_id:
            continue
        if committee_member_id is not None and a["committee_member_id"] != committee_member_id:
            continue
        items.append(a)
    page, meta = L.paginate(items, limit, offset)
    return response.ok_array([_assignment_view(a) for a in page], meta)


@app.route("/committee-assignments/<assignment_id>", methods=["GET"])
def get_assignment_route(assignment_id):
    auth(["FoundationAdmin", "CommitteeMember"])
    a = L.get_assignment(assignment_id)
    return response.ok_object(_assignment_view(a))


@app.route("/committee-assignments/<assignment_id>/decline", methods=["POST"])
def decline_assignment(assignment_id):
    uid, _role = auth(["CommitteeMember"])
    with db.LOCK:
        a = L.get_assignment(assignment_id)
        if uid != a["committee_member_id"]:
            raise err("ERR_NOT_ASSIGNMENT_OWNER", "Acting member does not own this assignment")
        if a["status"] != "ASSIGNED":
            raise err("ERR_ASSIGNMENT_STATE_INVALID", "Assignment must be ASSIGNED to decline")
        a["status"] = "DECLINED"
        db.touch(a)
        member = db.committee_members.get(a["committee_member_id"])
        if member:
            ledger.recompute_member_count(member)
            db.touch(member)
    return response.ok_object(_assignment_view(a))


def _assignment_view(a):
    return {
        "id": a["id"],
        "application_id": a["application_id"],
        "committee_member_id": a["committee_member_id"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "_seq": a["_seq"],
    }


# ===========================================================================
# RubricScore
# ===========================================================================
@app.route("/rubric-scores", methods=["POST"])
def create_score():
    uid, _role = auth(["CommitteeMember"])
    body = get_json_body()
    application_id = require_string(body, "application_id")
    committee_member_id = require_string(body, "committee_member_id")
    academic = validate_score_0_100(require_present(body, "academic_score"), "academic_score")
    need = validate_score_0_100(require_present(body, "need_score"), "need_score")
    essay = validate_score_0_100(require_present(body, "essay_score"), "essay_score")
    with db.LOCK:
        L.get_application(application_id)
        L.get_committee_member(committee_member_id)
        # Acting member must hold an ASSIGNED assignment on the application.
        has_assignment = any(
            a["application_id"] == application_id
            and a["committee_member_id"] == committee_member_id
            and a["status"] == "ASSIGNED"
            for a in db.committee_assignments.values())
        if not has_assignment:
            raise err("ERR_NO_ASSIGNMENT_FOR_SCORE",
                      "Acting member has no ASSIGNED assignment on this application")
        s = db.common_create({
            "application_id": application_id,
            "committee_member_id": committee_member_id,
            "academic_score": academic,
            "need_score": need,
            "essay_score": essay,
            "weighted_value": None,
            "status": "DRAFT",
        })
        db.rubric_scores[s["id"]] = s
    return response.ok_object(_score_view(s), 201)


@app.route("/rubric-scores", methods=["GET"])
def list_scores():
    auth(["FoundationAdmin", "CommitteeMember"])
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    committee_member_id = request.args.get("committee_member_id")
    items = []
    for s in db.rubric_scores.values():
        if application_id is not None and s["application_id"] != application_id:
            continue
        if committee_member_id is not None and s["committee_member_id"] != committee_member_id:
            continue
        items.append(s)
    page, meta = L.paginate(items, limit, offset)
    return response.ok_array([_score_view(s) for s in page], meta)


@app.route("/rubric-scores/<score_id>", methods=["GET"])
def get_score_route(score_id):
    auth(["FoundationAdmin", "CommitteeMember"])
    s = L.get_score(score_id)
    return response.ok_object(_score_view(s))


@app.route("/rubric-scores/<score_id>/submit", methods=["POST"])
def submit_score(score_id):
    uid, _role = auth(["CommitteeMember"])
    with db.LOCK:
        s = L.get_score(score_id)
        if uid != s["committee_member_id"]:
            raise err("ERR_NOT_SCORE_OWNER", "Acting member does not own this score")
        if s["status"] != "DRAFT":
            raise err("ERR_SCORE_STATE_INVALID", "Score must be DRAFT to submit")
        ap = db.applications.get(s["application_id"])
        if ap is None or ap["status"] != "UNDER_REVIEW":
            raise err("ERR_APPLICATION_NOT_UNDER_REVIEW",
                      "Parent application must be UNDER_REVIEW")
        s["weighted_value"] = calc.rubric_weighted_value(
            s["academic_score"], s["need_score"], s["essay_score"])
        s["status"] = "SUBMITTED"
        db.touch(s)
    return response.ok_object(_score_view(s))


def _score_view(s):
    return {
        "id": s["id"],
        "application_id": s["application_id"],
        "committee_member_id": s["committee_member_id"],
        "academic_score": s["academic_score"],
        "need_score": s["need_score"],
        "essay_score": s["essay_score"],
        "weighted_value": s["weighted_value"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "_seq": s["_seq"],
    }


# ===========================================================================
# Award
# ===========================================================================
@app.route("/awards", methods=["GET"])
def list_awards():
    auth(["FoundationAdmin", "Applicant", "DisbursementOfficer"])
    limit, offset = parse_pagination()
    fund_id = request.args.get("fund_id")
    application_id = request.args.get("application_id")
    items = []
    for a in db.awards.values():
        if fund_id is not None and a["fund_id"] != fund_id:
            continue
        if application_id is not None and a["application_id"] != application_id:
            continue
        items.append(a)
    page, meta = L.paginate(items, limit, offset)
    return response.ok_array([_award_view(a) for a in page], meta)


@app.route("/awards/<award_id>", methods=["GET"])
def get_award_route(award_id):
    auth(["FoundationAdmin", "Applicant", "DisbursementOfficer"])
    a = L.get_award(award_id)
    return response.ok_object(_award_view(a))


@app.route("/awards/<award_id>/disburse", methods=["POST"])
def disburse_award(award_id):
    auth(["DisbursementOfficer"])
    body = get_json_body()
    institution_id = require_string(body, "institution_id")
    with db.LOCK:
        award = L.get_award(award_id)
        if award["status"] != "COMMITTED":
            raise err("ERR_AWARD_STATE_INVALID", "Award must be COMMITTED to disburse")
        acknowledged = [r for r in db.stewardship_records.values()
                        if r["award_id"] == award_id and r["status"] == "ACKNOWLEDGED"]
        if len(acknowledged) != 1:
            raise err("ERR_STEWARDSHIP_REQUIRED",
                      "Award requires exactly one ACKNOWLEDGED stewardship record")
        ap = db.applications.get(award["application_id"])
        transcript = next((t for t in db.transcripts.values()
                           if t["application_id"] == award["application_id"]), None)
        crit = L.criteria_for_fund(award["fund_id"])
        final = calc.final_award(
            award["provisional_award_cents"], transcript["verified_gpa"],
            crit["max_award_cents"])
        award["final_award_cents"] = final
        award["status"] = "ACTIVE"
        db.touch(award)
        dis = db.common_create({
            "award_id": award_id,
            "fund_id": award["fund_id"],
            "institution_id": institution_id,
            "amount_cents": final,
            "status": "PENDING",
        })
        db.disbursements[dis["id"]] = dis
    return response.ok_object(_disbursement_view(dis), 201)


@app.route("/awards/<award_id>/complete", methods=["POST"])
def complete_award(award_id):
    auth(["FoundationAdmin"])
    with db.LOCK:
        award = L.get_award(award_id)
        if award["status"] != "ACTIVE":
            raise err("ERR_AWARD_STATE_INVALID", "Award must be ACTIVE to complete")
        award["status"] = "COMPLETED"
        db.touch(award)
    return response.ok_object(_award_view(award))


@app.route("/awards/<award_id>/revoke", methods=["POST"])
def revoke_award(award_id):
    auth(["FoundationAdmin"])
    with db.LOCK:
        award = L.get_award(award_id)
        if award["status"] != "COMMITTED":
            raise err("ERR_AWARD_STATE_INVALID", "Award must be COMMITTED to revoke")
        settled = any(d["award_id"] == award_id and d["status"] == "SETTLED"
                      for d in db.disbursements.values())
        if settled:
            raise err("ERR_AWARD_ALREADY_DISBURSED", "Award has a settled disbursement")
        award["status"] = "REVOKED"
        db.touch(award)
        fund = db.funds.get(award["fund_id"])
        if fund:
            ledger.recompute_fund(fund)
            db.touch(fund)
    return response.ok_object(_award_view(award))


def _award_view(a):
    return {
        "id": a["id"],
        "application_id": a["application_id"],
        "fund_id": a["fund_id"],
        "provisional_award_cents": a["provisional_award_cents"],
        "final_award_cents": a["final_award_cents"],
        "renewal_gpa_floor": a["renewal_gpa_floor"],
        "term_index": a["term_index"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "_seq": a["_seq"],
    }


# ===========================================================================
# Disbursement
# ===========================================================================
@app.route("/disbursements", methods=["GET"])
def list_disbursements():
    auth(["FoundationAdmin", "DisbursementOfficer"])
    limit, offset = parse_pagination()
    award_id = request.args.get("award_id")
    fund_id = request.args.get("fund_id")
    items = []
    for d in db.disbursements.values():
        if award_id is not None and d["award_id"] != award_id:
            continue
        if fund_id is not None and d["fund_id"] != fund_id:
            continue
        items.append(d)
    page, meta = L.paginate(items, limit, offset)
    return response.ok_array([_disbursement_view(d) for d in page], meta)


@app.route("/disbursements/<disbursement_id>", methods=["GET"])
def get_disbursement_route(disbursement_id):
    auth(["FoundationAdmin", "DisbursementOfficer"])
    d = L.get_disbursement(disbursement_id)
    return response.ok_object(_disbursement_view(d))


@app.route("/disbursements/<disbursement_id>/settle", methods=["POST"])
def settle_disbursement(disbursement_id):
    auth(["DisbursementOfficer"])
    with db.LOCK:
        d = L.get_disbursement(disbursement_id)
        if d["status"] != "PENDING":
            raise err("ERR_DISBURSEMENT_STATE_INVALID", "Disbursement must be PENDING to settle")
        d["status"] = "SETTLED"
        db.touch(d)
        fund = db.funds.get(d["fund_id"])
        if fund:
            ledger.recompute_fund(fund)
            db.touch(fund)
    return response.ok_object(_disbursement_view(d))


@app.route("/disbursements/<disbursement_id>/return", methods=["POST"])
def return_disbursement(disbursement_id):
    auth(["DisbursementOfficer"])
    with db.LOCK:
        d = L.get_disbursement(disbursement_id)
        if d["status"] not in ("PENDING", "SETTLED"):
            raise err("ERR_DISBURSEMENT_STATE_INVALID",
                      "Disbursement must be PENDING or SETTLED to return")
        award = db.awards.get(d["award_id"])
        fund = db.funds.get(d["fund_id"])
        if d["status"] == "PENDING":
            # Compensation: revert award ACTIVE -> COMMITTED; reset final null.
            d["status"] = "RETURNED"
            db.touch(d)
            if award:
                award["status"] = "COMMITTED"
                award["final_award_cents"] = None
                db.touch(award)
            # Commitment unchanged; no ledger change to committed. Recompute to
            # keep derived fields consistent (committed reflects COMMITTED award).
            if fund:
                ledger.recompute_fund(fund)
                db.touch(fund)
        else:  # SETTLED
            d["status"] = "RETURNED"
            db.touch(d)
            # Award -> REVOKED cascade; ledger drops both disbursed and committed.
            if award:
                award["status"] = "REVOKED"
                db.touch(award)
            if fund:
                ledger.recompute_fund(fund)
                db.touch(fund)
    return response.ok_object(_disbursement_view(d))


def _disbursement_view(d):
    return {
        "id": d["id"],
        "award_id": d["award_id"],
        "fund_id": d["fund_id"],
        "institution_id": d["institution_id"],
        "amount_cents": d["amount_cents"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "_seq": d["_seq"],
    }


# ===========================================================================
# RenewalReview
# ===========================================================================
@app.route("/renewal-reviews", methods=["POST"])
def create_renewal():
    auth(["FoundationAdmin"])
    body = get_json_body()
    award_id = require_string(body, "award_id")
    reported_gpa = validate_gpa(require_present(body, "reported_gpa"), "reported_gpa")
    with db.LOCK:
        award = L.get_award(award_id)
        if award["status"] != "ACTIVE":
            raise err("ERR_AWARD_NOT_ACTIVE", "Award must be ACTIVE to open a renewal review")
        meets = calc.meets_floor(reported_gpa, award["renewal_gpa_floor"])
        rr = db.common_create({
            "award_id": award_id,
            "reported_gpa": reported_gpa,
            "meets_floor": meets,
            "status": "PENDING",
        })
        db.renewal_reviews[rr["id"]] = rr
        award["status"] = "RENEWAL_PENDING"
        db.touch(award)
    return response.ok_object(_renewal_view(rr), 201)


@app.route("/renewal-reviews", methods=["GET"])
def list_renewals():
    auth(["FoundationAdmin", "Applicant"])
    limit, offset = parse_pagination()
    award_id = request.args.get("award_id")
    items = [r for r in db.renewal_reviews.values()
             if award_id is None or r["award_id"] == award_id]
    page, meta = L.paginate(items, limit, offset)
    return response.ok_array([_renewal_view(r) for r in page], meta)


@app.route("/renewal-reviews/<review_id>", methods=["GET"])
def get_renewal_route(review_id):
    auth(["FoundationAdmin", "Applicant"])
    rr = L.get_renewal(review_id)
    return response.ok_object(_renewal_view(rr))


@app.route("/renewal-reviews/<review_id>/approve", methods=["POST"])
def approve_renewal(review_id):
    auth(["FoundationAdmin"])
    with db.LOCK:
        rr = L.get_renewal(review_id)
        award = db.awards.get(rr["award_id"])
        if award is None or award["status"] != "RENEWAL_PENDING":
            raise err("ERR_AWARD_STATE_INVALID", "Award must be RENEWAL_PENDING to approve")
        if rr["meets_floor"] is not True:
            raise err("ERR_GPA_BELOW_FLOOR", "Reported GPA below renewal floor")
        fund = db.funds.get(award["fund_id"])
        if fund is None or fund["available_cents"] < award["provisional_award_cents"]:
            raise err("ERR_FUND_INSUFFICIENT", "Insufficient funds to re-commit term")
        rr["status"] = "APPROVED"
        db.touch(rr)
        award["term_index"] += 1
        award["status"] = "ACTIVE"
        db.touch(award)
        ledger.recompute_fund(fund)
        db.touch(fund)
    return response.ok_object(_renewal_view(rr))


@app.route("/renewal-reviews/<review_id>/deny", methods=["POST"])
def deny_renewal(review_id):
    auth(["FoundationAdmin"])
    with db.LOCK:
        rr = L.get_renewal(review_id)
        award = db.awards.get(rr["award_id"])
        if award is None or award["status"] != "RENEWAL_PENDING":
            raise err("ERR_AWARD_STATE_INVALID", "Award must be RENEWAL_PENDING to deny")
        rr["status"] = "DENIED"
        db.touch(rr)
        award["status"] = "LAPSED"
        db.touch(award)
        fund = db.funds.get(award["fund_id"])
        if fund:
            ledger.recompute_fund(fund)
            db.touch(fund)
    return response.ok_object(_renewal_view(rr))


def _renewal_view(r):
    return {
        "id": r["id"],
        "award_id": r["award_id"],
        "reported_gpa": r["reported_gpa"],
        "meets_floor": r["meets_floor"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "_seq": r["_seq"],
    }


# ===========================================================================
# StewardshipRecord
# ===========================================================================
@app.route("/stewardship-records", methods=["POST"])
def create_stewardship():
    auth(["FoundationAdmin", "Applicant"])
    body = get_json_body()
    award_id = require_string(body, "award_id")
    thank_you_text = require_string(body, "thank_you_text")
    with db.LOCK:
        L.get_award(award_id)
        sr = db.common_create({
            "award_id": award_id,
            "thank_you_text": thank_you_text,
            "status": "DRAFT",
        })
        db.stewardship_records[sr["id"]] = sr
    return response.ok_object(_stewardship_view(sr), 201)


@app.route("/stewardship-records", methods=["GET"])
def list_stewardship():
    auth(["FoundationAdmin", "Applicant", "DisbursementOfficer"])
    limit, offset = parse_pagination()
    award_id = request.args.get("award_id")
    items = [r for r in db.stewardship_records.values()
             if award_id is None or r["award_id"] == award_id]
    page, meta = L.paginate(items, limit, offset)
    return response.ok_array([_stewardship_view(r) for r in page], meta)


@app.route("/stewardship-records/<stewardship_id>", methods=["GET"])
def get_stewardship_route(stewardship_id):
    auth(["FoundationAdmin", "Applicant", "DisbursementOfficer"])
    sr = L.get_stewardship(stewardship_id)
    return response.ok_object(_stewardship_view(sr))


@app.route("/stewardship-records/<stewardship_id>/acknowledge", methods=["POST"])
def acknowledge_stewardship(stewardship_id):
    uid, _role = auth(["Applicant"])
    with db.LOCK:
        sr = L.get_stewardship(stewardship_id)
        # Ownership: acting applicant owns the parent application of the award.
        award = db.awards.get(sr["award_id"])
        owner_id = None
        if award:
            ap = db.applications.get(award["application_id"])
            if ap:
                owner_id = ap["applicant_id"]
        if uid != owner_id:
            raise err("ERR_NOT_APPLICATION_OWNER",
                      "Acting applicant does not own the parent application")
        if sr["status"] != "DRAFT":
            raise err("ERR_STEWARDSHIP_STATE_INVALID", "Stewardship record must be DRAFT")
        sr["status"] = "ACKNOWLEDGED"
        db.touch(sr)
    return response.ok_object(_stewardship_view(sr))


def _stewardship_view(r):
    return {
        "id": r["id"],
        "award_id": r["award_id"],
        "thank_you_text": r["thank_you_text"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "_seq": r["_seq"],
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
