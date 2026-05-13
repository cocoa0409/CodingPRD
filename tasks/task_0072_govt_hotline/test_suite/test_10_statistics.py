"""Statistics endpoints — satisfaction index, breach rate, and trend.

PRD §3.14.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    PA, SA, SUP,
    respond_survey_payload,
    setup_three_resolved_with_surveys,
    validate_success,
)


# ===========================================================================
# Satisfaction index baseline behaviours (PRD §3.14)
# ===========================================================================
class TestSatisfactionIndex:
    """PRD §3.14: 'The satisfaction index aggregates over the universe
    of work orders whose status is one of FOLLOWED_UP, CLOSED, or
    REOPENED, optionally constrained by a period_start and period_end
    filter.'"""

    def test_supervisor_can_read_stats_satisfaction(self, api):
        """PRD §4: 'GET /stats/satisfaction — ... — PlatformAdmin,
        Supervisor.'"""
        world = setup_three_resolved_with_surveys(
            scores_for_handler_a=[5], scores_for_handler_b=[],
        )
        resp = api.stats_satisfaction(SUP, params={
            "group_by": "department",
            "department_id": world["lead_department"]["id"],
        })
        validate_success(resp)

    def test_score_5_yields_index_5_00(self, api):
        """PRD §3.14: 'If that latest survey is in RESPONDED, the work
        order contributes its survey score.'

        Single RESPONDED survey with score=5 → mean = 5/1 = 5.00.
        """
        world = setup_three_resolved_with_surveys(
            scores_for_handler_a=[5], scores_for_handler_b=[],
        )
        resp = api.stats_satisfaction(PA, params={
            "group_by": "department",
            "department_id": world["lead_department"]["id"],
        })
        data = validate_success(resp)
        index = (
            data.get("satisfaction_index")
            if isinstance(data, dict) else None
        )
        if index is None and isinstance(data, dict):
            groups = data.get("groups") or data.get("results") or []
            if groups:
                index = groups[0].get("satisfaction_index")
        assert index is not None
        assert abs(float(index) - 5.00) < 0.005, (
            f"PRD §3.14: single score=5 gives 5.00; got {index}"
        )


# ===========================================================================
# Breach rate (PRD §3.14)
# ===========================================================================
class TestBreachRate:
    """PRD §3.14: 'The breach-rate endpoint accepts period_start,
    period_end, optional group_by (department or category),
    department_id, and category_code filters and produces two rates.'"""

    def test_breach_rate_endpoint_callable_by_supervisor(self, api):
        """PRD §4: 'GET /stats/breach-rate — ... — PlatformAdmin,
        Supervisor.'"""
        resp = api.stats_breach_rate(SUP, params={
            "period_start": "2020-01-01T00:00:00.000Z",
            "period_end": "2030-12-31T23:59:59.999Z",
        })
        validate_success(resp)


# ===========================================================================
# Trend (PRD §3.14)
# ===========================================================================
class TestTrend:
    """PRD §3.14: 'The trend endpoint accepts period_start, period_end,
    and a bucket size, and returns counts of work orders in each bucket
    for the lifecycle marker events REGISTERED, RESOLVED, CLOSED, and
    REOPENED.'"""

    def test_trend_endpoint_callable(self, api):
        """PRD §4: 'GET /stats/trend — Public-disclosure trend report
        — PlatformAdmin, Supervisor.'"""
        resp = api.stats_trend(PA, params={
            "period_start": "2020-01-01T00:00:00.000Z",
            "period_end": "2030-12-31T23:59:59.999Z",
            "bucket": "month",
        })
        validate_success(resp)
