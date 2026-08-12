"""Temporal overlap tests: half-open shift adjacency vs overlap; coverage
window capacity-pool semantics with OPEN/FULL cycling.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    TEST_USERS, make_hospitalist_headers,
    set_clock, create_hospitalist, create_shift, create_coverage_window,
)

ADMIN = TEST_USERS["group_admin_headers"]


class TestShiftHalfOpenAdjacencyAllowed:
    """Difficulty instance: shift_half_open_adjacency_allowed."""

    def test_adjacent_shift_end_equals_start_is_allowed(self, api):
        """PRD §2.8: "Shift and coverage-window intervals are half-open: an
        interval covers the logical time when `start_at` is at or before that
        time and `end_at` is strictly after it. Pure adjacency — one
        interval's `end_at` equal to another's `start_at` — never counts as
        an overlap."
        PRD §3.1: "the new interval must not intersect any existing
        non-closed shift of the same hospitalist, failing with
        `ERR_SHIFT_OVERLAP` (HTTP 409) — pure adjacency, where the new
        `start_at` equals an existing shift's `end_at`, is permitted."

        Design: Difficulty/resource_temporal_overlap/shift_half_open_adjacency_allowed
        """
        h1 = create_hospitalist("H One", "INTERNAL_MEDICINE", max_census_cap=16)
        s1 = create_shift(h1["id"], "DAY", "2026-05-01T07:00:00Z", "2026-05-01T19:00:00Z")
        # Adjacent: start == prior end — permitted
        resp2 = api.create_shift({
            "hospitalist_id": h1["id"], "shift_type": "NIGHT",
            "start_at": "2026-05-01T19:00:00Z", "end_at": "2026-05-02T07:00:00Z",
        }, ADMIN)
        s2 = validate_success(resp2, expected_status=201)
        assert s2["state"] == "SCHEDULED"

    def test_overlapping_shift_rejected_and_list_counted(self, api):
        """PRD §3.1: "the new interval must not intersect any existing
        non-closed shift of the same hospitalist, failing with
        `ERR_SHIFT_OVERLAP` (HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/shift_half_open_adjacency_allowed
        """
        h1 = create_hospitalist("H One", "INTERNAL_MEDICINE", max_census_cap=16)
        create_shift(h1["id"], "DAY", "2026-05-01T07:00:00Z", "2026-05-01T19:00:00Z")
        create_shift(h1["id"], "NIGHT", "2026-05-01T19:00:00Z", "2026-05-02T07:00:00Z")
        # Overlapping: [18:59, 06:00+1d) intersects both prior shifts
        resp = api.create_shift({
            "hospitalist_id": h1["id"], "shift_type": "DAY",
            "start_at": "2026-05-01T18:59:00Z", "end_at": "2026-05-02T06:00:00Z",
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)
        # Exactly two shifts exist for this hospitalist
        list_resp = api.list_shifts(ADMIN, params={"hospitalist_id": h1["id"]})
        rows, meta = validate_paginated(list_resp)
        assert meta["total_count"] == 2


class TestCoverageWindowCapacityPool:
    """Difficulty instance: coverage_window_capacity_pool."""

    def test_enroll_below_capacity_stays_open(self, api):
        """PRD §3.9: "A successful enrollment appends the caller to
        `enrolled_hospitalist_ids` in enrollment order, increments
        `enrolled_count`, and flips the window `OPEN` → `FULL` the moment the
        count reaches capacity."

        Design: Difficulty/resource_temporal_overlap/coverage_window_capacity_pool
        """
        h1 = create_hospitalist("H One", "INTERNAL_MEDICINE", max_census_cap=16)
        h2 = create_hospitalist("H Two", "FAMILY_MEDICINE", max_census_cap=16)
        w = create_coverage_window(window_type="NIGHT_CROSS_COVER", capacity=2)
        r1 = get_success_data(api.enroll_coverage_window(w["id"], make_hospitalist_headers(h1["id"])))
        assert r1["enrolled_count"] == 1
        assert r1["status"] == "OPEN"
        r2 = get_success_data(api.enroll_coverage_window(w["id"], make_hospitalist_headers(h2["id"])))
        assert r2["enrolled_count"] == 2
        assert r2["status"] == "FULL"

    def test_enroll_at_capacity_full_rejected_and_withdraw_reopens(self, api):
        """PRD §3.9: "Capacity, as always, comes last: a window at
        `enrolled_count` equal to `capacity` — status `FULL` — rejects with
        `ERR_COVERAGE_WINDOW_FULL` (HTTP 422)."
        PRD §3.9: "Withdrawal is equally self-service while the window
        remains `OPEN` or `FULL`: the caller is removed from
        `enrolled_hospitalist_ids`, `enrolled_count` decrements, and a `FULL`
        window relaxes back to `OPEN`."

        Design: Difficulty/resource_temporal_overlap/coverage_window_capacity_pool
        """
        h1 = create_hospitalist("H One", "INTERNAL_MEDICINE", max_census_cap=16)
        h2 = create_hospitalist("H Two", "FAMILY_MEDICINE", max_census_cap=16)
        h3 = create_hospitalist("H Three", "ICU", max_census_cap=16)
        w = create_coverage_window(window_type="NIGHT_CROSS_COVER", capacity=2)
        api.enroll_coverage_window(w["id"], make_hospitalist_headers(h1["id"]))
        api.enroll_coverage_window(w["id"], make_hospitalist_headers(h2["id"]))
        # Window FULL: third enrollment rejected
        resp = api.enroll_coverage_window(w["id"], make_hospitalist_headers(h3["id"]))
        validate_error(resp, ApiErrorId.ERR_COVERAGE_WINDOW_FULL)
        # Withdraw H1 -> FULL -> OPEN
        r3 = get_success_data(api.withdraw_coverage_window(w["id"], make_hospitalist_headers(h1["id"])))
        assert r3["enrolled_count"] == 1
        assert r3["status"] == "OPEN"
        # Re-enroll H3 -> FULL again; roster is [H2, H3] in enrollment order
        r4 = get_success_data(api.enroll_coverage_window(w["id"], make_hospitalist_headers(h3["id"])))
        assert r4["enrolled_count"] == 2
        assert r4["status"] == "FULL"
        assert r4["enrolled_hospitalist_ids"] == [h2["id"], h3["id"]]
