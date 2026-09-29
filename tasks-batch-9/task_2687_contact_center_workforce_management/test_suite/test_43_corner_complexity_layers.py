"""Concurrency, threshold-driven capacity and the immediacy of the reforecast cascade."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cycle_ledgers,
    assert_interval_forecast,
    assert_interval_outsourcing,
    assert_partner_ledgers,
    assert_ratio,
)
from test_helpers.constants import (
    ALLOCATION_COMMITTED,
    ALLOCATION_PROPOSED,
    BILLING_DELIVERED_ONLY,
    PARTNER_STATUS_ACTIVE,
    PARTNER_STATUS_PROBATION,
    POSTURE_REQUIREMENTS_LOCKED,
)
from test_helpers.factories import (
    commit_allocation_payload,
    partner_allocation_payload,
    reforecast_payload,
)
from test_helpers.fixtures import (
    CANONICAL_CLOCK,
    build_partner_week,
    file_performance_report,
    generate_allocations,
    generate_grid,
    lock_requirements,
    make_forecast_group,
    make_outsource_partner,
    make_planning_cycle,
    post_actuals,
    propose_allocation,
    read_allocation,
    read_cycle,
    read_group,
    read_interval,
    read_partner,
    set_clock,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    SOURCING_ALT_USER_ID,
    SOURCING_HEADERS,
    make_sourcing_headers,
)

PARTNER_OVERRIDES = {
    "rate_per_contact_millicents": 10000,
    "interval_max_volume": 50,
    "commitment_floor_volume": 10,
    "performance_threshold_pct": 0.8500,
    "billing_basis": BILLING_DELIVERED_ONLY,
}
FORWARD_BOUNDARY = "2026-09-07T08:30:00Z"
FAR_FUTURE_VERSION = 99


class TestReforecastCycleVersionEcho:
    """A posture lock behind the client's back invalidates its version echo."""

    def test_a_stale_or_future_echo_is_refused_and_writes_nothing(self, api):
        """Version 1 and version 99 are equally stale, and only the exact version advances the run.

        "If `expected_cycle_version` does not equal the cycle's current `version`,
        the run is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412) and nothing
        is written; the client must re-read the cycle — including its advanced
        `reforecast_generation` — before trying again."

        Design: Corner/cross_cutting_complexity_layers/reforecast_with_stale_cycle_version_returns_412
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api)
        assert cycle["version"] == 1
        group = make_forecast_group(api, cycle["id"])
        generate_grid(api, group["id"], "2026-09-07")

        locked = lock_requirements(api, cycle["id"])
        assert locked["posture"] == POSTURE_REQUIREMENTS_LOCKED
        locked_version = locked["version"]
        assert locked_version > 1

        validate_error(
            api.reforecast(
                cycle["id"],
                reforecast_payload(locked_version - 1, FORWARD_BOUNDARY),
                ANALYST_HEADERS,
            ),
            ApiErrorId.STALE_CYCLE_VERSION,
            412,
        )

        assert_cycle_ledgers(
            read_cycle(api, cycle["id"]),
            version=locked_version,
            reforecast_generation=0,
        )
        assert_ratio(
            read_group(api, group["id"])["reforecast_multiplier"],
            1.0000,
            "reforecast_multiplier",
        )

        validate_error(
            api.reforecast(
                cycle["id"],
                reforecast_payload(FAR_FUTURE_VERSION, FORWARD_BOUNDARY),
                ANALYST_HEADERS,
            ),
            ApiErrorId.STALE_CYCLE_VERSION,
            412,
        )
        assert_cycle_ledgers(
            read_cycle(api, cycle["id"]),
            version=locked_version,
            reforecast_generation=0,
        )

        advanced = validate_success(
            api.reforecast(
                cycle["id"],
                reforecast_payload(locked_version, FORWARD_BOUNDARY),
                ANALYST_HEADERS,
            ),
            200,
        )
        assert_cycle_ledgers(
            advanced, version=locked_version + 1, reforecast_generation=1
        )


class TestCommitPartnerVersionEcho:
    """The second concurrency guard names a different parent and a different error."""

    def test_a_performance_report_invalidates_the_committers_version_echo(self, api):
        """A non-breaching report moves the partner version, so the pending commit is refused.

        "Committing a partner allocation requires `expected_partner_version` as a
        non-optional body field, carrying the client's last observed `version` of
        the referenced `OutsourcePartner`. Commitment consumes partner capacity
        against `committed_volume_outstanding` and depends on the eligibility state
        that performance reports and other commitments both move, so a client whose
        view of the partner predates those changes is refused with
        `ERR_STALE_PARTNER_VERSION` (HTTP 412) until it re-reads the partner."

        Design: Corner/cross_cutting_complexity_layers/commit_with_stale_partner_version_returns_412
        """
        world = build_partner_week(api)
        interval_id = world["intervals"][0]["id"]
        partner = make_outsource_partner(api, SOURCING_HEADERS, **PARTNER_OVERRIDES)
        assert partner["version"] == 1

        allocation = propose_allocation(
            api, partner["id"], interval_id, 20, SOURCING_HEADERS
        )
        assert allocation["status"] == ALLOCATION_PROPOSED

        reported = file_performance_report(api, partner["id"], 0.9000)
        assert_partner_ledgers(
            reported,
            status=PARTNER_STATUS_ACTIVE,
            rolling_sl_attainment_pct=0.9000,
            consecutive_breach_count=0,
            version=2,
        )

        committer = make_sourcing_headers(SOURCING_ALT_USER_ID)
        validate_error(
            api.commit_partner_allocation(
                allocation["id"], commit_allocation_payload(1), committer
            ),
            ApiErrorId.STALE_PARTNER_VERSION,
            412,
        )

        assert read_allocation(api, allocation["id"])["status"] == ALLOCATION_PROPOSED
        assert_partner_ledgers(
            read_partner(api, partner["id"]),
            committed_volume_outstanding=0,
            version=2,
        )

        committed = validate_success(
            api.commit_partner_allocation(
                allocation["id"], commit_allocation_payload(2), committer
            ),
            200,
        )
        assert committed["status"] == ALLOCATION_COMMITTED

        assert_partner_ledgers(
            read_partner(api, partner["id"]),
            committed_volume_outstanding=20,
            version=3,
        )
        assert_interval_outsourcing(
            read_interval(api, interval_id),
            partner_committed_volume=20,
            unserved_volume=62,
        )


class TestProbationCapsPartnerParticipation:
    """One report rewrites the partner's cap on both allocation pathways at once."""

    def test_the_cap_drops_to_the_floor_on_probation_and_is_restored_on_recovery(self, api):
        """Fifty units while active, ten on probation, then fifty again once the rolling score recovers.

        "`ACTIVE → PROBATION` fires on the first breach: `consecutive_breach_count`
        is set to 1 and the partner's waterfall cap drops from `interval_max_volume`
        to `commitment_floor_volume` for every subsequent allocation run.
        `PROBATION → ACTIVE` fires when a report does not breach:
        `consecutive_breach_count` resets to 0 and the full interval cap is
        restored."

        "A report **breaches** when the recomputed `rolling_sl_attainment_pct` is
        strictly below the partner's `performance_threshold_pct`; attainment exactly
        equal to the threshold is compliant."

        "`allocated_volume` must be at least the partner's `commitment_floor_volume`
        and at most the partner's applicable interval cap, which is
        `interval_max_volume` while the partner is `ACTIVE` and
        `commitment_floor_volume` while it is on `PROBATION`; a volume outside that
        band is refused with `ERR_PARTNER_VOLUME_OUT_OF_RANGE` (HTTP 422)."

        Design: Corner/cross_cutting_complexity_layers/probation_caps_partner_participation_at_commitment_floor
        """
        world = build_partner_week(api)
        first_interval = world["intervals"][0]
        second_interval = world["intervals"][1]
        partner = make_outsource_partner(api, SOURCING_HEADERS, **PARTNER_OVERRIDES)
        assert_partner_ledgers(
            partner,
            status=PARTNER_STATUS_ACTIVE,
            rolling_sl_attainment_pct=None,
            consecutive_breach_count=0,
        )
        assert_interval_outsourcing(first_interval, allocatable_volume=82)
        assert_interval_outsourcing(second_interval, allocatable_volume=82)

        active_run = generate_allocations(api, first_interval["id"])
        assert len(active_run) == 1
        assert active_run[0]["allocated_volume"] == 50
        assert active_run[0]["status"] == ALLOCATION_PROPOSED

        breached = file_performance_report(api, partner["id"], 0.8000)
        assert_partner_ledgers(
            breached,
            status=PARTNER_STATUS_PROBATION,
            rolling_sl_attainment_pct=0.8000,
            consecutive_breach_count=1,
        )

        probation_run = generate_allocations(api, second_interval["id"])
        assert len(probation_run) == 1
        assert probation_run[0]["allocated_volume"] == 10

        validate_error(
            api.create_partner_allocation(
                partner_allocation_payload(partner["id"], second_interval["id"], 50),
                SOURCING_HEADERS,
            ),
            ApiErrorId.PARTNER_VOLUME_OUT_OF_RANGE,
            422,
        )

        recovered = file_performance_report(
            api, partner["id"], 0.9000, period_end_date="2026-09-07"
        )
        assert_partner_ledgers(
            recovered,
            status=PARTNER_STATUS_ACTIVE,
            rolling_sl_attainment_pct=0.8500,
            consecutive_breach_count=0,
        )

        restored = validate_success(
            api.create_partner_allocation(
                partner_allocation_payload(partner["id"], second_interval["id"], 50),
                SOURCING_HEADERS,
            ),
            201,
        )
        assert restored["allocated_volume"] == 50
        assert restored["status"] == ALLOCATION_PROPOSED


