"""The cooperative dimension: the gross and net patronage measures, board
ratification, and the capped largest-remainder distribution waterfall."""

from test_helpers import (
    CLOCK_BASE,
    HUB,
    ApiErrorId,
    assert_patronage_cycle,
    assert_pool_conserved,
    distribute_cycle,
    make_board_director_headers,
    onboard_active_producer,
    propose_cycle,
    ratify_cycle,
    read_cycle,
    read_producer,
    set_clock,
    setup_paid_order_with_shrink,
    validate_error,
    validate_success,
)


class TestPatronageBasis:
    def test_ratification_freezes_the_net_basis_after_shrink(self, api):
        """PRD 3.9: "A `RATIFY` decision moves the cycle `PROPOSED → RATIFIED`
        and freezes the membership snapshot: a producer is eligible if it is
        `ACTIVE`, its compliance is currently satisfied, and its net basis is
        greater than zero; `basis_snapshot_total_cents` becomes the sum of the
        net bases of the eligible producers and `eligible_producer_count`
        becomes how many there were."
        PRD 3.9: "Either decision records the acting user id in
        `ratified_by_user_id`."

        Design: Difficulty/dual_variant_calc/patronage_basis_gross_volume_versus_net_ratification_snapshot
        """
        setup_paid_order_with_shrink()
        cycle = propose_cycle(fiscal_year=2026, distributable_pool_cents=1_000_000)

        data = validate_success(
            api.ratify_patronage_cycle(
                cycle["id"], {"decision": "RATIFY"},
                make_board_director_headers("director-7"),
            )
        )
        assert_patronage_cycle(data)
        assert data["status"] == "RATIFIED"
        assert data["basis_snapshot_total_cents"] == 105930
        assert data["eligible_producer_count"] == 1
        assert data["ratified_by_user_id"] == "director-7"

    def test_the_gross_volume_differs_from_the_frozen_net_snapshot(self, api):
        """PRD 3.9: "The **gross** measure is the running
        `patronage_volume_cents` on each producer, credited allocation by
        allocation as orders reach `PAID` and carrying no deduction for shrink.
        The **net** measure is that same figure less the producer's cumulative
        `shrink_charge_cents`, floored at zero, and it exists only at
        ratification time. For identical underlying rows the two measures give
        different per-member bases and therefore different shares — a member
        with approved rejection claims against it looks larger on the gross
        measure than on the net one."

        Design: Difficulty/dual_variant_calc/patronage_basis_gross_volume_versus_net_ratification_snapshot
        """
        scenario = setup_paid_order_with_shrink()
        producer = read_producer(scenario["producer_id"])
        assert producer["patronage_volume_cents"] == 108000
        assert producer["shrink_charge_cents"] == 2070

        cycle = propose_cycle(fiscal_year=2026, distributable_pool_cents=1_000_000)
        ratified = ratify_cycle(cycle["id"])

        assert ratified["basis_snapshot_total_cents"] == 105930
        assert (
            ratified["basis_snapshot_total_cents"]
            != producer["patronage_volume_cents"]
        ), "the net snapshot subtracts the shrink charge the gross measure keeps"


