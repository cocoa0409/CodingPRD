"""Buffered blocked intervals are half-open: a request whose buffer-expanded
span only touches an issued permit's blocked span at the exclusive endpoint is
not an overlap; a thirty-minute intrusion is (PRD §2.4, §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    make_renter_headers,
    make_booking_env, add_renter_with_insurance,
    make_approved_permit_in_env, make_under_review_request, approve,
    create_request_payload,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

DIRECTOR = TEST_USERS["director_headers"]


def _env_with_blocking_permit(api):
    """GYM (30/30 buffers); Renter One holds an ISSUED permit occupying
    [2026-11-07T01:00Z, 04:00Z) -> blocked [00:30Z, 04:30Z). Returns
    (env, env2) where env2 is the same inventory under Renter Two."""
    env = make_booking_env(org_name="Renter One")
    req1, permit1 = make_approved_permit_in_env(
        env, event_title="Evening Gala", headcount_estimate=100,
        starts_at="2026-11-07T01:00:00Z", ends_at="2026-11-07T04:00:00Z")
    assert permit1["blocked_start"].startswith("2026-11-07T00:30")
    assert permit1["blocked_end"].startswith("2026-11-07T04:30")
    org2, _cert2 = add_renter_with_insurance("Renter Two")
    return env, {**env, "org": org2}


class TestFacilityBlockedIntervalHalfOpenAdjacency:
    def test_touching_at_exclusive_endpoint_is_not_overlap(self, api):
        """PRD §2.4: "Every occupancy, coverage, blocked, and event interval in
        the system is half-open: the start instant is inclusive and the end
        instant is exclusive, written [start, end). Two intervals overlap when
        each begins strictly before the other ends."
        PRD §3.4: "The facility's committed book must be clear: no `ISSUED` or
        `ACTIVE` permit whose blocked interval overlaps the requested window
        expanded by the facility's setup and teardown buffers — that is, the span
        from `starts_at` minus `setup_buffer_minutes` to `ends_at` plus
        `teardown_buffer_minutes` (else `ERR_SCHEDULE_CONFLICT`)."

        Design: Difficulty/resource_temporal_overlap/facility_blocked_interval_half_open_adjacency
        """
        env, env2 = _env_with_blocking_permit(api)
        # R-touch [05:00, 06:30) -> blocked [04:30, 07:00): touches the blocking
        # permit's blocked span only at the exclusive endpoint 04:30.
        req2 = make_under_review_request(
            env2, event_title="Late Night Setup", headcount_estimate=50,
            starts_at="2026-11-07T05:00:00Z", ends_at="2026-11-07T06:30:00Z")
        permit2 = approve(req2["id"], req2["version"])
        assert permit2["lifecycle_status"] == "ISSUED"
        # The buffers are part of the blocked-interval arithmetic itself.
        assert permit2["blocked_start"].startswith("2026-11-07T04:30")
        assert permit2["blocked_end"].startswith("2026-11-07T07:00")

    def test_thirty_minute_intrusion_rejected_as_conflict(self, api):
        """PRD §2.9: "**Availability and schedule conflict.** The site must be
        `ACTIVE`, else `ERR_SITE_CLOSED` (HTTP 409); the facility must be
        `AVAILABLE`, else `ERR_FACILITY_NOT_AVAILABLE` (HTTP 409); and the
        requested interval must not collide with a `SCHEDULED` school calendar
        event or with the blocked interval of an `ISSUED` or `ACTIVE` permit on
        the same facility, else `ERR_SCHEDULE_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/facility_blocked_interval_half_open_adjacency
        """
        env, env2 = _env_with_blocking_permit(api)
        # R-overlap [04:00, 05:00) -> blocked [03:30, 05:30): intersects the
        # blocking permit's [00:30, 04:30) on [03:30, 04:30).
        res = api.create_request(
            env2["org"]["id"],
            create_request_payload(
                env["facility"]["id"], event_title="Overlapping Mixer",
                headcount_estimate=50,
                starts_at="2026-11-07T04:00:00Z", ends_at="2026-11-07T05:00:00Z"),
            make_renter_headers(env2["org"]["id"]))
        validate_error(res, ApiErrorId.ERR_SCHEDULE_CONFLICT)
