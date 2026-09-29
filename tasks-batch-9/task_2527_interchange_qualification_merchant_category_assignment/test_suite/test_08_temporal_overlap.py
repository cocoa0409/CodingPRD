"""Two deliberately opposite interval conventions: the half-open rate-version
interval and the closed, buffered platform window interval.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import make_implementation_window_payload
from test_helpers.fixtures import (
    canonical_environment,
    draft_rate_version,
    publish_rate_version,
    schedule_window,
)
from test_helpers.test_users import TEST_USERS

NETWORK_ADMIN = TEST_USERS["network_admin_headers"]


def _three_drafted_quarters():
    """2026Q4 [2026-10-01, 2027-01-01), 2027Q1 [2027-01-01, 2027-04-01) — adjacent
    — and 2027Q2 [2026-12-15, 2027-03-01), which reaches back into both."""
    env = canonical_environment(
        "2026-09-01T12:00:00Z", program_keys=("CPS_RETAIL",)
    )
    program_id = env["programs"]["CPS_RETAIL"]["id"]
    fourth_quarter = draft_rate_version(
        program_id,
        "2026Q4",
        "2026-10-01T00:00:00Z",
        "2027-01-01T00:00:00Z",
        "2026-09-30T00:00:00Z",
        base_rate_bps=150,
        per_item_fee_cents=10,
    )
    first_quarter = draft_rate_version(
        program_id,
        "2027Q1",
        "2027-01-01T00:00:00Z",
        "2027-04-01T00:00:00Z",
        "2026-12-31T00:00:00Z",
        base_rate_bps=155,
        per_item_fee_cents=10,
    )
    intruder = draft_rate_version(
        program_id,
        "2027Q2",
        "2026-12-15T00:00:00Z",
        "2027-03-01T00:00:00Z",
        "2026-12-01T00:00:00Z",
        base_rate_bps=160,
        per_item_fee_cents=10,
    )
    return {
        "program_id": program_id,
        "fourth_quarter": fourth_quarter,
        "first_quarter": first_quarter,
        "intruder": intruder,
    }


def _read_version(version_id):
    return validate_success(
        api_client.get_rate_program_version(version_id, NETWORK_ADMIN)
    )


class TestRateVersionHalfOpenIntervals:
    def test_a_version_starting_exactly_where_its_predecessor_ends_publishes(self):
        """2027Q1 opens at the exact instant 2026Q4 closes, and because the end of
        the interval is exclusive the two hand over without colliding.

        PRD 3.2: "The interval is half-open, which means adjacency is legal: a
        version whose `effective_from` equals a predecessor's `effective_to` hands
        over cleanly with no gap and no collision."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_rate_version_half_open_adjacency_legal_intrusion_rejected
        """
        state = _three_drafted_quarters()
        first = publish_rate_version(state["fourth_quarter"]["id"])
        assert first["status"] == "PUBLISHED"

        second = publish_rate_version(state["first_quarter"]["id"])
        assert second["status"] == "PUBLISHED"

    def test_a_version_reaching_one_interval_back_is_refused_and_stays_drafted(self):
        """2027Q2 starts before both published rivals end, so a single collision is
        enough to refuse the publication and the row is left in `DRAFT`.

        PRD 3.2: "Two half-open intervals collide when the candidate's
        `effective_from` is strictly earlier than the rival's `effective_to` **and**
        the rival's `effective_from` is strictly earlier than the candidate's
        `effective_to`; both comparisons are strict, and the capacity is one, so a
        single colliding rival is enough to reject the publication with
        `ERR_RATE_VERSION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_rate_version_half_open_adjacency_legal_intrusion_rejected
        """
        state = _three_drafted_quarters()
        publish_rate_version(state["fourth_quarter"]["id"])
        publish_rate_version(state["first_quarter"]["id"])

        response = api_client.publish_rate_program_version(
            state["intruder"]["id"], NETWORK_ADMIN
        )
        validate_error(response, "ERR_RATE_VERSION_WINDOW_OVERLAP", 409)

        assert _read_version(state["first_quarter"]["id"])["status"] == "PUBLISHED"
        assert _read_version(state["intruder"]["id"])["status"] == "DRAFT"

        listing = api_client.list_rate_program_versions(
            NETWORK_ADMIN,
            params={"rate_program_id": state["program_id"], "status": "PUBLISHED"},
        )
        rows, meta = validate_paginated(listing)
        assert meta["total_count"] == 2
        assert len(rows) == 2


def _platform_with_one_scheduled_window():
    """A single-capacity platform with a 3-day blackout buffer and one window
    already standing on [2026-09-05, 2026-09-10]."""
    env = canonical_environment(
        "2026-09-01T12:00:00Z", program_keys=("CPS_RETAIL",)
    )
    version = draft_rate_version(
        env["programs"]["CPS_RETAIL"]["id"],
        "2026Q4",
        "2026-10-01T00:00:00Z",
        "2027-01-01T00:00:00Z",
        "2026-09-30T00:00:00Z",
        base_rate_bps=150,
        per_item_fee_cents=10,
    )
    publish_rate_version(version["id"])
    first = schedule_window(
        env["acquirer"]["id"],
        version["id"],
        env["platform"]["id"],
        "2026-09-05T00:00:00Z",
        "2026-09-10T00:00:00Z",
    )
    return {
        "acquirer_id": env["acquirer"]["id"],
        "platform_id": env["platform"]["id"],
        "version_id": version["id"],
        "first": first,
    }


def _window_attempt(state, window_start, window_end):
    return api_client.create_implementation_window(
        make_implementation_window_payload(
            state["acquirer_id"],
            state["version_id"],
            state["platform_id"],
            window_start,
            window_end,
        ),
        NETWORK_ADMIN,
    )


def _read_window(window_id):
    return validate_success(
        api_client.get_implementation_window(window_id, NETWORK_ADMIN)
    )


class TestPlatformWindowClosedIntervalsWithBuffer:
    def test_a_geometrically_disjoint_window_collides_once_the_buffer_is_applied(self):
        """[2026-09-12, 2026-09-15] touches the standing window inflated to
        [2026-09-02, 2026-09-13] and is refused, while [2026-09-14, 2026-09-18]
        clears the buffer by one day and is admitted.

        PRD 3.2: "The candidate is said to collide with an inflated rival when the
        candidate's `window_start` is at or before the rival's inflated end **and**
        the rival's inflated start is at or before the candidate's `window_end`;
        both comparisons are non-strict, so merely touching endpoints do collide
        here."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_platform_windows_closed_interval_with_symmetric_buffer_and_capacity
        """
        state = _platform_with_one_scheduled_window()
        assert state["first"]["status"] == "SCHEDULED"

        blocked = _window_attempt(state, "2026-09-12T00:00:00Z", "2026-09-15T00:00:00Z")
        validate_error(blocked, "ERR_PLATFORM_WINDOW_CONFLICT", 409)

        admitted = _window_attempt(state, "2026-09-14T00:00:00Z", "2026-09-18T00:00:00Z")
        third = validate_success(admitted, 201)
        assert third["status"] == "SCHEDULED"
        assert third["window_start"] == "2026-09-14T00:00:00.000Z"

    def test_the_envelope_check_is_reported_ahead_of_the_capacity_conflict(self):
        """[2026-09-08, 2026-10-05] both collides with the standing window and ends
        past the version's implementation deadline, and the fixed order reports the
        envelope failure.

        PRD 3.2: "Two independent checks guard scheduling, and their order is
        fixed. First the **envelope check**: `window_start` must be at or after the
        referenced version's `published_at`, and `window_end` must be at or before
        that version's `implementation_deadline`."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_platform_windows_closed_interval_with_symmetric_buffer_and_capacity
        """
        state = _platform_with_one_scheduled_window()
        validate_success(
            _window_attempt(state, "2026-09-14T00:00:00Z", "2026-09-18T00:00:00Z"), 201
        )

        response = _window_attempt(state, "2026-09-08T00:00:00Z", "2026-10-05T00:00:00Z")
        error = validate_error(response, "ERR_IMPLEMENTATION_WINDOW_OUT_OF_BOUNDS", 422)
        assert error["error_id"] != "ERR_PLATFORM_WINDOW_CONFLICT"

        assert _read_window(state["first"]["id"])["status"] == "SCHEDULED"

        listing = api_client.list_implementation_windows(
            NETWORK_ADMIN, params={"platform_id": state["platform_id"]}
        )
        rows, meta = validate_paginated(listing)
        assert meta["total_count"] == 2
        assert len(rows) == 2