class TestCycleGovernance:
    def test_a_second_cycle_for_the_same_fiscal_year_is_refused(self, api):
        """PRD 3.9: "A distribution begins as a proposal from hub operations
        naming a `fiscal_year`, which must be an integer from 2000 through 2100
        and must not already be claimed by another cycle — a duplicate is
        refused with `ERR_DUPLICATE_FISCAL_YEAR` — and a
        `distributable_pool_cents` of at least 1 cent, the board-proposed
        surplus."

        Design: Corner/errors/second_patronage_cycle_for_the_same_fiscal_year_is_rejected
        """
        set_clock(CLOCK_BASE)
        first = propose_cycle(fiscal_year=2026, distributable_pool_cents=500000)

        resp = api.create_patronage_cycle(
            {"fiscal_year": 2026, "distributable_pool_cents": 900000}, HUB
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_FISCAL_YEAR.value, 409)

        unchanged = read_cycle(first["id"])
        assert unchanged["status"] == "PROPOSED"
        assert unchanged["distributable_pool_cents"] == 500000

    def test_ratification_without_a_positive_net_basis_is_refused(self, api):
        """PRD 3.9: "If that frozen total is not greater than zero — no eligible
        member has any net basis at all — ratification is refused with
        `ERR_NO_PATRONAGE_BASIS` and the cycle stays `PROPOSED`."

        Design: Corner/errors/ratification_with_no_positive_patronage_basis_is_rejected
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        assert read_producer(onboarded["producer_id"])["patronage_volume_cents"] == 0
        cycle = propose_cycle(fiscal_year=2026, distributable_pool_cents=500000)

        resp = api.ratify_patronage_cycle(
            cycle["id"], {"decision": "RATIFY"},
            make_board_director_headers("director-7"),
        )
        validate_error(resp, ApiErrorId.ERR_NO_PATRONAGE_BASIS.value, 422)

        unchanged = read_cycle(cycle["id"])
        assert unchanged["status"] == "PROPOSED"
        assert unchanged["basis_snapshot_total_cents"] == 0
        assert unchanged["eligible_producer_count"] == 0

    def test_distribution_before_ratification_is_refused(self, api):
        """PRD 3.9: "Distribution is executed by hub operations against a cycle
        that is `RATIFIED`, and any other status is refused with
        `ERR_INVALID_CYCLE_STATE`."
        PRD 3.9: "The cycle enters `PROPOSED` with `proposed_by_user_id`
        stamped, no `ratified_by_user_id`, and `basis_snapshot_total_cents`,
        `eligible_producer_count`, `distributed_total_cents` and
        `remainder_cents` all at 0."

        Design: Corner/errors/distribution_before_ratification_returns_invalid_cycle_state
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        cycle = propose_cycle(fiscal_year=2026, distributable_pool_cents=500000)

        resp = api.distribute_patronage_cycle(cycle["id"], HUB)
        validate_error(resp, ApiErrorId.ERR_INVALID_CYCLE_STATE.value, 409)

        unchanged = read_cycle(cycle["id"])
        assert unchanged["status"] == "PROPOSED"
        assert unchanged["distributed_total_cents"] == 0
        assert unchanged["remainder_cents"] == 0
        assert read_producer(onboarded["producer_id"])["retained_patronage_cents"] == 0


class TestDistributionWaterfall:
    def test_the_capped_distribution_conserves_the_pool(self, api):
        """PRD 3.9: "The cycle records the outcome: `distributed_total_cents` is
        the sum of what was actually credited and `remainder_cents` is the pool
        less that sum, and the two always add back to `distributable_pool_cents`
        exactly."
        PRD 3.9: "The cap makes this waterfall lossy on purpose — when the
        per-member ceiling binds for every eligible member, the pool simply
        cannot be fully distributed, and the undistributed balance stays with
        the hub as an unallocated reserve rather than being forced onto
        members."

        Design: Difficulty/compensating_invariant/patronage_distribution_conserves_the_equity_pool_under_the_member_cap
        """
        setup_paid_order_with_shrink()
        cycle = propose_cycle(fiscal_year=2026, distributable_pool_cents=1_000_000)
        ratified = ratify_cycle(cycle["id"])
        assert ratified["basis_snapshot_total_cents"] == 105930

        data = validate_success(api.distribute_patronage_cycle(cycle["id"], HUB))
        assert data["status"] == "DISTRIBUTED"
        assert data["distributed_total_cents"] == 300000
        assert data["remainder_cents"] == 700000
        assert data["distributed_total_cents"] + data["remainder_cents"] == 1_000_000
        assert_pool_conserved(data)
        assert_pool_conserved(read_cycle(cycle["id"]))

    def test_the_member_ceiling_limits_the_credited_share(self, api):
        """PRD 3.9: "First, a per-member ceiling is computed: no member may
        receive more than 3000 basis points — 30 percent — of the pool, and that
        ceiling is the pool multiplied by 3000, divided by 10000, taken **down**
        to the whole cent below."
        PRD 3.9: "Each eligible member's `retained_patronage_cents` then rises
        by its final share, ceiling-limited and inclusive of any cents won in
        the walk."

        Design: Difficulty/compensating_invariant/patronage_distribution_conserves_the_equity_pool_under_the_member_cap
        """
        scenario = setup_paid_order_with_shrink()
        cycle = propose_cycle(fiscal_year=2026, distributable_pool_cents=1_000_000)
        ratify_cycle(cycle["id"])

        distribute_cycle(cycle["id"])

        producer = read_producer(scenario["producer_id"])
        assert producer["retained_patronage_cents"] == 300000, (
            "the sole member is clamped to floor(1000000 * 3000 / 10000)"
        )
        assert read_cycle(cycle["id"])["distributed_total_cents"] == 300000
