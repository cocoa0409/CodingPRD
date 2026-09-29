"""S-3 wage index collection, the occupational mix survey and desk review (PRD 3.5)."""

from decimal import Decimal

from flask import Blueprint, request

import errors
import services.calc as calc
from arith import F, rhu_int
from common import (READ_ROLES, body, check_scope, endpoint, find, ok_list_of, pagination, public,
                    require_editable)
from db import db, new_row, occ_of, submissions_of, touch
from response import ok
from validators import query_enum

bp = Blueprint("wage", __name__)

SUBMISSION_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "CHANGE_REQUESTED", "ACCEPTED",
                       "REJECTED")
OCC_CATEGORIES = ("RN", "LPN", "NURSE_AIDE", "MEDICAL_ASSISTANT", "NURSE_PRACTITIONER")
DECISIONS = ("ACCEPT", "REQUEST_CHANGE", "REJECT")
EDITABLE_SUBMISSION_STATUSES = ("DRAFT", "CHANGE_REQUESTED")


def _report_of(submission):
    return db.cost_reports[submission["cost_report_id"]]


def _touch_once(row, before_version):
    if row["version"] == before_version:
        touch(row)


# ----------------------------------------------------- WageIndexSubmission
@bp.post("/cost-reports/<report_id>/wage-index-submissions")
@endpoint(roles=["ReimbursementAnalyst"])
def create_submission(report_id):
    payload = body()
    total_salaries = payload.integer("total_salaries_cents", minimum=0)
    total_paid_hours = payload.number("total_paid_hours", places=2, exclusive_minimum=0)
    wage_related = payload.integer("wage_related_costs_cents", required=False, default=0,
                                   minimum=0)
    contract_cents = payload.integer("contract_labor_cents", required=False, default=0, minimum=0)
    contract_hours = payload.number("contract_labor_hours", required=False,
                                    default=Decimal("0.00"), places=2, minimum=0)
    excluded_salaries = payload.integer("excluded_area_salaries_cents", required=False, default=0,
                                        minimum=0)
    excluded_hours = payload.number("excluded_area_hours", required=False, default=Decimal("0.00"),
                                    places=2, minimum=0)

    report = find("CostReport", report_id)
    check_scope(report["provider_id"])
    require_editable(report)
    if calc.active_submission(report["id"]) is not None:
        raise errors.business("ERR_DUPLICATE_CHILD_RECORD",
                             "An open wage index submission already exists for this report.")

    submission = new_row(
        cost_report_id=report["id"],
        status="DRAFT",
        revision_number=0,
        total_salaries_cents=total_salaries,
        total_paid_hours=total_paid_hours,
        wage_related_costs_cents=wage_related,
        contract_labor_cents=contract_cents,
        contract_labor_hours=contract_hours,
        excluded_area_salaries_cents=excluded_salaries,
        excluded_area_hours=excluded_hours,
        allowed_wage_related_costs_cents=0,
        unadjusted_ahw_cents=0,
        occ_mix_adjusted_ahw_cents=None,
        occ_mix_category_count=0,
        effective_ahw_cents=0,
        reported_hours_total=Decimal("0.00"),
        review_note=None,
    )
    db.wage_index_submissions[submission["id"]] = submission
    return ok(public(submission), 201)


@bp.get("/wage-index-submissions/<submission_id>")
@endpoint(roles=list(READ_ROLES))
def read_submission(submission_id):
    return ok(public(find("WageIndexSubmission", submission_id)))


