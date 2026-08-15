"""Deal execution: OCC stale-version gate and the escalated fee schedule."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_payment_milestone,
    add_production_obligation,
    execute_deal_payload,
    get_deal,
    get_milestone,
    setup_awarded_deal,
    setup_executed_deal,
    validate_error,
    validate_success,
)

RM = TEST_USERS["rights_manager_headers"]


class TestOptimisticConcurrencyOnExecute:
    def test_execute_with_stale_deal_version_rejected(self, api):
        """PRD §2.7: "If the deal's current `version` has advanced beyond
        that value — because another writer has amended the deal, for
        instance by adding payment milestones — the execution is rejected
        with `ERR_STALE_DEAL_VERSION` (HTTP 412)".

        Design: Corner/errors/error_stale_deal_version_triggerable
        """
        bundle = setup_awarded_deal()
        deal = bundle["deal"]
        observed_version = deal["version"]

        # Adding a payment milestone amends the deal and advances its version.
        add_payment_milestone(bundle["deal"]["id"])
        add_production_obligation(bundle["deal"]["id"])
        refreshed = get_deal(deal["id"])
        assert refreshed["version"] != observed_version

        res = api.execute_deal(
            deal["id"], execute_deal_payload(observed_version), RM
        )
        validate_error(res, "ERR_STALE_DEAL_VERSION", expected_status=412)

        # Control: the same call with the current version succeeds.
        ok = api.execute_deal(
            deal["id"], execute_deal_payload(get_deal(deal["id"])["version"]), RM
        )
        executed = validate_success(ok, 200)
        assert executed["status"] == "EXECUTED"


class TestEscalatedRightsFee:
    def test_season_one_fee_is_base_capped(self, api):
        """PRD §3.4: "in season 1 the fee is simply the smaller of
        `base_fee_cents` and the cap."

        Design: Difficulty/combinatorial_formula/escalated_rights_fee_three_input_nested_max_min
        """
        bundle = setup_executed_deal(
            bid_overrides={
                "offered_fee_cents": 100000000,
                "escalator_rate_pct": 0.03,
                "minimum_growth_pct": 0.10,
                "fee_cap_cents": 120000000,
            },
            package_overrides={"minimum_bid_cents": 100000000},
        )
        ms1 = get_milestone(bundle["deal"]["id"], bundle["milestones"][0]["id"])
        # fee_1 = min(100000000, 120000000) = 100000000; weight 1.0.
        assert ms1["base_amount_cents"] == 100000000

    def test_season_two_min_growth_floor_dominates_compounding(self, api):
        """PRD §3.4: "The growth floor for season 1 equals that compounded
        value; for every later season it equals the prior season's escalated
        fee multiplied by (1 + `minimum_growth_pct`). The pre-cap fee is the
        larger of the compounded value and the growth floor, and the season's
        fee is the smaller of that pre-cap fee and `fee_cap_cents`, rounded
        half-up to whole cents."

        Season 2 here: compounded 100000000*1.03 = 103000000; floor
        100000000*1.10 = 110000000; pre-cap 110000000; under the 120000000
        cap, so the season-2 milestone carries 110000000.

        Design: Difficulty/combinatorial_formula/escalated_rights_fee_three_input_nested_max_min
        """
        bundle = setup_executed_deal(
            bid_overrides={
                "offered_fee_cents": 100000000,
                "escalator_rate_pct": 0.03,
                "minimum_growth_pct": 0.10,
                "fee_cap_cents": 120000000,
            },
            package_overrides={"minimum_bid_cents": 100000000},
            term_start="2026-01-01T00:00:00Z",
            term_end="2027-12-31T23:59:59Z",
        )
        ms2 = add_payment_milestone(
            bundle["deal"]["id"],
            season_index=2,
            sequence_in_season=1,
            due_date="2027-02-01T00:00:00Z",
            milestone_weight=1.0,
        )
        assert ms2["base_amount_cents"] == 110000000


class TestPaymentScheduleAllocation:
    def test_per_milestone_rounding_reconciles_exactly(self, api):
        """PRD §3.4: "Each milestone's pre-round amount is the season fee
        multiplied by its weight; each such amount is rounded half-up to
        whole cents, and rounding happens per milestone before any
        reconciliation."

        Design: Difficulty/combinatorial_formula/payment_schedule_allocation_nested_rounding
        """
        bundle = setup_executed_deal(
            milestone_specs=[
                (1, 1, "2026-09-01T00:00:00Z", 0.333),
                (1, 2, "2026-10-01T00:00:00Z", 0.333),
                (1, 3, "2026-11-01T00:00:00Z", 0.334),
            ],
            bid_overrides={
                "offered_fee_cents": 100000000,
                "escalator_rate_pct": 0.0,
                "minimum_growth_pct": 0.0,
                "fee_cap_cents": 200000000,
            },
            package_overrides={"minimum_bid_cents": 100000000},
        )
        deal_id = bundle["deal"]["id"]
        amounts = [
            get_milestone(deal_id, m["id"])["base_amount_cents"]
            for m in bundle["milestones"]
        ]
        assert amounts == [33300000, 33300000, 33400000]
        assert sum(amounts) == 100000000

    def test_remainder_cent_goes_to_earliest_sequence(self, api):
        """PRD §3.4: "The remainder — the season fee minus the sum of the
        rounded amounts — is then distributed one cent at a time to the
        season's milestones in ascending `sequence_in_season` order, breaking
        ties by earlier `created_at`".

        Season fee 100000001 with weights 0.334/0.333/0.333 rounds to
        33400000 + 33300000 + 33300000 = 100000000, leaving a remainder of
        one cent that lands on sequence 1.

        Design: Difficulty/combinatorial_formula/payment_schedule_allocation_nested_rounding
        """
        bundle = setup_executed_deal(
            milestone_specs=[
                (1, 1, "2026-09-01T00:00:00Z", 0.334),
                (1, 2, "2026-10-01T00:00:00Z", 0.333),
                (1, 3, "2026-11-01T00:00:00Z", 0.333),
            ],
            bid_overrides={
                "offered_fee_cents": 100000001,
                "escalator_rate_pct": 0.0,
                "minimum_growth_pct": 0.0,
                "fee_cap_cents": 200000000,
            },
            package_overrides={"minimum_bid_cents": 100000001},
        )
        deal_id = bundle["deal"]["id"]
        amounts = [
            get_milestone(deal_id, m["id"])["base_amount_cents"]
            for m in bundle["milestones"]
        ]
        assert amounts == [33400001, 33300000, 33300000]
        assert sum(amounts) == 100000001


class TestComputedFieldsAtExecution:
    def test_total_contracted_fee_sums_escalated_seasons(self, api):
        """PRD §3.4: "On execution the deal's `executed_at` is stamped with
        the current logical clock, its `version` increments, and two
        computed fields are fixed: `total_contracted_fee_cents`, the sum
        over all seasons of the escalated rights fee, and
        `audience_commitment_basis_points`, the asset's
        `guaranteed_rating_basis_points` multiplied by the winning bid's
        `audience_commitment_pct`, rounded to integer basis points."

        Two-season term at escalator 0.05: 100000000 + 105000000.

        Design: Corner/entities/deal_total_contracted_fee_computed
        """
        bundle = setup_executed_deal(
            milestone_specs=[
                (1, 1, "2026-09-01T00:00:00Z", 1.0),
                (2, 1, "2027-02-01T00:00:00Z", 1.0),
            ],
            bid_overrides={
                "offered_fee_cents": 100000000,
                "escalator_rate_pct": 0.05,
                "minimum_growth_pct": 0.0,
                "fee_cap_cents": 200000000,
                "audience_commitment_pct": 0.5,
            },
            package_overrides={"minimum_bid_cents": 100000000},
            term_start="2026-01-01T00:00:00Z",
            term_end="2027-12-31T23:59:59Z",
        )
        deal = get_deal(bundle["deal"]["id"])
        assert deal["total_contracted_fee_cents"] == 205000000
        assert deal["audience_commitment_basis_points"] == 1500
