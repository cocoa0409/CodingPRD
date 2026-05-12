"""RankingPeriod creation, close, publish, and ranking-score normalization.

Covers PRD §3.7 — Ranking Periods and Leaderboard Snapshots.
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import (
    ApiErrorId,
    advance_clock,
    close_ranking_period,
    create_ranking_period,
    create_ranking_period_payload,
    make_community_admin_headers,
    publish_ranking_period,
    setup_ranking_window,
    setup_verified_resident,
    submit_disposal,
)


class TestRankingPeriodCreation:
    def test_create_open_with_empty_leaderboard(self, api):
        """PRD §3.7: 'Periods are born OPEN; their leaderboard is the empty
        array; published_at is null.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, _, _ = setup_verified_resident()
        period = create_ranking_period(
            community["id"], "WEEKLY", "HOUSEHOLD",
            "2030-01-01T00:00:00.000Z", "2030-01-08T00:00:00.000Z",
        )
        assert period["status"] == "OPEN"
        assert period["leaderboard"] == []
        assert period["published_at"] is None

    def test_overlapping_period_rejected(self, api):
        """PRD §3.7: 'Within the same (community_id, granularity, dimension)
        triple, period windows must not overlap any existing period ...
        Violations of either constraint are rejected with
        ERR_RANKING_PERIOD_OVERLAP.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, _, _ = setup_verified_resident()
        create_ranking_period(
            community["id"], "WEEKLY", "HOUSEHOLD",
            "2030-01-01T00:00:00.000Z", "2030-01-08T00:00:00.000Z",
        )
        resp = api.create_ranking_period(
            community["id"],
            create_ranking_period_payload(
                "WEEKLY", "HOUSEHOLD",
                "2030-01-05T00:00:00.000Z", "2030-01-12T00:00:00.000Z",
            ),
            make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_RANKING_PERIOD_OVERLAP.value)

    def test_non_contiguous_weekly_period_rejected(self, api):
        """PRD §3.7: 'for WEEKLY and MONTHLY granularities, the new period
        must additionally be contiguous with the immediately prior period,
        meaning its window_start equals the prior period's window_end.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, _, _ = setup_verified_resident()
        create_ranking_period(
            community["id"], "WEEKLY", "HOUSEHOLD",
            "2030-01-01T00:00:00.000Z", "2030-01-08T00:00:00.000Z",
        )
        # Gap of one day -> not contiguous.
        resp = api.create_ranking_period(
            community["id"],
            create_ranking_period_payload(
                "WEEKLY", "HOUSEHOLD",
                "2030-01-09T00:00:00.000Z", "2030-01-16T00:00:00.000Z",
            ),
            make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_RANKING_PERIOD_OVERLAP.value)

    def test_contiguous_weekly_period_succeeds(self, api):
        """PRD §3.7: 'meaning its window_start equals the prior period's
        window_end.' Exactly contiguous is permitted."""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, _, _ = setup_verified_resident()
        create_ranking_period(
            community["id"], "WEEKLY", "HOUSEHOLD",
            "2030-01-01T00:00:00.000Z", "2030-01-08T00:00:00.000Z",
        )
        next_p = create_ranking_period(
            community["id"], "WEEKLY", "HOUSEHOLD",
            "2030-01-08T00:00:00.000Z", "2030-01-15T00:00:00.000Z",
        )
        assert next_p["status"] == "OPEN"


class TestRankingPeriodClose:
    def test_close_before_window_end_yields_not_ended(self, api):
        """PRD §3.7: 'Closing earlier is rejected with
        ERR_RANKING_PERIOD_NOT_ENDED.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, _, _ = setup_verified_resident()
        period = create_ranking_period(
            community["id"], "WEEKLY", "HOUSEHOLD",
            "2030-01-01T00:00:00.000Z", "2030-01-08T00:00:00.000Z",
        )
        # Clock is before window_end.
        resp = api.close_ranking_period(
            community["id"], period["id"], make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_RANKING_PERIOD_NOT_ENDED.value)

    def test_close_empty_window_yields_empty_leaderboard(self, api):
        """PRD §3.7: 'If the eligible subject set is empty (no eligible
        disposals AND no eligible violations), the leaderboard is the empty
        array.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, _, _ = setup_verified_resident()
        period = create_ranking_period(
            community["id"], "WEEKLY", "HOUSEHOLD",
            "2030-01-01T00:00:00.000Z", "2030-01-08T00:00:00.000Z",
        )
        advance_clock("2030-01-08T00:00:01.000Z")
        closed = close_ranking_period(community["id"], period["id"])
        assert closed["status"] == "CLOSED"
        assert closed["leaderboard"] == []

    def test_publish_empty_leaderboard_yields_ranking_empty(self, api):
        """PRD §3.7: 'Publish requires that the period is currently CLOSED
        and that the leaderboard is non-empty (else ERR_RANKING_EMPTY).'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, _, _ = setup_verified_resident()
        period = create_ranking_period(
            community["id"], "WEEKLY", "HOUSEHOLD",
            "2030-01-01T00:00:00.000Z", "2030-01-08T00:00:00.000Z",
        )
        advance_clock("2030-01-08T00:00:01.000Z")
        close_ranking_period(community["id"], period["id"])
        resp = api.publish_ranking_period(
            community["id"], period["id"], make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_RANKING_EMPTY.value)


class TestRankingPublish:
    def test_publish_closed_with_leaderboard_succeeds(self, api):
        """PRD §3.7: 'On publish, the system sets published_at to the
        current logical clock, transitions to PUBLISHED (terminal).'"""
        scenario = setup_ranking_window(
            granularity="WEEKLY", dimension="HOUSEHOLD",
            window_start_iso="2030-02-01T00:00:00.000Z",
            window_end_iso="2030-02-08T00:00:00.000Z",
            base_rate_per_kg=10.00,
        )
        # Submit a disposal in the window.
        submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-02-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=2.0,
        )
        # Advance clock past window_end and close.
        advance_clock("2030-02-08T00:00:01.000Z")
        closed = close_ranking_period(
            scenario["community"]["id"], scenario["period"]["id"],
        )
        assert closed["leaderboard"]
        published = publish_ranking_period(
            scenario["community"]["id"], scenario["period"]["id"],
        )
        assert published["status"] == "PUBLISHED"
        assert published["published_at"] is not None
