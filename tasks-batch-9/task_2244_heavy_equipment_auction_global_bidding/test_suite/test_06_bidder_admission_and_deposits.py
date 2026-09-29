"""Buyer admission: deposits, country tiers, paddles and the credit decision."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bidder_registration,
    assert_deposit_ledger_conserved,
    create_bid_payload,
    create_bidder_registration_payload,
    credit_decision_payload,
    funded_bidder,
    make_bidder_headers,
    new_auction,
    new_yard,
    open_auction_with_catalogue,
    place_bid,
    reset_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import OPERATOR, SETTLEMENT

IRANIAN_BUYER = {
    "legal_name": "Pars Machinery Trading",
    "country_code": "IR",
    "tax_id": "IR-0000001",
}


def _timed_online_window(day: int):
    return {
        "kind": "TIMED_ONLINE",
        "window_start": f"2026-08-0{day}T00:00:00Z",
        "window_end": f"2026-08-{day + 7:02d}T00:00:00Z",
    }


class TestPaddleAllocation:
    def test_paddles_are_minted_by_the_server_starting_at_one_hundred_and_one(self):
        """Neither client supplies a paddle, and the two registrations at one event come back
        holding 101 and 102.

        PRD 3.5: "A successful create puts the registration in `REQUESTED` at `version` 1,
        moves `deposit_hold_cents` from the bidder's `deposit_available_cents` to its
        `deposit_held_cents`, and allocates a `paddle_number`: one greater than the highest
        paddle already issued at that auction, starting at 101 when the auction has none."

        Design: Corner/entities/bidder_registration_paddle_number_is_system_allocated
        """
        reset_clock()
        yard = new_yard()
        auction = new_auction(yard)
        first_bidder = funded_bidder(200_000, reference="WIRE-US-1")
        second_bidder = funded_bidder(
            200_000,
            reference="WIRE-US-2",
            legal_name="Sabine Equipment Co",
            tax_id="US-74-0000002",
        )

        first = validate_success(
            api_client.create_bidder_registration(
                create_bidder_registration_payload(
                    first_bidder["id"], auction["id"], 100_000
                ),
                make_bidder_headers(first_bidder["id"]),
            ),
            expected_status=201,
        )
        second = validate_success(
            api_client.create_bidder_registration(
                create_bidder_registration_payload(
                    second_bidder["id"], auction["id"], 100_000
                ),
                make_bidder_headers(second_bidder["id"]),
            ),
            expected_status=201,
        )

        for registration in (first, second):
            assert_bidder_registration(registration)
            assert registration["status"] == "REQUESTED"
            assert registration["version"] == 1
        assert first["paddle_number"] == 101
        assert second["paddle_number"] == 102

        ledger = validate_success(api_client.get_bidder(first_bidder["id"], SETTLEMENT))
        assert ledger["deposit_held_cents"] == 100_000
        assert ledger["deposit_available_cents"] == 100_000
        assert_deposit_ledger_conserved(ledger)


class TestDepositAdmission:
    def test_a_hold_under_the_tier_floor_and_a_hold_over_the_funded_cash_differ(self):
        """The same rule reports two distinct ids: below the TIER_A minimum, and above what
        the bidder has actually funded.

        PRD 3.5: "The requested hold must reach the minimum for the bidder's tier: 100,000
        cents for `TIER_A`, 500,000 cents for `TIER_B`, and 1,500,000 cents for `TIER_C` — the
        less familiar the jurisdiction, the larger the stake required. A hold below the tier
        floor is refused with `ERR_DEPOSIT_BELOW_MINIMUM`. Separately, the bidder's
        `deposit_available_cents` must be at least the requested `deposit_hold_cents`; asking
        to lock cash that is not free is refused with `ERR_DEPOSIT_UNAVAILABLE`."

        Design: Corner/errors/deposit_admission_errors_distinguish_minimum_from_availability
        """
        reset_clock()
        yard = new_yard()
        auction = new_auction(yard)
        bidder = funded_bidder(200_000, reference="WIRE-US-1")
        bidder_headers = make_bidder_headers(bidder["id"])
        assert bidder["country_tier"] == "TIER_A"

        undersized = api_client.create_bidder_registration(
            create_bidder_registration_payload(bidder["id"], auction["id"], 50_000),
            bidder_headers,
        )
        validate_error(
            undersized, ApiErrorId.ERR_DEPOSIT_BELOW_MINIMUM, expected_status=422
        )

        unfunded = api_client.create_bidder_registration(
            create_bidder_registration_payload(bidder["id"], auction["id"], 1_000_000),
            bidder_headers,
        )
        validate_error(
            unfunded, ApiErrorId.ERR_DEPOSIT_UNAVAILABLE, expected_status=422
        )

        _, meta = validate_paginated(
            api_client.list_bidder_registrations(
                SETTLEMENT, params={"bidder_id": bidder["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_the_hold_that_clears_both_checks_locks_the_cash_and_grants_the_tier_leverage(self):
        """A 200,000-cent hold on 200,000 funded is admitted, takes paddle 101 and leaves
        nothing available.

        PRD 3.5: "A successful create puts the registration in `REQUESTED` at `version` 1,
        moves `deposit_hold_cents` from the bidder's `deposit_available_cents` to its
        `deposit_held_cents`".
        PRD 3.5: "`leverage_multiplier` is the deposit leverage granted by the tier: 10 for
        `TIER_A`, 5 for `TIER_B`, and 2 for `TIER_C`."

        Design: Corner/errors/deposit_admission_errors_distinguish_minimum_from_availability
        """
        reset_clock()
        yard = new_yard()
        auction = new_auction(yard)
        bidder = funded_bidder(200_000, reference="WIRE-US-1")
        bidder_headers = make_bidder_headers(bidder["id"])

        registration = validate_success(
            api_client.create_bidder_registration(
                create_bidder_registration_payload(bidder["id"], auction["id"], 200_000),
                bidder_headers,
            ),
            expected_status=201,
        )
        assert registration["status"] == "REQUESTED"
        assert registration["paddle_number"] == 101

        approved = validate_success(
            api_client.decide_credit(
                registration["id"], credit_decision_payload("APPROVE"), SETTLEMENT
            )
        )
        assert approved["leverage_multiplier"] == 10

        ledger = validate_success(api_client.get_bidder(bidder["id"], SETTLEMENT))
        assert ledger["deposit_held_cents"] == 200_000
        assert ledger["deposit_available_cents"] == 0
        assert ledger["deposit_total_cents"] == 200_000
        assert_deposit_ledger_conserved(ledger)


class TestSanctionsOutrankMoney:
    def test_an_embargoed_buyer_reports_the_embargo_and_not_the_undersized_deposit(self):
        """The Iranian paddle's hold is 1,400,000 short of its tier floor, yet the sanctions
        screen answers first with a 403.

        PRD 2.10: "Bidders whose `country_code` is `IR`, `KP`, `SY` or `RU` are embargoed.
        Registration creation, the credit decision on a registration, and export packet
        creation all screen for this and refuse with `ERR_COUNTRY_EMBARGOED`. Sanctions
        screening outranks every money rule in the ladder of §2.8."
        PRD 3.5: "Because the sanctions screen and the strike check sit far higher in the
        ladder, an embargoed bidder with an undersized deposit reports the embargo and never
        reaches either fiscal check."
        PRD 3.5: "Every other country falls into `TIER_C`."

        Design: Difficulty/priority_pair_validation_conflict/embargoed_country_with_undersized_deposit_reports_embargo
        """
        reset_clock()
        yard = new_yard()
        auction = new_auction(yard)
        bidder = funded_bidder(100_000, reference="WIRE-IR-1", **IRANIAN_BUYER)
        assert bidder["country_tier"] == "TIER_C"

        response = api_client.create_bidder_registration(
            create_bidder_registration_payload(bidder["id"], auction["id"], 100_000),
            make_bidder_headers(bidder["id"]),
        )

        validate_error(response, ApiErrorId.ERR_COUNTRY_EMBARGOED, expected_status=403)
        assert response.json()["data"]["error_id"] != "ERR_DEPOSIT_BELOW_MINIMUM"

    def test_the_refused_registration_locks_no_cash_and_leaves_no_row(self):
        """The embargo refusal is inert: the ledger is untouched and no paddle exists.

        PRD 3.5: "Recording a deposit raises both `deposit_total_cents` and
        `deposit_available_cents` by `amount_cents`, leaving `deposit_held_cents` and
        `deposit_forfeited_cents` untouched, and increments the bidder's `version` by 1."
        PRD 2.10: "Sanctions screening outranks every money rule in the ladder of §2.8."

        Design: Difficulty/priority_pair_validation_conflict/embargoed_country_with_undersized_deposit_reports_embargo
        """
        reset_clock()
        yard = new_yard()
        auction = new_auction(yard)
        bidder = funded_bidder(100_000, reference="WIRE-IR-1", **IRANIAN_BUYER)

        validate_error(
            api_client.create_bidder_registration(
                create_bidder_registration_payload(bidder["id"], auction["id"], 100_000),
                make_bidder_headers(bidder["id"]),
            ),
            ApiErrorId.ERR_COUNTRY_EMBARGOED,
            expected_status=403,
        )

        ledger = validate_success(api_client.get_bidder(bidder["id"], SETTLEMENT))
        assert ledger["deposit_total_cents"] == 100_000
        assert ledger["deposit_held_cents"] == 0
        assert ledger["deposit_available_cents"] == 100_000
        assert_deposit_ledger_conserved(ledger)

        rows, meta = validate_paginated(
            api_client.list_bidder_registrations(
                SETTLEMENT, params={"bidder_id": bidder["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestDepositConservation:
    def test_a_cancel_and_a_decline_each_hand_the_locked_cash_straight_back(self):
        """One 1,500,000-cent deposit is locked, released by a cancellation, locked again and
        released by a declined credit decision, with the total never moving.

        PRD 3.5: "Cancellation moves the registration to `CANCELLED`, which is terminal, and
        performs the compensating deposit move: `deposit_held_cents` falls and
        `deposit_available_cents` rises by `deposit_hold_cents`, with `deposit_total_cents`
        untouched."
        PRD 3.5: "Declining instead requires a `decline_reason` in the request, moves the
        registration `REQUESTED → DECLINED`, and releases the hold — `deposit_held_cents`
        falls and `deposit_available_cents` rises by `deposit_hold_cents`, with
        `deposit_total_cents` unchanged."
        PRD 2.10: "Bidders whose `country_code` is `IR`, `KP`, `SY` or `RU` are embargoed."

        Design: Difficulty/compensating_invariant/deposit_conservation_across_hold_cancel_and_decline
        """
        reset_clock()
        yard = new_yard()
        first_auction = new_auction(yard, **_timed_online_window(5))
        second_auction = new_auction(yard, **_timed_online_window(6))
        bidder = funded_bidder(1_500_000, reference="WIRE-US-1")
        bidder_headers = make_bidder_headers(bidder["id"])

        def ledger():
            snapshot = validate_success(api_client.get_bidder(bidder["id"], SETTLEMENT))
            assert_deposit_ledger_conserved(snapshot)
            assert snapshot["deposit_total_cents"] == 1_500_000
            assert snapshot["deposit_forfeited_cents"] == 0
            return snapshot

        first = validate_success(
            api_client.create_bidder_registration(
                create_bidder_registration_payload(
                    bidder["id"], first_auction["id"], 1_500_000
                ),
                bidder_headers,
            ),
            expected_status=201,
        )
        validate_success(
            api_client.decide_credit(
                first["id"], credit_decision_payload("APPROVE"), SETTLEMENT
            )
        )
        after_hold = ledger()
        assert after_hold["deposit_held_cents"] == 1_500_000
        assert after_hold["deposit_available_cents"] == 0

        cancelled = validate_success(
            api_client.cancel_bidder_registration(first["id"], bidder_headers)
        )
        assert cancelled["status"] == "CANCELLED"
        after_cancel = ledger()
        assert after_cancel["deposit_held_cents"] == 0
        assert after_cancel["deposit_available_cents"] == 1_500_000

        second = validate_success(
            api_client.create_bidder_registration(
                create_bidder_registration_payload(
                    bidder["id"], second_auction["id"], 1_500_000
                ),
                bidder_headers,
            ),
            expected_status=201,
        )
        after_second_hold = ledger()
        assert after_second_hold["deposit_held_cents"] == 1_500_000
        assert after_second_hold["deposit_available_cents"] == 0

        declined = validate_success(
            api_client.decide_credit(
                second["id"],
                credit_decision_payload(
                    "DECLINE", decline_reason="insufficient trade references"
                ),
                SETTLEMENT,
            )
        )
        assert declined["status"] == "DECLINED"
        after_decline = ledger()
        assert after_decline["deposit_held_cents"] == 0
        assert after_decline["deposit_available_cents"] == 1_500_000

    def test_the_final_smaller_hold_leaves_the_remainder_free_and_caps_the_paddle(self):
        """After the released rounds, a 1,000,000-cent hold locks only part of the same cash
        and the approved paddle is capped at ten times what it locked.

        PRD 3.5: "Approval also stamps `bid_cap_cents` from the **registration forecast**
        view of the paddle's headroom. Start from a base headroom equal to
        `deposit_hold_cents` multiplied by `leverage_multiplier`."
        PRD 2.10: "The conservation identity of §2.10 continues to hold."

        Design: Difficulty/compensating_invariant/deposit_conservation_across_hold_cancel_and_decline
        """
        reset_clock()
        yard = new_yard()
        first_auction = new_auction(yard, **_timed_online_window(5))
        third_auction = new_auction(yard, **_timed_online_window(7))
        bidder = funded_bidder(1_500_000, reference="WIRE-US-1")
        bidder_headers = make_bidder_headers(bidder["id"])

        first = validate_success(
            api_client.create_bidder_registration(
                create_bidder_registration_payload(
                    bidder["id"], first_auction["id"], 1_500_000
                ),
                bidder_headers,
            ),
            expected_status=201,
        )
        validate_success(api_client.cancel_bidder_registration(first["id"], bidder_headers))

        third = validate_success(
            api_client.create_bidder_registration(
                create_bidder_registration_payload(
                    bidder["id"], third_auction["id"], 1_000_000
                ),
                bidder_headers,
            ),
            expected_status=201,
        )
        assert third["paddle_number"] == 101
        approved = validate_success(
            api_client.decide_credit(
                third["id"], credit_decision_payload("APPROVE"), SETTLEMENT
            )
        )

        assert approved["status"] == "APPROVED"
        assert approved["bid_cap_cents"] == 10_000_000

        ledger = validate_success(api_client.get_bidder(bidder["id"], SETTLEMENT))
        assert ledger["deposit_total_cents"] == 1_500_000
        assert ledger["deposit_held_cents"] == 1_000_000
        assert ledger["deposit_available_cents"] == 500_000
        assert ledger["deposit_forfeited_cents"] == 0
        assert_deposit_ledger_conserved(ledger)


class TestBiddingNeedsApproval:
    def test_a_requested_paddle_cannot_bid_even_though_its_deposit_is_already_locked(self):
        """The ring refuses the bid on the registration's state, not on money: the cash is
        held and the cap is still zero.

        PRD 3.6: "The registration must be `APPROVED` — a `REQUESTED`, `DECLINED`,
        `SUSPENDED` or `CANCELLED` registration cannot bid — failing which the refusal is
        `ERR_REGISTRATION_NOT_APPROVED`."
        PRD 3.5: "`approved_credit_limit_cents` starts at 0, `financing_approved` at false,
        `bid_cap_cents` at 0, `deposit_applied_total_cents` at 0, and `payment_terms_code`,
        `leverage_multiplier`, `credit_approved_by_user_id` and `decline_reason` all at null."

        Design: Difficulty/cross_entity_state_dependency/bid_requires_approved_registration
        """
        stage = open_auction_with_catalogue(
            lot_overrides={
                "serial_number": "CAT-D8T-0001",
                "reserve_price_cents": 10_000_000,
            },
            approve_credit=False,
            open_clock="2026-08-10T16:00:00Z",
        )
        registration = stage["registration"]
        assert registration["status"] == "REQUESTED"
        assert registration["bid_cap_cents"] == 0
        assert registration["leverage_multiplier"] is None

        response = place_bid(
            registration, stage["lot"], 12_000_000, stage["bidder"]
        )

        validate_error(
            response, ApiErrorId.ERR_REGISTRATION_NOT_APPROVED, expected_status=409
        )

        ledger = validate_success(api_client.get_bidder(stage["bidder"]["id"], SETTLEMENT))
        assert ledger["deposit_held_cents"] == 1_500_000
        _, meta = validate_paginated(
            api_client.list_bids(OPERATOR, params={"lot_id": stage["lot"]["id"]})
        )
        assert meta["total_count"] == 0

    def test_the_credit_decision_is_what_opens_the_cap_and_admits_the_identical_bid(self):
        """Approval stamps the terms, the leverage and the 15,000,000-cent cap, after which the
        very same bid is accepted.

        PRD 3.5: "`payment_terms_code` follows from that outcome and the tier: an approved
        financing arrangement earns `NET_30`; failing that, a `TIER_A` bidder earns `NET_7`;
        every other bidder is `PREPAY`."
        PRD 3.5: "The forecast cap is then the base headroom plus `approved_credit_limit_cents`
        less that exposure, floored at zero."
        PRD 3.6: "A bid is created in `ACTIVE` with `placed_at` taken from the logical clock".

        Design: Difficulty/cross_entity_state_dependency/bid_requires_approved_registration
        """
        stage = open_auction_with_catalogue(
            lot_overrides={
                "serial_number": "CAT-D8T-0001",
                "reserve_price_cents": 10_000_000,
            },
            approve_credit=False,
            open_clock="2026-08-10T16:00:00Z",
        )
        registration = stage["registration"]
        validate_error(
            place_bid(registration, stage["lot"], 12_000_000, stage["bidder"]),
            ApiErrorId.ERR_REGISTRATION_NOT_APPROVED,
            expected_status=409,
        )

        approved = validate_success(
            api_client.decide_credit(
                registration["id"], credit_decision_payload("APPROVE"), SETTLEMENT
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["payment_terms_code"] == "NET_7"
        assert approved["leverage_multiplier"] == 10
        assert approved["bid_cap_cents"] == 15_000_000
        assert approved["financing_approved"] is False

        bid = validate_success(
            api_client.create_bid(
                create_bid_payload(registration["id"], stage["lot"]["id"], 12_000_000),
                stage["bidder_headers"],
            ),
            expected_status=201,
        )
        assert bid["status"] == "ACTIVE"
        assert bid["amount_cents"] == 12_000_000

        _, meta = validate_paginated(
            api_client.list_bids(OPERATOR, params={"lot_id": stage["lot"]["id"]})
        )
        assert meta["total_count"] == 1
        assert (
            validate_success(api_client.get_lot(stage["lot"]["id"], OPERATOR))[
                "high_bid_cents"
            ]
            == 12_000_000
        )
