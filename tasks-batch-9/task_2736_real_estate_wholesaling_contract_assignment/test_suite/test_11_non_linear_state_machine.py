"""
Machines that are not a straight line: the cyclic counter-and-revise loop that
terminates on a counter rather than on a status, and the three parallel status
dimensions of one purchase contract advancing one at a time.
"""

from test_helpers import (
    ApiErrorId,
    acknowledge_disclosures,
    add_verified_buyer,
    assert_assignment_offer,
    assert_cash_buyer,
    assert_nulls,
    assert_purchase_contract,
    build_draft_contract,
    build_marketed_contract,
    counter_offer,
    elect,
    factories,
    make_cash_buyer_headers,
    make_seller_headers,
    make_wholesaler_headers,
    read_buyer,
    read_contract,
    read_offer,
    revise_offer,
    submit_offer,
    validate_error,
    validate_success,
    MAX_NEGOTIATION_ROUNDS,
)

CONTRACT_TERMS = {
    "purchase_price_cents": 18000000,
    "earnest_money_cents": 500000,
    "inspection_period_days": 7,
}


def _marketed(api):
    return build_marketed_contract(
        api,
        clock="2026-08-10T00:00:00Z",
        buyer_price_cents=19000000,
        buyer_deposit_cents=1000000,
        structure_election="ASSIGNMENT_ELECTED",
        contract_kwargs=dict(CONTRACT_TERMS),
    )


class TestNegotiationLoopReentersCountered:
    """COUNTERED_BY_WHOLESALER and REVISED_BY_BUYER form a re-entered pair."""

    def test_counter_revise_counter_walks_the_round_counter_to_four(self, api):
        """
        "The wholesaler counters by supplying `countered_price_cents`, which
        drives the offer to `COUNTERED_BY_WHOLESALER` from either `SUBMITTED` or
        `REVISED_BY_BUYER`, records the countered price on the offer, and
        increments `negotiation_round` by one."

        "The buyer answers a counter by revising, which drives
        `COUNTERED_BY_WHOLESALER → REVISED_BY_BUYER`. Revision supplies fresh
        `buyer_price_cents` and `buyer_deposit_cents`, which overwrite the values
        on the offer, and it increments `negotiation_round` by one."

        "A successful offer enters status `SUBMITTED` with `negotiation_round` at
        1, `countered_price_cents` null, `accepted_at` null and
        `assignment_fee_cents` null."

        Design: Difficulty/non_linear_state_machine/assignment_offer_counter_revise_cycle_returns_to_countered
        """
        scenario = _marketed(api)
        assert_assignment_offer(
            scenario.offer,
            status="SUBMITTED",
            negotiation_round=1,
            buyer_price_cents=19000000,
            countered_price_cents=None,
        )

        first_counter = counter_offer(api, scenario.offer_id, scenario.w_id, 18800000)
        assert_assignment_offer(
            first_counter,
            status="COUNTERED_BY_WHOLESALER",
            negotiation_round=2,
            countered_price_cents=18800000,
            buyer_price_cents=19000000,
        )

        revised = revise_offer(
            api, scenario.offer_id, scenario.buyer_id, 18900000, 1000000
        )
        assert_assignment_offer(
            revised,
            status="REVISED_BY_BUYER",
            negotiation_round=3,
            buyer_price_cents=18900000,
        )

        second_counter = counter_offer(api, scenario.offer_id, scenario.w_id, 18850000)
        assert_assignment_offer(
            second_counter,
            status="COUNTERED_BY_WHOLESALER",
            negotiation_round=4,
            countered_price_cents=18850000,
            buyer_price_cents=18900000,
        )
        assert second_counter["status"] == first_counter["status"], (
            "the loop re-enters the very same status a second time, two rounds "
            f"later: {first_counter['status']} then {second_counter['status']}"
        )
        assert_cash_buyer(
            read_buyer(api, scenario.buyer_id, scenario.w_id),
            committed_deposit_cents=1000000,
            active_offer_count=1,
        )

    def test_fourth_round_revision_hits_the_cap_and_writes_nothing(self, api):
        """
        "Revision is available only from `COUNTERED_BY_WHOLESALER` — revising an
        offer in any other status is `ERR_INVALID_STATE` — and only while
        `negotiation_round` is strictly below four, the fourth round reporting
        `ERR_NEGOTIATION_ROUND_LIMIT`."

        "Because the cycle can run `SUBMITTED → COUNTERED_BY_WHOLESALER →
        REVISED_BY_BUYER → COUNTERED_BY_WHOLESALER` and round again, the round
        counter — not the status — is what terminates it; acceptance remains
        available on a fourth-round offer even though no further counter or
        revision is."

        Design: Difficulty/non_linear_state_machine/assignment_offer_counter_revise_cycle_returns_to_countered
        """
        scenario = _marketed(api)
        counter_offer(api, scenario.offer_id, scenario.w_id, 18800000)
        revise_offer(api, scenario.offer_id, scenario.buyer_id, 18900000, 1000000)
        capped = counter_offer(api, scenario.offer_id, scenario.w_id, 18850000)
        assert capped["negotiation_round"] == MAX_NEGOTIATION_ROUNDS, (
            "the loop must have walked the counter to the four-round cap, got "
            f"{capped['negotiation_round']}"
        )

        response = api.revise_assignment_offer(
            scenario.offer_id,
            factories.revise_payload(18860000, 1000000),
            make_cash_buyer_headers(scenario.buyer_id),
        )
        validate_error(response, ApiErrorId.NEGOTIATION_ROUND_LIMIT, 409)

        # The status is still a legal source for revision; only the counter
        # stopped the loop, and the rejected call wrote nothing.
        assert_assignment_offer(
            read_offer(api, scenario.offer_id, scenario.w_id),
            status="COUNTERED_BY_WHOLESALER",
            negotiation_round=4,
            buyer_price_cents=18900000,
            countered_price_cents=18850000,
        )
        assert_cash_buyer(
            read_buyer(api, scenario.buyer_id, scenario.w_id),
            committed_deposit_cents=1000000,
            active_offer_count=1,
        )


