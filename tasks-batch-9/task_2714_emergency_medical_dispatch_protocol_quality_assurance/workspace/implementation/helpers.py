"""Shared route helpers: reference resolution (PRD 2.5) and list surfaces (2.3).

Path identifiers are resolved strictly left to right and the first identifier
that does not resolve decides the error, so every route resolves its parents in
path order before it looks at the child.  Pagination shape (ladder step 4) is
checked *before* path existence (step 8), so list handlers read the pagination
parameters first and resolve the path afterwards.
"""
from envelope import ok_list, paginate, public
from errors import fail
from store import db, order_rows


def _find(collection, key, error_id):
    if not isinstance(key, str) or key not in collection:
        fail(error_id)
    return collection[key]


def program(program_id):
    return _find(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")


def protocol_version(version_id):
    return _find(db.protocol_versions, version_id, "ERR_PROTOCOL_VERSION_NOT_FOUND")


def rollout(rollout_id):
    return _find(db.rollouts, rollout_id, "ERR_ROLLOUT_NOT_FOUND")


def dispatcher(dispatcher_id):
    return _find(db.dispatchers, dispatcher_id, "ERR_DISPATCHER_NOT_FOUND")


def call_record(call_record_id):
    return _find(db.call_records, call_record_id, "ERR_CALL_RECORD_NOT_FOUND")


def sampling_period(period_id):
    return _find(db.sampling_periods, period_id, "ERR_SAMPLING_PERIOD_NOT_FOUND")


def review(review_id):
    return _find(db.reviews, review_id, "ERR_REVIEW_NOT_FOUND")


def rebuttal(rebuttal_id):
    return _find(db.rebuttals, rebuttal_id, "ERR_REBUTTAL_NOT_FOUND")


def high_risk_review(hrcr_id):
    return _find(db.high_risk_reviews, hrcr_id, "ERR_HIGH_RISK_REVIEW_NOT_FOUND")


def coaching_plan(plan_id):
    return _find(db.coaching_plans, plan_id, "ERR_COACHING_PLAN_NOT_FOUND")


def retraining_session(session_id):
    return _find(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")


def report(report_id):
    return _find(db.reports, report_id, "ERR_REPORT_NOT_FOUND")


def matches(row, filters):
    """Every supplied filter must match; an omitted filter is ignored."""
    for field, value in filters.items():
        if value is None:
            continue
        if row.get(field) != value:
            return False
    return True


def respond_list(rows, limit, offset):
    """Order by created_at ascending, then window the page (PRD 2.3)."""
    window, total = paginate(order_rows(rows), limit, offset)
    return ok_list([public(row) for row in window], limit, offset, total)
