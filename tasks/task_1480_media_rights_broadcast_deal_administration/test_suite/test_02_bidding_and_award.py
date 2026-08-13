"""Bidding cycle: fee floor boundary, submission gates, counter-offer loop,
award side effects, and OCC on package accept."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_winning_bid,
    create_accredited_broadcaster,
    create_bid_payload,
    create_package,
    create_rights_asset,
    file_bid,
    get_bid,
    get_deal,
    get_package,
    lock_asset_packages,
    make_bid_coordinator_headers,
    setup_open_market,
    setup_shortlisted_bid,
    setup_submitted_bid,
    submit_bid,
    validate_error,
    validate_success,
    walk_bid_to_shortlisted,
)

RM = TEST_USERS["rights_manager_headers"]


class TestBidFloorBoundary:
    def test_bid_one_cent_below_floor_rejected(self, api):
        """PRD §3.3: "second, `offered_fee_cents` must meet the package's
        floor (`ERR_BID_BELOW_FLOOR`)".

        Design: Difficulty/boundary_precision_check/bid_floor_exact_equality
        """
        asset, package = setup_open_market(
            package_overrides={"minimum_bid_cents": 5000000}
        )
        broadcaster = create_accredited_broadcaster()
        headers = make_bid_coordinator_headers(broadcaster["id"])
        res = api.create_bid(
            package["id"],
            create_bid_payload(
                bidder_id=broadcaster["id"],
                offered_fee_cents=4999999,
                fee_cap_cents=10000000,
                production_commitment_games=package["games_committed"],
            ),
            headers,
        )
        validate_error(res, "ERR_BID_BELOW_FLOOR", expected_status=422)

    def test_bid_exactly_at_floor_accepted_and_submittable(self, api):
        """PRD §3.3: "second, `offered_fee_cents` must meet the package's
        floor (`ERR_BID_BELOW_FLOOR`)" — an offer exactly equal to the floor
        meets it.
        PRD §3.3: "Submission is a separate act by the `BidCoordinator`, and
        it re-runs the fee-floor and production-commitment checks."

        Design: Difficulty/boundary_precision_check/bid_floor_exact_equality
        """
        asset, package = setup_open_market(
            package_overrides={"minimum_bid_cents": 5000000}
        )
        broadcaster = create_accredited_broadcaster()
        bid = file_bid(
            package["id"],
            broadcaster["id"],
            offered_fee_cents=5000000,
            fee_cap_cents=10000000,
            production_commitment_games=package["games_committed"],
        )
        assert bid["status"] == "DRAFT"
        submitted = submit_bid(package["id"], bid["id"], broadcaster["id"])
        assert submitted["status"] == "SUBMITTED"


class TestSubmissionGates:
    def test_submit_on_withdrawn_package_rejected(self, api):
        """PRD §3.3: "Submitting requires the bid to be `DRAFT`
        (`ERR_BID_NOT_DRAFT`), the package to be `OPEN_FOR_BIDS` or
        `UNDER_NEGOTIATION` (`ERR_PACKAGE_NOT_ACCEPTING_BIDS`)".

        Design: Difficulty/cross_entity_state_dependency/bid_submit_requires_package_accepting_bids
        """
        asset, package = setup_open_market()
        broadcaster = create_accredited_broadcaster()
        api.withdraw_package(package["id"], RM)
        bid = file_bid(package["id"], broadcaster["id"])
        res = api.submit_bid(
            package["id"], bid["id"], make_bid_coordinator_headers(broadcaster["id"])
        )
        validate_error(res, "ERR_PACKAGE_NOT_ACCEPTING_BIDS", expected_status=409)
        assert get_bid(package["id"], bid["id"])["status"] == "DRAFT"

    def test_first_submission_flips_package_to_under_negotiation(self, api):
        """PRD §3.3: "The first submission on a package still in
        `OPEN_FOR_BIDS` flips the package to `UNDER_NEGOTIATION`, signaling
        that the market has engaged."

        Design: Difficulty/cross_entity_state_dependency/bid_submit_requires_package_accepting_bids
        """
        asset, package = setup_open_market()
        assert package["status"] == "OPEN_FOR_BIDS"
        broadcaster = create_accredited_broadcaster()
        bid = file_bid(package["id"], broadcaster["id"])
        submitted = submit_bid(package["id"], bid["id"], broadcaster["id"])
        assert submitted["status"] == "SUBMITTED"
        package_after = get_package(package["id"])
        assert package_after["status"] == "UNDER_NEGOTIATION"

    def test_submit_on_withdrawn_package_state_gate_preempts(self, api):
        """PRD §3.3: "Submitting requires the bid to be `DRAFT`
        (`ERR_BID_NOT_DRAFT`), the package to be `OPEN_FOR_BIDS` or
        `UNDER_NEGOTIATION` (`ERR_PACKAGE_NOT_ACCEPTING_BIDS`), and the
        bidding broadcaster to be `ACCREDITED`
        (`ERR_BROADCASTER_NOT_ACCREDITED`)."
        PRD §2.12: "Fourth, the target entity's state machine is consulted,
        and an illegal transition is rejected with the state-specific 409
        error named in §3".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_bid_submission
        """
        asset, package = setup_open_market()
        broadcaster = create_accredited_broadcaster(credit_rating="SPECULATIVE")
        api.withdraw_package(package["id"], RM)
        # File succeeds while DRAFT; the submit then hits the package state gate.
        bid = file_bid(package["id"], broadcaster["id"])
        res = api.submit_bid(
            package["id"], bid["id"], make_bid_coordinator_headers(broadcaster["id"])
        )
        validate_error(res, "ERR_PACKAGE_NOT_ACCEPTING_BIDS", expected_status=409)

    def test_broader_exclusivity_requires_investment_grade(self, api):
        """PRD §3.3: "first, a request for `BROADER` exclusivity is permitted
        only when the bidder's `credit_rating` is `INVESTMENT_GRADE`
        (`ERR_BIDDER_NOT_GRADE_FOR_BROADER`)".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_bid_submission
        """
        asset, package = setup_open_market()
        broadcaster = create_accredited_broadcaster(credit_rating="SPECULATIVE")
        res = api.create_bid(
            package["id"],
            create_bid_payload(
                bidder_id=broadcaster["id"], exclusivity_request="BROADER"
            ),
            make_bid_coordinator_headers(broadcaster["id"]),
        )
        validate_error(res, "ERR_BIDDER_NOT_GRADE_FOR_BROADER", expected_status=422)


class TestCounterOfferLoop:
    def test_counter_moves_shortlisted_bid_to_countered(self, api):
        """PRD §3.3: "Countering a `SHORTLISTED` bid
        (`ERR_BID_NOT_SHORTLISTED` otherwise) moves it to `COUNTERED`".

        Design: Difficulty/non_linear_state_machine/bid_cyclic_counter_offer_loop
        """
        bundle = setup_shortlisted_bid()
        package, bid = bundle["package"], bundle["bid"]
        countered = validate_success(
            api.counter_bid(package["id"], bid["id"], RM), 200
        )
        assert countered["status"] == "COUNTERED"

    def test_successor_bid_increments_round_and_reenters_submitted(self, api):
        """PRD §3.3: "A filed bid starts in `DRAFT` with `round_number` 1 —
        unless it is a counter-offer carrying an optional `parent_bid_id`,
        in which case its `round_number` is one greater than its parent's."
        PRD §3.3: "the `BidCoordinator` is expected to answer by filing a
        fresh bid whose `parent_bid_id` references the countered one and
        whose `round_number` is incremented accordingly."

        Design: Difficulty/non_linear_state_machine/bid_cyclic_counter_offer_loop
        """
        bundle = setup_shortlisted_bid()
        package, bid1 = bundle["package"], bundle["bid"]
        broadcaster = bundle["broadcaster"]
        validate_success(api.counter_bid(package["id"], bid1["id"], RM), 200)

        bid2 = file_bid(
            package["id"],
            broadcaster["id"],
            offered_fee_cents=27000000,
            parent_bid_id=bid1["id"],
        )
        assert bid2["round_number"] == 2
        assert bid2["parent_bid_id"] == bid1["id"]
        assert bid2["status"] == "DRAFT"

        submitted = submit_bid(package["id"], bid2["id"], broadcaster["id"])
        assert submitted["status"] == "SUBMITTED"
        assert get_bid(package["id"], bid1["id"])["status"] == "COUNTERED"


class TestBidTransitionErrors:
    def test_shortlist_directly_from_draft_rejected(self, api):
        """PRD §3.3: "Shortlisting moves `UNDER_REVIEW` to `SHORTLISTED`
        (`ERR_BID_NOT_UNDER_REVIEW` otherwise)."

        Design: Corner/state_machines/invalid_transition_bid_draft_to_shortlist
        """
        asset, package = setup_open_market()
        broadcaster = create_accredited_broadcaster()
        bid = file_bid(package["id"], broadcaster["id"])
        res = api.shortlist_bid(package["id"], bid["id"], RM)
        validate_error(res, "ERR_BID_NOT_UNDER_REVIEW", expected_status=409)
        assert get_bid(package["id"], bid["id"])["status"] == "DRAFT"

    def test_reject_accepted_bid_rejected_terminal_lockdown(self, api):
        """PRD §3.3: "Rejection is available from `UNDER_REVIEW`,
        `SHORTLISTED`, or `COUNTERED` (`ERR_BID_NOT_REJECTABLE` otherwise)
        and lands the bid in `REJECTED`."

        Design: Corner/state_machines/terminal_state_lockdown_bid_accepted
        """
        bundle = setup_shortlisted_bid()
        package, bid = bundle["package"], bundle["bid"]
        accept_winning_bid(package["id"], bid["id"])
        res = api.reject_bid(package["id"], bid["id"], RM)
        validate_error(res, "ERR_BID_NOT_REJECTABLE", expected_status=409)
        assert get_bid(package["id"], bid["id"])["status"] == "ACCEPTED"


class TestAwardEffects:
    def test_accept_increments_package_version_and_awards(self, api):
        """PRD §3.3: "the package moves to `AWARDED` with its
        `awarded_bid_id` and `awarded_deal_id` populated and its `version`
        incremented".

        Design: Corner/cross_cutting_complexity_layers/occ_package_version_increments_on_accept
        """
        bundle = setup_shortlisted_bid()
        package, bid = bundle["package"], bundle["bid"]
        version_before = get_package(package["id"])["version"]
        deal = accept_winning_bid(package["id"], bid["id"])
        package_after = get_package(package["id"])
        assert package_after["version"] == version_before + 1
        assert package_after["status"] == "AWARDED"
        assert package_after["awarded_bid_id"] == bid["id"]
        assert package_after["awarded_deal_id"] == deal["id"]

    def test_deal_visible_immediately_after_accept(self, api):
        """PRD §3.3: "a new deal is auto-created in `DRAFT` status with
        `winning_bid_id` pointing at the accepted bid".
        PRD §3.4: "along with the `winning_bid_id` and a `broadcaster_id`
        denormalized from the winning bid."

        Design: Corner/consistency_model/immediate_visibility_of_deal_after_accept
        """
        bundle = setup_shortlisted_bid()
        package, bid, broadcaster = (
            bundle["package"],
            bundle["bid"],
            bundle["broadcaster"],
        )
        deal = accept_winning_bid(package["id"], bid["id"])
        fetched = get_deal(deal["id"])
        assert fetched["status"] == "DRAFT"
        assert fetched["winning_bid_id"] == bid["id"]
        assert fetched["broadcaster_id"] == broadcaster["id"]
