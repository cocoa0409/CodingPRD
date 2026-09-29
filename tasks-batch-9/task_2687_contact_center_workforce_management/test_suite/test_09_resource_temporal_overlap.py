"""Boundaries of the two temporal windows: the rest buffer and the interval span."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_agent_hours,
    assert_cents,
    assert_cycle_ledgers,
    assert_instant_equals,
    assert_interval_outsourcing,
    assert_partner_ledgers,
    assert_ratio,
    assert_shift_hours,
)
from test_helpers.constants import (
    ACTION_STATUS_ACCEPTED,
    ACTION_STATUS_OFFERED,
    ALLOCATION_COMMITTED,
    ALLOCATION_PROPOSED,
    BILLING_DELIVERED_ONLY,
    RESPONSE_ACCEPT,
)
from test_helpers.fixtures import (
    CANONICAL_CLOCK,
    HORIZON_START,
    build_partner_week,
    commit_allocation,
    generate_grid,
    lock_requirements,
    make_agent,
    make_forecast_group,
    make_labor_agreement,
    make_ot_offer,
    make_outsource_partner,
    make_planning_cycle,
    make_schedule_shift,
    make_shift_template,
    propose_allocation,
    publish_shift,
    read_action,
    read_agent,
    read_allocation,
    read_cycle,
    read_interval,
    read_partner,
    read_shift,
    respond_to_action,
    set_clock,
)
from test_helpers.test_users import (
    SOURCING_ALT_USER_ID,
    make_agent_headers,
    make_sourcing_headers,
)


def _accept(api, action_id, agent_id):
    """Raw acceptance so a refusal can be inspected."""
    return api.respond_to_intraday_action(
        action_id,
        f.action_response_payload(RESPONSE_ACCEPT),
        make_agent_headers(agent_id),
    )


TUESDAY = "2026-09-08"


def _rest_buffer_week(api):
    """Two published back-to-back days plus a 5.0-hour and a 0.5-hour offer on Monday."""
    set_clock(api, CANONICAL_CLOCK)
    agreement = make_labor_agreement(api, min_rest_hours=11, max_weekly_hours=45.0)
    cycle = make_planning_cycle(api, name="W37-BUF")
    group = make_forecast_group(api, cycle["id"])
    generate_grid(api, group["id"], HORIZON_START)
    agent = make_agent(api, agreement["id"], hourly_rate_cents=2400)
    template = make_shift_template(
        api, cycle["id"], code="T-WK-AM", days_of_week=[0, 1], slots_total=2
    )
    monday = make_schedule_shift(
        api, cycle["id"], agent["id"], template["id"], HORIZON_START
    )
    tuesday = make_schedule_shift(
        api, cycle["id"], agent["id"], template["id"], TUESDAY
    )
    lock_requirements(api, cycle["id"])
    monday = publish_shift(api, monday["id"])
    tuesday = publish_shift(api, tuesday["id"])
    fitting = make_ot_offer(
        api,
        cycle["id"],
        agent["id"],
        monday["id"],
        group["id"],
        hours=5.0,
        expires_at="2026-09-30T00:00:00Z",
    )
    overshooting = make_ot_offer(
        api,
        cycle["id"],
        agent["id"],
        monday["id"],
        group["id"],
        hours=0.5,
        expires_at="2026-09-30T00:00:00Z",
    )
    return {
        "cycle": cycle,
        "agent": agent,
        "monday": monday,
        "tuesday": tuesday,
        "fitting": fitting,
        "overshooting": overshooting,
    }


class TestRestBufferClosedBoundaryOnOvertimeExtension:
    """Overtime stretches end_at, so the gap to the next day is the binding constraint."""

    def test_an_extension_landing_exactly_on_the_rest_floor_is_accepted(self, api):
        """Five extra hours leave exactly eleven hours before Tuesday, and equality passes.

        "The **rest rule** compares the gap between the end of one shift and the
        start of the agent's next non-overlapping shift against the agreement's
        `min_rest_hours`; the check passes when the gap is greater than or equal to
        that value, and a gap strictly below it is refused with
        `ERR_MIN_REST_VIOLATION` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/agent_rest_buffer_closed_boundary_on_ot_extension
        """
        world = _rest_buffer_week(api)

        accepted = respond_to_action(
            api, world["fitting"]["id"], world["agent"]["id"]
        )

        assert accepted["status"] == ACTION_STATUS_ACCEPTED
        assert_cents(accepted["cost_cents"], 18000, "cost_cents")
        assert_ratio(accepted["ot_multiplier_applied"], 1.50, "ot_multiplier_applied")

    def test_the_accepted_extension_moves_the_finish_to_twenty_one_hundred(self, api):
        """The Monday shift now ends at 21:00 carrying five overtime hours.

        "An accepted overtime offer then extends the shift's `end_at` by `hours`
        and recomputes the shift's `scheduled_seconds`, `ot_hours` and `paid_hours`,
        the agent's `scheduled_hours_committed`, the cycle's `ot_hours_committed`
        (the two-decimal sum of `hours` over the cycle's accepted overtime actions),
        the cycle's `ot_spend_committed_cents` (the integer sum of `cost_cents` over
        the same set) and the cycle's `total_scheduled_hours`."

        Design: Difficulty/resource_temporal_overlap/agent_rest_buffer_closed_boundary_on_ot_extension
        """
        world = _rest_buffer_week(api)

        respond_to_action(api, world["fitting"]["id"], world["agent"]["id"])

        shift = read_shift(api, world["monday"]["id"])
        assert_instant_equals(shift["end_at"], "2026-09-07T21:00:00Z", "end_at")
        assert_shift_hours(shift, ot_hours=5.00)

    def test_a_further_half_hour_breaks_the_eleven_hour_buffer(self, api):
        """With 21:00 already reached, another half hour leaves only 10.5 hours of rest.

        "For an overtime offer it additionally requires that the cycle's overtime
        budget holds and that extending the shift keeps the agent's rest gap at or
        above the agreement's `min_rest_hours` and the agent's weekly committed
        total at or below the agreement's `max_weekly_hours` — the same three
        labour rules as publication apply here in the same relative order, so a
        rest breach surfaces as `ERR_MIN_REST_VIOLATION`, an overlap created by the
        extension surfaces as `ERR_SHIFT_OVERLAP`, and an hours breach surfaces as
        `ERR_MAX_WEEKLY_HOURS_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/agent_rest_buffer_closed_boundary_on_ot_extension
        """
        world = _rest_buffer_week(api)
        respond_to_action(api, world["fitting"]["id"], world["agent"]["id"])

        response = _accept(
            api, world["overshooting"]["id"], world["agent"]["id"]
        )

        validate_error(response, ApiErrorId.MIN_REST_VIOLATION.value)

    def test_the_refused_extension_leaves_the_ledgers_at_the_accepted_figures(self, api):
        """The rejected offer stays open and unpriced while the ledgers hold 18000 and 5.00.

        "Both `ot_multiplier_applied` and `cost_cents` are frozen on the action at
        acceptance and are never recomputed afterwards."

        Design: Difficulty/resource_temporal_overlap/agent_rest_buffer_closed_boundary_on_ot_extension
        """
        world = _rest_buffer_week(api)
        respond_to_action(api, world["fitting"]["id"], world["agent"]["id"])

        _accept(api, world["overshooting"]["id"], world["agent"]["id"])

        refused = read_action(api, world["overshooting"]["id"])
        assert refused["status"] == ACTION_STATUS_OFFERED
        assert_cents(refused["cost_cents"], 0, "cost_cents")
        assert_cycle_ledgers(
            read_cycle(api, world["cycle"]["id"]),
            ot_spend_committed_cents=18000,
            ot_hours_committed=5.00,
        )

    def test_the_agent_carries_only_the_accepted_extension(self, api):
        """Fifteen published hours plus the five accepted overtime hours total 20.00.

        "The agent's `scheduled_hours_committed` — the sum of `paid_hours` over
        that agent's shifts whose `publication_status` is `PUBLISHED`, at two
        decimal places — and the cycle's `total_scheduled_hours` are both
        recomputed."

        Design: Difficulty/resource_temporal_overlap/agent_rest_buffer_closed_boundary_on_ot_extension
        """
        world = _rest_buffer_week(api)
        respond_to_action(api, world["fitting"]["id"], world["agent"]["id"])

        _accept(api, world["overshooting"]["id"], world["agent"]["id"])

        assert_agent_hours(read_agent(api, world["agent"]["id"]), 20.00)


def _commit(api, allocation_id, expected_partner_version):
    """Raw commitment by an operator other than the proposer."""
    return api.commit_partner_allocation(
        allocation_id,
        f.commit_allocation_payload(expected_partner_version),
        make_sourcing_headers(SOURCING_ALT_USER_ID),
    )


def _adjacency_world(api):
    """Two adjacent 82-contact intervals and three proposals: 50 and 40 here, 40 next door."""
    world = build_partner_week(api, cycle_overrides={"name": "W37-AGG"})
    partner = make_outsource_partner(
        api,
        legal_name="Adjacent Contact BV",
        interval_max_volume=50,
        commitment_floor_volume=10,
        billing_basis=BILLING_DELIVERED_ONLY,
    )
    first, second = world["intervals"][0], world["intervals"][1]
    world.update(
        {
            "partner": partner,
            "first_interval": first,
            "second_interval": second,
            "filling": propose_allocation(api, partner["id"], first["id"], 50),
            "overshooting": propose_allocation(api, partner["id"], first["id"], 40),
            "adjacent": propose_allocation(api, partner["id"], second["id"], 40),
        }
    )
    return world


class TestIntervalAggregateCapacityHalfOpenAdjacency:
    """Capacity is aggregated inside one interval span, never across the service date."""

    def test_the_first_commitment_consumes_fifty_of_the_interval(self, api):
        """Committing fifty against an allocatable eighty-two leaves thirty-two unserved.

        "On success the system stamps `committed_by_user_id`, adds
        `allocated_volume` to the partner's `committed_volume_outstanding`,
        recomputes the interval's `partner_committed_volume` and `unserved_volume`,
        and increments the partner's own `version` by 1."

        Design: Difficulty/resource_temporal_overlap/interval_aggregate_capacity_half_open_adjacency
        """
        world = _adjacency_world(api)

        committed = commit_allocation(
            api, world["filling"]["id"], world["partner"]["version"]
        )

        assert committed["status"] == ALLOCATION_COMMITTED
        assert_interval_outsourcing(
            read_interval(api, world["first_interval"]["id"]),
            allocatable_volume=82,
            partner_committed_volume=50,
            unserved_volume=32,
        )

    def test_a_second_commitment_reaching_ninety_in_one_interval_is_refused(self, api):
        """Fifty already committed plus forty more exceeds the interval's own ceiling.

        "Beyond that guard, commitment requires that the parent cycle is not
        frozen, that the acting `X-User-ID` differs from the allocation's
        `proposed_by_user_id`, that the partner's `status` is not `SUSPENDED`, that
        `allocated_volume` is at least the partner's `commitment_floor_volume`, and
        that the interval's `partner_committed_volume` plus this `allocated_volume`
        does not exceed the interval's `allocatable_volume` — the aggregate interval
        capacity ceiling, breaches of which are refused with
        `ERR_ALLOCATION_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/interval_aggregate_capacity_half_open_adjacency
        """
        world = _adjacency_world(api)
        commit_allocation(api, world["filling"]["id"], world["partner"]["version"])
        fresh = read_partner(api, world["partner"]["id"])

        response = _commit(api, world["overshooting"]["id"], fresh["version"])

        validate_error(response, ApiErrorId.ALLOCATION_CAPACITY_EXCEEDED.value)
        refused = read_allocation(api, world["overshooting"]["id"])
        assert refused["status"] == ALLOCATION_PROPOSED
        assert refused["committed_by_user_id"] is None

    def test_the_same_volume_commits_cleanly_against_the_adjacent_interval(self, api):
        """The forty refused next door is accepted on the following half hour.

        "`partner_committed_volume` is the sum of `allocated_volume` over the
        interval's partner allocations whose status is `COMMITTED` or `SETTLED`;
        proposed and revoked allocations contribute nothing, which means settling a
        commitment leaves the interval's committed volume unchanged while revoking
        one releases it."

        Design: Difficulty/resource_temporal_overlap/interval_aggregate_capacity_half_open_adjacency
        """
        world = _adjacency_world(api)
        commit_allocation(api, world["filling"]["id"], world["partner"]["version"])
        fresh = read_partner(api, world["partner"]["id"])
        _commit(api, world["overshooting"]["id"], fresh["version"])

        adjacent = commit_allocation(
            api, world["adjacent"]["id"], fresh["version"]
        )

        assert adjacent["status"] == ALLOCATION_COMMITTED
        assert_interval_outsourcing(
            read_interval(api, world["second_interval"]["id"]),
            allocatable_volume=82,
            partner_committed_volume=40,
            unserved_volume=42,
        )

    def test_the_partner_outstanding_volume_spans_both_intervals(self, api):
        """Fifty here and forty next door leave ninety outstanding on the partner.

        "`invoice_total_cents` aggregates only allocations whose `status` is
        `SETTLED`, while `committed_volume_outstanding` aggregates only those whose
        `status` is `COMMITTED`."

        Design: Difficulty/resource_temporal_overlap/interval_aggregate_capacity_half_open_adjacency
        """
        world = _adjacency_world(api)
        commit_allocation(api, world["filling"]["id"], world["partner"]["version"])
        fresh = read_partner(api, world["partner"]["id"])
        _commit(api, world["overshooting"]["id"], fresh["version"])
        commit_allocation(api, world["adjacent"]["id"], fresh["version"])

        assert_partner_ledgers(
            read_partner(api, world["partner"]["id"]),
            committed_volume_outstanding=90,
            invoice_total_cents=0,
        )
