"""Shared route helpers."""

from flask import request

import db
from errors import fail

PREFIX = "/appraisal-desk"


def find(collection, resource_id, error_id):
    record = collection.get(resource_id)
    if record is None:
        fail(error_id)
    return record


def find_loan(loan_id):
    return find(db.loan_files, loan_id, "ERR_LOAN_FILE_NOT_FOUND")


def find_appraiser(appraiser_id):
    return find(db.appraisers, appraiser_id, "ERR_APPRAISER_NOT_FOUND")


def find_amc(amc_id):
    return find(db.amcs, amc_id, "ERR_AMC_NOT_FOUND")


def find_membership(membership_id):
    return find(db.panel_memberships, membership_id, "ERR_PANEL_MEMBERSHIP_NOT_FOUND")


def find_appraisal(appraisal_id):
    return find(db.appraisals, appraisal_id, "ERR_APPRAISAL_NOT_FOUND")


def find_flag(flag_id):
    return find(db.bias_flags, flag_id, "ERR_BIAS_FLAG_NOT_FOUND")


def find_desk_review(review_id):
    return find(db.desk_reviews, review_id, "ERR_DESK_REVIEW_NOT_FOUND")


def find_order(order_id):
    return find(db.escalation_orders, order_id, "ERR_ESCALATION_ORDER_NOT_FOUND")


def find_rov(rov_id):
    return find(db.rov_requests, rov_id, "ERR_ROV_REQUEST_NOT_FOUND")


def find_dispute(case_id):
    return find(db.dispute_cases, case_id, "ERR_DISPUTE_CASE_NOT_FOUND")


def body_fk(data, field, collection, error_id, required=True):
    """Resolve a body foreign key (ladder rung 7).  Absent or non-string
    values fall through to the body-shape rung."""
    if field not in data or data[field] is None:
        return None
    value = data[field]
    if not isinstance(value, str):
        return None
    record = collection.get(value)
    if record is None:
        fail(error_id)
    return record


def filter_equals(rows, field, param=None):
    """Apply an exact-match query filter when the parameter is supplied."""
    raw = request.args.get(param or field)
    if raw is None:
        return rows
    return [r for r in rows if r.get(field) == raw]


def active_membership(appraiser_id, amc_id, coverage_state=None):
    """An ACTIVE membership for the appraiser on that company's panel.

    ``coverage_state`` narrows the lookup to the full appraiser/company/state
    triple, which is the uniqueness key enrolment enforces.  The eligibility
    gates on delivery and on escalation assignment ask only about the
    appraiser/company pair and so leave it unset.
    """
    for membership in db.panel_memberships.values():
        if (membership["appraiser_id"] == appraiser_id
                and membership["amc_id"] == amc_id
                and membership["status"] == "ACTIVE"
                and (coverage_state is None
                     or membership["coverage_state"] == coverage_state)):
            return membership
    return None