@bp.get("/cost-reports/<report_id>/wage-index-submissions")
@endpoint(roles=list(READ_ROLES))
def list_submissions(report_id):
    limit, offset = pagination()
    status = query_enum(request.args, "status", SUBMISSION_STATUSES)
    report = find("CostReport", report_id)
    rows = submissions_of(report["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list_of(rows, limit, offset)


@bp.patch("/wage-index-submissions/<submission_id>")
@endpoint(roles=["ReimbursementAnalyst"])
def correct_submission(submission_id):
    payload = body()
    total_salaries = payload.integer("total_salaries_cents", required=False, default=None,
                                    minimum=0)
    total_paid_hours = payload.number("total_paid_hours", required=False, default=None, places=2,
                                      exclusive_minimum=0)
    wage_related = payload.integer("wage_related_costs_cents", required=False, default=None,
                                   minimum=0)
    contract_cents = payload.integer("contract_labor_cents", required=False, default=None,
                                     minimum=0)
    contract_hours = payload.number("contract_labor_hours", required=False, default=None,
                                    places=2, minimum=0)
    excluded_salaries = payload.integer("excluded_area_salaries_cents", required=False,
                                        default=None, minimum=0)
    excluded_hours = payload.number("excluded_area_hours", required=False, default=None, places=2,
                                    minimum=0)

    submission = find("WageIndexSubmission", submission_id)
    report = _report_of(submission)
    check_scope(report["provider_id"])
    require_editable(report)
    if submission["status"] not in EDITABLE_SUBMISSION_STATUSES:
        raise errors.invalid_state(
            "A submission in %s may not be corrected." % submission["status"])

    supplied = {
        "total_salaries_cents": total_salaries,
        "total_paid_hours": total_paid_hours,
        "wage_related_costs_cents": wage_related,
        "contract_labor_cents": contract_cents,
        "contract_labor_hours": contract_hours,
        "excluded_area_salaries_cents": excluded_salaries,
        "excluded_area_hours": excluded_hours,
    }
    before = submission["version"]
    for key, value in supplied.items():
        if value is not None:
            submission[key] = value
    calc.recompute_ahw(submission)
    _touch_once(submission, before)
    return ok(public(submission))


@bp.post("/wage-index-submissions/<submission_id>/submit")
@endpoint(roles=["ReimbursementManager"])
def submit_submission(submission_id):
    submission = find("WageIndexSubmission", submission_id)
    report = _report_of(submission)
    check_scope(report["provider_id"])

    if submission["status"] not in EDITABLE_SUBMISSION_STATUSES:
        raise errors.invalid_state(
            "A submission in %s may not be submitted." % submission["status"])
    responses = occ_of(submission["id"])
    if submission["status"] == "DRAFT" and not responses:
        raise errors.invalid_state(
            "The occupational mix survey has no responses yet.")
    if calc.reported_hours_total(submission) > F(submission["total_paid_hours"]):
        raise errors.business("ERR_OCC_MIX_HOURS_EXCEED_TOTAL",
                             "Reported occupational mix hours exceed total paid hours.")

    before = submission["version"]
    calc.recompute_ahw(submission)
    if submission["status"] == "CHANGE_REQUESTED":
        submission["revision_number"] = submission["revision_number"] + 1
    submission["status"] = "SUBMITTED"
    _touch_once(submission, before)

    report["wage_data_status"] = "COLLECTED"
    touch(report)
    return ok(public(submission))


@bp.post("/wage-index-submissions/<submission_id>/start-review")
@endpoint(roles=["MacAuditor"])
def start_review(submission_id):
    submission = find("WageIndexSubmission", submission_id)
    report = _report_of(submission)
    if submission["status"] not in ("SUBMITTED", "ACCEPTED"):
        raise errors.invalid_state(
            "A submission in %s may not enter desk review." % submission["status"])
    if submission["status"] == "ACCEPTED" and report["status"] == "CLOSED":
        raise errors.invalid_state("The cost report is CLOSED; desk review cannot be re-opened.")

    submission["status"] = "UNDER_REVIEW"
    touch(submission)
    report["wage_data_status"] = "UNDER_REVIEW"
    touch(report)
    return ok(public(submission))


@bp.post("/wage-index-submissions/<submission_id>/review-decision")
@endpoint(roles=["MacAuditor"])
def review_decision(submission_id):
    payload = body()
    decision = payload.enum("decision", DECISIONS)
    review_note = payload.string("review_note")

    submission = find("WageIndexSubmission", submission_id)
    report = _report_of(submission)
    if submission["status"] != "UNDER_REVIEW":
        raise errors.invalid_state(
            "A submission in %s has no review decision to record." % submission["status"])
    if decision == "REJECT" and report["status"] != "DRAFT":
        raise errors.invalid_state(
            "The wage data may only be rejected while the report is DRAFT.")

    if decision == "ACCEPT":
        active = [r for r in occ_of(submission["id"]) if F(r["reported_hours"]) > 0]
        if len(active) < calc.OCC_MIX_MIN_CATEGORIES:
            raise errors.business("ERR_OCC_MIX_INCOMPLETE",
                                 "At least three staffed occupational mix categories are needed.")
        if calc.reported_hours_total(submission) > F(submission["total_paid_hours"]):
            raise errors.business("ERR_OCC_MIX_HOURS_EXCEED_TOTAL",
                                 "Reported occupational mix hours exceed total paid hours.")

    if decision == "ACCEPT":
        submission["status"] = "ACCEPTED"
        report["wage_data_status"] = "VERIFIED"
    elif decision == "REQUEST_CHANGE":
        submission["status"] = "CHANGE_REQUESTED"
        report["wage_data_status"] = "REVISION_REQUESTED"
    else:
        submission["status"] = "REJECTED"
        report["wage_data_status"] = "REJECTED"
    submission["review_note"] = review_note
    touch(submission)
    touch(report)
    return ok(public(submission))


# ---------------------------------------------------------- OccMixResponse
@bp.post("/wage-index-submissions/<submission_id>/occ-mix-responses")
@endpoint(roles=["ReimbursementAnalyst"])
def create_occ_mix_response(submission_id):
    payload = body()
    category = payload.enum("category", OCC_CATEGORIES)
    reported_hours = payload.number("reported_hours", places=2, minimum=0)
    reported_salaries = payload.integer("reported_salaries_cents", minimum=0)

    submission = find("WageIndexSubmission", submission_id)
    report = _report_of(submission)
    check_scope(report["provider_id"])
    if submission["status"] not in EDITABLE_SUBMISSION_STATUSES:
        raise errors.invalid_state(
            "A submission in %s no longer accepts survey responses." % submission["status"])

    existing = occ_of(submission["id"])
    for other in existing:
        if other["category"] == category:
            raise errors.business("ERR_OCC_MIX_CATEGORY_DUPLICATE",
                                 "That occupational mix category is already recorded.")
    projected = calc.reported_hours_total(submission) + F(reported_hours)
    if projected > F(submission["total_paid_hours"]):
        raise errors.business("ERR_OCC_MIX_HOURS_EXCEED_TOTAL",
                             "Reported occupational mix hours exceed total paid hours.")

    category_ahw = None
    if F(reported_hours) != 0:
        category_ahw = rhu_int(F(reported_salaries) / F(reported_hours))
    response = new_row(
        wage_index_submission_id=submission["id"],
        category=category,
        reported_hours=reported_hours,
        reported_salaries_cents=reported_salaries,
        category_ahw_cents=category_ahw,
    )
    db.occ_mix_responses[response["id"]] = response

    calc.recompute_ahw(submission)
    return ok(public(response), 201)


@bp.get("/wage-index-submissions/<submission_id>/occ-mix-responses")
@endpoint(roles=list(READ_ROLES))
def list_occ_mix_responses(submission_id):
    limit, offset = pagination()
    category = query_enum(request.args, "category", OCC_CATEGORIES)
    submission = find("WageIndexSubmission", submission_id)
    rows = occ_of(submission["id"])
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    return ok_list_of(rows, limit, offset)


@bp.get("/occ-mix-responses/<response_id>")
@endpoint(roles=list(READ_ROLES))
def read_occ_mix_response(response_id):
    return ok(public(find("OccMixResponse", response_id)))
