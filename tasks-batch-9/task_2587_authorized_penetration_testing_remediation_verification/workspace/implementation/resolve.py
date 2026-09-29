"""Bands 2 and 4: path identifiers and body foreign keys (PRD 2.8).

Path identifiers resolve strictly left to right and the leftmost failure is the
one reported.  Body foreign keys resolve in the order PRD 2.8 lists them.
"""
from errors import ApiError
from store import store
from validate import pagination
from envelope import array_response
from core import ordered

_TABLES = (
    ("asset", "assets", "ERR_ASSET_NOT_FOUND"),
    ("test_plan", "test_plans", "ERR_TEST_PLAN_NOT_FOUND"),
    ("scope_item", "scope_items", "ERR_SCOPE_ITEM_NOT_FOUND"),
    ("engagement", "engagements", "ERR_ENGAGEMENT_NOT_FOUND"),
    ("roe", "roes", "ERR_ROE_NOT_FOUND"),
    ("target", "targets", "ERR_TARGET_NOT_FOUND"),
    ("tester", "testers", "ERR_TESTER_NOT_FOUND"),
    ("assignment", "assignments", "ERR_ASSIGNMENT_NOT_FOUND"),
    ("finding", "findings", "ERR_FINDING_NOT_FOUND"),
    ("alert", "alerts", "ERR_ALERT_NOT_FOUND"),
    ("remediation", "remediations", "ERR_REMEDIATION_NOT_FOUND"),
    ("retest", "retests", "ERR_RETEST_NOT_FOUND"),
    ("training", "training", "ERR_TRAINING_RECOMMENDATION_NOT_FOUND"),
)


def _make(table, error_id):
    def getter(record_id):
        record = getattr(store, table).get(record_id)
        if record is None:
            raise ApiError(error_id)
        return record

    return getter


get_asset = _make("assets", "ERR_ASSET_NOT_FOUND")
get_test_plan = _make("test_plans", "ERR_TEST_PLAN_NOT_FOUND")
get_scope_item = _make("scope_items", "ERR_SCOPE_ITEM_NOT_FOUND")
get_engagement = _make("engagements", "ERR_ENGAGEMENT_NOT_FOUND")
get_roe = _make("roes", "ERR_ROE_NOT_FOUND")
get_target = _make("targets", "ERR_TARGET_NOT_FOUND")
get_tester = _make("testers", "ERR_TESTER_NOT_FOUND")
get_assignment = _make("assignments", "ERR_ASSIGNMENT_NOT_FOUND")
get_finding = _make("findings", "ERR_FINDING_NOT_FOUND")
get_alert = _make("alerts", "ERR_ALERT_NOT_FOUND")
get_remediation = _make("remediations", "ERR_REMEDIATION_NOT_FOUND")
get_retest = _make("retests", "ERR_RETEST_NOT_FOUND")
get_training = _make("training", "ERR_TRAINING_RECOMMENDATION_NOT_FOUND")


def paginate(records, serializer, presorted=False):
    """PRD 2.3: limit/offset validated in band 3, created_at ascending by default."""
    limit, offset = pagination()
    rows = records if presorted else ordered(records)
    total = len(rows)
    page = rows[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return array_response([serializer(row) for row in page], 200, meta)


def filtered(records, **filters):
    """Apply optional equality filters from the query string."""
    rows = list(records)
    for field, value in filters.items():
        if value is None:
            continue
        rows = [row for row in rows if row.get(field) == value]
    return rows
