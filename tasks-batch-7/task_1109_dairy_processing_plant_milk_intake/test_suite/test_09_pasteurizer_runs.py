"""Pasteurizer runs: half-open overlap conflicts, completion and cancellation
preconditions, and the abort cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_run,
    get_success_data,
    make_batch,
    make_run,
    set_clock,
    setup_running_run,
    setup_validated_cip,
    validate_error,
    validate_success,
)

OP = TEST_USERS["pasteurizer_operator_headers"]


class TestPasteurizerOverlapHalfOpen:
    def test_overlapping_running_run_rejected(self, api):
        """PRD §3.6: "no other `PasteurizerRun` for the same `pasteurizer_id`
        may already be in `RUNNING` with an overlapping half-open window from
        `scheduled_start_at` to `scheduled_end_at`, otherwise
        `ERR_PASTEURIZER_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pasteurizer_run_overlap_half_open
        """
        run_a = setup_running_run(start="2026-05-10T08:00:00Z", end="2026-05-10T12:00:00Z")
        assert run_a["status"] == "RUNNING"

        # Run C [11:00, 13:00) shares the interior of A's [08:00, 12:00).
        run_c = make_run(
            scheduled_start_at="2026-05-10T11:00:00Z",
            scheduled_end_at="2026-05-10T13:00:00Z",
        )
        res = api.start_pasteurizer_run(run_c["id"], {}, OP)
        validate_error(res, ApiErrorId.ERR_PASTEURIZER_OVERLAP)

    def test_abutting_run_half_open_no_overlap(self, api):
        """PRD §3.6: the conflict window is "an overlapping half-open window
        from `scheduled_start_at` to `scheduled_end_at`" — a run starting
        exactly when the RUNNING run ends (12:00 == 12:00) shares no interior
        point and may start.

        Design: Difficulty/resource_temporal_overlap/pasteurizer_run_overlap_half_open
        """
        run_a = setup_running_run(start="2026-05-10T08:00:00Z", end="2026-05-10T12:00:00Z")
        assert run_a["status"] == "RUNNING"

        run_b = make_run(
            scheduled_start_at="2026-05-10T12:00:00Z",
            scheduled_end_at="2026-05-10T16:00:00Z",
        )
        res = api.start_pasteurizer_run(run_b["id"], {}, OP)
        started = validate_success(res, 200)
        assert started["status"] == "RUNNING"


def test_complete_blocked_by_unfinished_batches(api):
    """PRD §3.6: "The completion requires that every `ProductBatch` for the run
    be in `CODED` or `SCRAPPED`; otherwise `ERR_BATCHES_UNFINISHED`."

    Design: Corner/state_machines/complete_run_blocked_by_unfinished_batches
    """
    run = setup_running_run()
    batch = make_batch(run["id"], shelf_life_days=14)
    get_success_data(api.begin_batch(run["id"], batch["id"], {}, OP))

    res = api.complete_pasteurizer_run(run["id"], {}, OP)
    validate_error(res, ApiErrorId.ERR_BATCHES_UNFINISHED)


def test_cancel_running_run_is_invalid_state(api):
    """PRD §3.6: "Cancelling a run moves it from `SCHEDULED` to `CANCELLED`" —
    the transition is undefined from `RUNNING`, so the state-machine
    precondition fails first. PRD §2.10: "then state-machine precondition (→
    `ERR_INVALID_STATE`), then the business-rule checks enumerated for that
    endpoint in §3".

    Design: Corner/state_machines/cancel_run_blocked_by_in_production_batch
    """
    run = setup_running_run()
    batch = make_batch(run["id"], shelf_life_days=14)
    get_success_data(api.begin_batch(run["id"], batch["id"], {}, OP))

    res = api.cancel_pasteurizer_run(run["id"], {}, OP)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_abort_scraps_in_production_batches(api):
    """PRD §3.6: "Aborting a run moves it from `RUNNING` to `ABORTED` with no
    preconditions; on abort the server stamps `actual_end_at`, transitions
    every non-terminal batch of the run to `SCRAPPED`".

    Design: Corner/cross_cutting/cascading_abort_scraps_batches_and_invalidates_assays
    """
    run = setup_running_run()
    batch = make_batch(run["id"], shelf_life_days=14)
    get_success_data(api.begin_batch(run["id"], batch["id"], {}, OP))

    aborted = validate_success(api.abort_pasteurizer_run(run["id"], {}, OP), 200)
    assert aborted["status"] == "ABORTED"
    assert aborted["actual_end_at"] is not None

    batches = get_success_data(api.list_batches(run["id"], OP))
    assert len(batches) == 1
    assert batches[0]["id"] == batch["id"]
    assert batches[0]["status"] == "SCRAPPED"
