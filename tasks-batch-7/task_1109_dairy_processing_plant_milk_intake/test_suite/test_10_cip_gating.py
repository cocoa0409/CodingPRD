"""CIP freshness gating on run start: failed/absent/mis-scoped CIP and the
trailing 24-hour sliding window."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    fail_cip,
    make_cip_cycle,
    make_permit,
    make_run,
    set_clock,
    setup_validated_cip,
    validate_error,
    validate_success,
)

OP = TEST_USERS["pasteurizer_operator_headers"]


class TestRunStartGatedOnCipValidation:
    def test_failed_cip_blocks_run_start(self, api):
        """PRD §3.6: "The most recent completed `CipCycle` for the same
        `pasteurizer_id` must have a `validation_outcome` of `PASS` and a
        `completed_at` within the trailing 24 hours of the current logical
        clock, otherwise `ERR_CIP_STALE`." PRD §3.7: a failed cycle means "the
        parent `PasteurizerRun` cannot be started until a subsequent
        `VALIDATED` cycle exists."

        Design: Difficulty/cross_entity_state_dependency/run_start_gated_on_cip_validation
        """
        set_clock("2026-05-01T00:00:00Z")
        make_permit()
        run = make_run()
        cip = make_cip_cycle(
            run["id"],
            started_at="2026-05-09T08:00:00Z",
            caustic_conductivity_ms=70.0,
            rinse_ph=9.5,
        )
        fail_cip(run["id"], cip["id"])

        res = api.start_pasteurizer_run(run["id"], {}, OP)
        validate_error(res, ApiErrorId.ERR_CIP_STALE)

    def test_cip_for_other_pasteurizer_does_not_count(self, api):
        """PRD §3.6: "The most recent completed `CipCycle` for the same
        `pasteurizer_id` must have a `validation_outcome` of `PASS`" — a
        VALIDATED cycle recorded under another pasteurizer does not satisfy the
        gate, so the run start is rejected with `ERR_CIP_STALE`.

        Design: Difficulty/cross_entity_state_dependency/run_start_gated_on_cip_validation
        """
        set_clock("2026-05-10T06:00:00Z")
        make_permit()
        # VALIDATED CIP exists, but only under an HTST-2 run.
        run_htst2 = make_run(pasteurizer_id="HTST-2")
        setup_validated_cip(run_htst2["id"], started_at="2026-05-10T06:00:00Z")

        run_htst1 = make_run(pasteurizer_id="HTST-1")
        res = api.start_pasteurizer_run(run_htst1["id"], {}, OP)
        validate_error(res, ApiErrorId.ERR_CIP_STALE)


class TestCip24HourStaleWindow:
    def test_cip_older_than_24h_is_stale(self, api):
        """PRD §3.6: "The most recent completed `CipCycle` for the same
        `pasteurizer_id` must have a `validation_outcome` of `PASS` and a
        `completed_at` within the trailing 24 hours of the current logical
        clock, otherwise `ERR_CIP_STALE`." A cycle completed 24h01m before the
        start attempt is outside the window.

        Design: Difficulty/resource_temporal_overlap/cip_24hour_stale_window
        """
        set_clock("2026-05-09T08:00:00Z")
        make_permit()
        run = make_run(
            scheduled_start_at="2026-05-10T09:00:00Z",
            scheduled_end_at="2026-05-10T12:00:00Z",
        )
        # completed_at stamps from the logical clock: 2026-05-09T08:00:00Z
        setup_validated_cip(run["id"], started_at="2026-05-09T07:00:00Z")

        set_clock("2026-05-10T08:01:00Z")  # 24h01m later
        res = api.start_pasteurizer_run(run["id"], {}, OP)
        validate_error(res, ApiErrorId.ERR_CIP_STALE)

    def test_cip_within_24h_allows_start(self, api):
        """PRD §3.6: "a `completed_at` within the trailing 24 hours of the
        current logical clock" satisfies the freshness gate; a cycle completed
        23h59m ago is inside the window, and with the permit valid and no
        overlap the run starts.

        Design: Difficulty/resource_temporal_overlap/cip_24hour_stale_window
        """
        set_clock("2026-05-09T08:00:00Z")
        make_permit()
        run = make_run(
            scheduled_start_at="2026-05-10T09:00:00Z",
            scheduled_end_at="2026-05-10T12:00:00Z",
        )
        setup_validated_cip(run["id"], started_at="2026-05-09T07:00:00Z")

        set_clock("2026-05-10T07:59:00Z")  # 23h59m later — still fresh
        started = validate_success(api.start_pasteurizer_run(run["id"], {}, OP), 200)
        assert started["status"] == "RUNNING"
        assert started["actual_start_at"] is not None
