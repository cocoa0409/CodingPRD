"""Identifier resolution helpers; each returns its own not-found code (PRD 2.10)."""
import store
from errors import ApiError


def _get(bucket, row_id, error_id, label):
    row = bucket.get(row_id)
    if row is None:
        raise ApiError(error_id, "No %s exists with id %s." % (label, row_id))
    return row


def sponsor(row_id):
    return _get(store.sponsors, row_id, "ERR_SPONSOR_NOT_FOUND", "sponsor")


def permittee(row_id):
    return _get(store.permittees, row_id, "ERR_PERMITTEE_NOT_FOUND", "permittee")


def irt_member(row_id):
    return _get(store.irt_members, row_id, "ERR_IRT_MEMBER_NOT_FOUND", "review-team member")


def bank(row_id):
    return _get(store.banks, row_id, "ERR_BANK_NOT_FOUND", "mitigation bank")


def prospectus(row_id):
    return _get(store.prospectuses, row_id, "ERR_PROSPECTUS_NOT_FOUND", "prospectus")


def work_plan(row_id):
    return _get(store.work_plans, row_id, "ERR_WORK_PLAN_NOT_FOUND", "work plan")


def milestone(row_id):
    return _get(store.milestones, row_id, "ERR_MILESTONE_NOT_FOUND", "release milestone")


def monitoring_report(row_id):
    return _get(store.monitoring_reports, row_id, "ERR_MONITORING_REPORT_NOT_FOUND",
                "monitoring report")


def remedial_action(row_id):
    return _get(store.remedial_actions, row_id, "ERR_REMEDIAL_ACTION_NOT_FOUND",
                "remedial action")


def credit_sale(row_id):
    return _get(store.credit_sales, row_id, "ERR_CREDIT_SALE_NOT_FOUND", "credit sale")