class TestReforecastIsImmediatelyObservable:
    """The reforecast response body is already the post-write state, history included."""

    def test_the_response_body_and_the_forward_window_are_already_recomputed(self, api):
        """One call advances the generation in its own body and leaves the seeding interval alone.

        "The system then re-runs the volume forecast, the handle-time forecast, both
        staffing variants and the absorbable-volume chain for every interval plan of
        the group whose `interval_start` is at or after
        `effective_from_interval_start`, increments the cycle's
        `reforecast_generation` by 1, recomputes `short_interval_count`, evaluates
        the posture edges, and increments the cycle's `version` by 1."

        "Any operation that perturbs a link recomputes every downstream link in the
        same request — never lazily, never on the next read."

        Design: Corner/consistency_model/reforecast_response_carries_recomputed_forward_window_in_same_request
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api)
        group = make_forecast_group(api, cycle["id"])
        assert_ratio(group["reforecast_multiplier"], 1.0000, "reforecast_multiplier")
        intervals = generate_grid(api, group["id"], "2026-09-07")
        assert len(intervals) == 4

        seeded = post_actuals(api, intervals[0]["id"], 240, 300)
        assert_ratio(seeded["observed_ratio"], 0.5000, "observed_ratio")

        locked = lock_requirements(api, cycle["id"])
        locked_version = locked["version"]

        replayed = validate_success(
            api.reforecast(
                cycle["id"],
                reforecast_payload(locked_version, FORWARD_BOUNDARY),
                ANALYST_HEADERS,
            ),
            200,
        )
        assert_cycle_ledgers(
            replayed,
            version=locked_version + 1,
            reforecast_generation=1,
            short_interval_count=4,
        )

        assert_ratio(
            read_group(api, group["id"])["reforecast_multiplier"],
            0.8000,
            "reforecast_multiplier",
        )

        history = read_interval(api, intervals[0]["id"])
        assert_ratio(history["smoothed_ratio"], 0.8000, "smoothed_ratio")
        assert_interval_forecast(history, volume_forecast=480, required_agents=140)

        assert_interval_forecast(
            read_interval(api, intervals[1]["id"]),
            volume_forecast=288,
            required_agents=84,
        )
        assert_interval_forecast(
            read_interval(api, intervals[2]["id"]),
            volume_forecast=192,
            required_agents=56,
        )
        assert_interval_forecast(
            read_interval(api, intervals[3]["id"]),
            volume_forecast=96,
            required_agents=28,
        )
