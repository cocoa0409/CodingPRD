"""Path/body lookups (ladder tiers 4-5) and the list-endpoint shortcut."""

from db import db
from errors import fail
from middleware import apply_filters, pagination
from response import array_response


def _find(store, rec_id, error_id):
    if not isinstance(rec_id, str):
        fail(error_id, "resource not found")
    rec = store.get(rec_id)
    if rec is None:
        fail(error_id, "resource %s does not exist" % rec_id)
    return rec


def cycle_or_404(rec_id):
    return _find(db.cycles, rec_id, "ERR_CYCLE_NOT_FOUND")


def scenario_or_404(rec_id):
    return _find(db.scenarios, rec_id, "ERR_SCENARIO_NOT_FOUND")


def source_or_404(rec_id):
    return _find(db.sources, rec_id, "ERR_SOURCE_NOT_FOUND")


def adjustment_or_404(rec_id):
    return _find(db.adjustments, rec_id, "ERR_ADJUSTMENT_NOT_FOUND")


def item_or_404(rec_id):
    return _find(db.items, rec_id, "ERR_ONE_TIME_ITEM_NOT_FOUND")


def round_or_404(rec_id):
    return _find(db.rounds, rec_id, "ERR_ROUND_NOT_FOUND")


def estimate_or_404(rec_id):
    return _find(db.estimates, rec_id, "ERR_ESTIMATE_NOT_FOUND")


def disagreement_or_404(rec_id):
    return _find(db.disagreements, rec_id, "ERR_DISAGREEMENT_NOT_FOUND")


def fund_or_404(rec_id):
    return _find(db.funds, rec_id, "ERR_FUND_NOT_FOUND")


def transaction_or_404(rec_id):
    return _find(db.transactions, rec_id, "ERR_TRANSACTION_NOT_FOUND")


def request_or_404(rec_id):
    return _find(db.requests, rec_id, "ERR_REQUEST_NOT_FOUND")


def vote_or_404(rec_id):
    return _find(db.votes, rec_id, "ERR_VOTE_NOT_FOUND")


def actual_or_404(rec_id):
    return _find(db.actuals, rec_id, "ERR_ACTUAL_NOT_FOUND")


def briefing_or_404(rec_id):
    return _find(db.briefings, rec_id, "ERR_BRIEFING_NOT_FOUND")


def listing(rows, spec=None):
    """Filter (§2.3 exact match), then paginate; default order is created_at ASC."""
    limit, offset = pagination()
    if spec:
        rows = apply_filters(rows, spec)
    return array_response(rows, limit, offset, len(rows))
