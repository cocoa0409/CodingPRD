"""Existence lookups returning the row or raising the type-specific not-found
error (PRD §2.4)."""

import db
from errors import err


def get_fund(fund_id):
    row = db.funds.get(fund_id)
    if row is None:
        raise err("ERR_FUND_NOT_FOUND", "ScholarshipFund not found")
    return row


def get_criteria(criteria_id):
    row = db.criteria.get(criteria_id)
    if row is None:
        raise err("ERR_CRITERIA_NOT_FOUND", "EligibilityCriteria not found")
    return row


def get_applicant(applicant_id):
    row = db.applicants.get(applicant_id)
    if row is None:
        raise err("ERR_APPLICANT_NOT_FOUND", "Applicant not found")
    return row


def get_application(application_id):
    row = db.applications.get(application_id)
    if row is None:
        raise err("ERR_APPLICATION_NOT_FOUND", "Application not found")
    return row


def get_committee_member(member_id):
    row = db.committee_members.get(member_id)
    if row is None:
        raise err("ERR_COMMITTEE_MEMBER_NOT_FOUND", "CommitteeMember not found")
    return row


def get_assignment(assignment_id):
    row = db.committee_assignments.get(assignment_id)
    if row is None:
        raise err("ERR_ASSIGNMENT_NOT_FOUND", "CommitteeAssignment not found")
    return row


def get_score(score_id):
    row = db.rubric_scores.get(score_id)
    if row is None:
        raise err("ERR_SCORE_NOT_FOUND", "RubricScore not found")
    return row


def get_award(award_id):
    row = db.awards.get(award_id)
    if row is None:
        raise err("ERR_AWARD_NOT_FOUND", "Award not found")
    return row


def get_disbursement(disbursement_id):
    row = db.disbursements.get(disbursement_id)
    if row is None:
        raise err("ERR_DISBURSEMENT_NOT_FOUND", "Disbursement not found")
    return row


def get_renewal(review_id):
    row = db.renewal_reviews.get(review_id)
    if row is None:
        raise err("ERR_RENEWAL_NOT_FOUND", "RenewalReview not found")
    return row


def get_stewardship(stewardship_id):
    row = db.stewardship_records.get(stewardship_id)
    if row is None:
        raise err("ERR_STEWARDSHIP_NOT_FOUND", "StewardshipRecord not found")
    return row


def criteria_for_fund(fund_id):
    for c in db.criteria.values():
        if c["fund_id"] == fund_id:
            return c
    return None


def paginate(items, limit, offset):
    """Sort by created_at asc (tie-break by creation sequence), then slice.
    Returns (page_items, pagination_meta)."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