class TestThreeDimensionsAdvanceIndependently:
    """One row, three machines; each write moves exactly one of them."""

    def test_signing_and_electing_leave_the_other_two_dimensions_alone(self, api):
        """
        "**Signing.** The seller drives `contract_status` from `DRAFT` to
        `SIGNED`, and it is the seller alone who may do so."

        "A successful create initialises all three of the contract's independent
        status dimensions: `contract_status` to `DRAFT`, `assignment_status` to
        `NOT_MARKETED` and `structure_election` to `UNDECIDED`. These three
        dimensions advance independently of one another and none of them
        constrains another's transitions except where a precondition explicitly
        says so."

        "`signed_at`, `inspection_deadline_at`, the four double-close funding
        figures, `cancellation_reason` and `cancelled_at` all begin null."

        Design: Difficulty/non_linear_state_machine/purchase_contract_parallel_dimensions_advance_independently
        """
        scenario = build_draft_contract(
            api, clock="2026-08-10T00:00:00Z", contract_kwargs=dict(CONTRACT_TERMS)
        )
        assert_purchase_contract(
            scenario.contract,
            contract_status="DRAFT",
            assignment_status="NOT_MARKETED",
            structure_election="UNDECIDED",
        )
        acknowledge_disclosures(api, scenario.pc_id, scenario.lead_id)

        signed = validate_success(
            api.sign_purchase_contract(
                scenario.pc_id, make_seller_headers(scenario.lead_id)
            ),
            200,
        )
        assert_purchase_contract(
            signed,
            contract_status="SIGNED",
            assignment_status="NOT_MARKETED",
            structure_election="UNDECIDED",
            signed_at="2026-08-10T00:00:00Z",
            inspection_deadline_at="2026-08-17T00:00:00Z",
        )

        elected = elect(api, scenario.pc_id, scenario.w_id, "ASSIGNMENT_ELECTED")
        assert_purchase_contract(
            elected,
            structure_election="ASSIGNMENT_ELECTED",
            contract_status="SIGNED",
            assignment_status="NOT_MARKETED",
        )
        assert_nulls(
            elected,
            "funding_base_cents",
            "transactional_lender_fee_cents",
            "total_funding_required_cents",
            label="purchase_contract",
        )

    def test_first_offer_moves_only_marketing_and_re_election_only_the_structure(
        self, api
    ):
        """
        "It also touches the contract: the first offer drives
        `assignment_status` from `NOT_MARKETED` to `MARKETED`, which requires the
        contract's `contract_status` to be `SIGNED` or `PENDING_CLOSE` and
        requires either `assignment_rights_granted` to be true or
        `structure_election` to be `DOUBLE_CLOSE_ELECTED`"

        "The election is re-elective in both directions while nothing has been
        papered. Moving `ASSIGNMENT_ELECTED → DOUBLE_CLOSE_ELECTED` requires only
        that `assignment_status` is not yet `ASSIGNED`."

        "**Sizing the double close.** Electing `DOUBLE_CLOSE_ELECTED` — from
        `UNDECIDED` or from `ASSIGNMENT_ELECTED` — runs the funding schedule."

        "Step five is the spread, and it stays null until an offer on this
        contract reaches `ACCEPTED`: `double_close_spread_cents` is the accepted
        offer's `buyer_price_cents` less `total_funding_required_cents`."

        Design: Difficulty/non_linear_state_machine/purchase_contract_parallel_dimensions_advance_independently
        """
        scenario = build_draft_contract(
            api, clock="2026-08-10T00:00:00Z", contract_kwargs=dict(CONTRACT_TERMS)
        )
        acknowledge_disclosures(api, scenario.pc_id, scenario.lead_id)
        validate_success(
            api.sign_purchase_contract(
                scenario.pc_id, make_seller_headers(scenario.lead_id)
            ),
            200,
        )
        elect(api, scenario.pc_id, scenario.w_id, "ASSIGNMENT_ELECTED")
        add_verified_buyer(scenario)

        offer = submit_offer(
            api,
            scenario.pc_id,
            scenario.buyer_id,
            20160000,
            scenario.refresh_contract()["version"],
            buyer_deposit_cents=1000000,
        )
        assert_assignment_offer(offer, status="SUBMITTED", negotiation_round=1)
        assert_purchase_contract(
            read_contract(api, scenario.pc_id, scenario.w_id),
            assignment_status="MARKETED",
            contract_status="SIGNED",
            structure_election="ASSIGNMENT_ELECTED",
        )

        response = api.elect_structure(
            scenario.pc_id,
            factories.elect_structure_payload("DOUBLE_CLOSE_ELECTED"),
            make_wholesaler_headers(scenario.w_id),
        )
        re_elected = validate_success(response, 200)

        # 18000000 x 0.021 == 378000, and tier two on the 18378000 base gives
        # 18378000 x 0.0225 == 413505.
        assert_purchase_contract(
            re_elected,
            structure_election="DOUBLE_CLOSE_ELECTED",
            contract_status="SIGNED",
            assignment_status="MARKETED",
            funding_base_cents=18378000,
            transactional_lender_fee_cents=413505,
            total_funding_required_cents=18791505,
            double_close_spread_cents=None,
        )
        assert_assignment_offer(
            read_offer(api, offer["id"], scenario.w_id), status="SUBMITTED"
        )
