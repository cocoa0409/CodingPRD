"""The seller's negotiation loop over a sale that missed its reserve."""
from test_helpers import (
    ApiErrorId,
    api_client,
    counter_response_payload,
    counteroffer_payload,
    provisional_sale_below_reserve,
    reject_sale_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import OPERATOR, SETTLEMENT


def _negotiation_stage(reserve_price_cents: int):
    """A hammer under the reserve, so the sale sits with the seller."""
    stage = provisional_sale_below_reserve(
        reserve_price_cents=reserve_price_cents,
        bid_amount_cents=12_000_000,
        lot_overrides={"serial_number": "CAT-D8T-0001"},
    )
    assert stage["sale"]["status"] == "PROVISIONAL"
    assert stage["sale"]["reserve_met"] is False
    return stage


def _counter(stage, price_cents):
    """Counter at the seller's current view of the sale version. Returns the raw response."""
    current = validate_success(api_client.get_sale(stage["sale"]["id"], OPERATOR))
    return api_client.counteroffer_sale(
        stage["sale"]["id"],
        counteroffer_payload(price_cents, current["version"]),
        stage["consignor_headers"],
    )


def _decline(stage):
    return validate_success(
        api_client.respond_to_counteroffer(
            stage["sale"]["id"], counter_response_payload("DECLINE"), stage["bidder_headers"]
        )
    )


class TestCounterofferLoop:
    def test_each_decline_below_the_lap_limit_hands_the_sale_back_to_the_seller(self):
        """Two concessions are refused by the buyer and each time the sale returns to the
        seller with its lap counter one higher.

        PRD 3.7: "A valid counteroffer moves the sale `PROVISIONAL → CONSIGNOR_COUNTERED`,
        increments `counter_round` by 1, records `counter_price_cents`, and increments the
        sale's `version` by 1."
        PRD 3.7: "While `counter_round` is still below 3, a decline moves the sale
        `CONSIGNOR_COUNTERED → PROVISIONAL`, returning it to the seller so another concession
        may be offered; the loop `PROVISIONAL → CONSIGNOR_COUNTERED → PROVISIONAL` may be
        walked for at most three laps."

        Design: Difficulty/non_linear_state_machine/sale_counteroffer_cycle_returns_to_provisional_then_no_sale_at_lap_limit
        """
        stage = _negotiation_stage(20_000_000)

        first = validate_success(_counter(stage, 18_000_000))
        assert first["status"] == "CONSIGNOR_COUNTERED"
        assert first["counter_round"] == 1
        assert first["counter_price_cents"] == 18_000_000

        after_first_decline = _decline(stage)
        assert after_first_decline["status"] == "PROVISIONAL"
        assert after_first_decline["counter_round"] == 1

        second = validate_success(_counter(stage, 15_000_000))
        assert second["status"] == "CONSIGNOR_COUNTERED"
        assert second["counter_round"] == 2
        assert second["counter_price_cents"] == 15_000_000

        after_second_decline = _decline(stage)
        assert after_second_decline["status"] == "PROVISIONAL"
        assert after_second_decline["counter_round"] == 2
        assert after_second_decline["reserve_met"] is False
        assert (
            validate_success(api_client.get_lot(stage["lot"]["id"], OPERATOR))[
                "lifecycle_status"
            ]
            == "HAMMERED"
        )

    def test_the_third_decline_ends_the_negotiation_instead_of_reopening_it(self):
        """The same endpoint with the same payload lands on NO_SALE once the counter has been
        offered three times, and the machine goes back on the shelf uninvoiced.

        PRD 3.7: "When `counter_round` has reached 3, the same decline instead moves the sale
        `CONSIGNOR_COUNTERED → NO_SALE`, moves the lot `HAMMERED → UNSOLD`, flips the winning
        bid `WINNING → LOSING`, and recomputes the consignment's and the auction's
        `unsold_lot_count`."
        PRD 3.7: "Beyond that, `counter_round` must still be below 3 — a fourth counteroffer is
        refused with `ERR_MAX_COUNTER_ROUNDS_EXCEEDED` — and the proposed `counter_price_cents`
        must satisfy all three of the following inequalities: it must be at least the sale's
        current `hammer_price_cents`, it must be no greater than the lot's
        `reserve_price_cents`, and when `counter_round` is already above zero it must be no
        greater than the previous `counter_price_cents`."

        Design: Difficulty/non_linear_state_machine/sale_counteroffer_cycle_returns_to_provisional_then_no_sale_at_lap_limit
        """
        stage = _negotiation_stage(20_000_000)
        for price in (18_000_000, 15_000_000):
            validate_success(_counter(stage, price))
            _decline(stage)

        third = validate_success(_counter(stage, 13_000_000))
        assert third["counter_round"] == 3

        final = _decline(stage)

        assert final["status"] == "NO_SALE"
        assert final["counter_round"] == 3
        assert final["counter_price_cents"] == 13_000_000
        assert final["reserve_met"] is False
        assert (
            validate_success(api_client.get_lot(stage["lot"]["id"], OPERATOR))[
                "lifecycle_status"
            ]
            == "UNSOLD"
        )
        assert (
            validate_success(
                api_client.get_consignment(stage["consignment"]["id"], OPERATOR)
            )["unsold_lot_count"]
            == 1
        )
        _, meta = validate_paginated(
            api_client.list_invoices(SETTLEMENT, params={"sale_id": stage["sale"]["id"]})
        )
        assert meta["total_count"] == 0
        assert (
            validate_success(api_client.get_bidder(stage["bidder"]["id"], SETTLEMENT))[
                "open_exposure_cents"
            ]
            == 0
        )


class TestConcessionsOnlyMoveDown:
    def test_a_later_counteroffer_may_not_exceed_the_one_the_buyer_already_declined(self):
        """Walking the price back up is refused and leaves the lap counter alone, while a lower
        concession is accepted.

        PRD 3.7: "Concessions may only move down; a second counteroffer higher than the first
        is refused with `ERR_COUNTER_PRICE_NOT_MONOTONIC`."
        PRD 3.7: "This is exactly why the version guard exists: evaluating the monotonicity
        comparison against a round the seller never observed would let a client walk the price
        back up."

        Design: Corner/errors/a_second_counteroffer_above_the_first_is_refused
        """
        stage = _negotiation_stage(13_000_000)
        validate_success(_counter(stage, 12_500_000))
        after_decline = _decline(stage)
        assert after_decline["status"] == "PROVISIONAL"
        assert after_decline["counter_round"] == 1
        assert after_decline["counter_price_cents"] == 12_500_000

        response = _counter(stage, 12_800_000)

        validate_error(
            response, ApiErrorId.ERR_COUNTER_PRICE_NOT_MONOTONIC, expected_status=422
        )
        held = validate_success(api_client.get_sale(stage["sale"]["id"], OPERATOR))
        assert held["counter_round"] == 1
        assert held["counter_price_cents"] == 12_500_000
        assert held["status"] == "PROVISIONAL"

        lower = validate_success(_counter(stage, 12_300_000))
        assert lower["status"] == "CONSIGNOR_COUNTERED"
        assert lower["counter_round"] == 2
        assert lower["counter_price_cents"] == 12_300_000


class TestCounterofferVersionGuard:
    def test_replaying_a_counteroffer_with_the_consumed_version_is_a_precondition_failure(self):
        """The stale version answers before the state guard would, and the replay writes
        nothing.

        PRD 3.7: "A counteroffer is available only while the sale is `PROVISIONAL` with
        `reserve_met` false, and it is the one negotiation step guarded by optimistic
        concurrency: the request must carry `expected_sale_version` matching the sale's current
        `version`, or it is refused with `ERR_STALE_SALE_VERSION`."
        PRD 2.8: "`expected_sale_version` or `expected_invoice_version` equals the parent's
        current `version` — otherwise `ERR_STALE_SALE_VERSION` or `ERR_STALE_INVOICE_VERSION`
        (412). Checked before any state precondition, so a stale version on a resource that is
        also in the wrong state still returns 412."

        Design: Corner/cross-cutting complexity layers/stale_expected_sale_version_on_a_counteroffer_returns_412
        """
        stage = _negotiation_stage(13_000_000)
        observed_version = stage["sale"]["version"]

        countered = validate_success(
            api_client.counteroffer_sale(
                stage["sale"]["id"],
                counteroffer_payload(12_600_000, observed_version),
                stage["consignor_headers"],
            )
        )
        assert countered["status"] == "CONSIGNOR_COUNTERED"
        assert countered["counter_round"] == 1
        assert countered["version"] == observed_version + 1

        replay = api_client.counteroffer_sale(
            stage["sale"]["id"],
            counteroffer_payload(12_600_000, observed_version),
            stage["consignor_headers"],
        )

        validate_error(replay, ApiErrorId.ERR_STALE_SALE_VERSION, expected_status=412)
        stored = validate_success(api_client.get_sale(stage["sale"]["id"], OPERATOR))
        assert stored["counter_round"] == 1
        assert stored["counter_price_cents"] == 12_600_000
        assert stored["version"] == observed_version + 1


class TestReconciliationWaitsForTheNegotiation:
    def test_the_books_close_only_once_the_provisional_sale_is_resolved(self):
        """An unresolved negotiation refuses reconciliation; rejecting the sale releases the
        machine and lets the identical call through.

        PRD 3.9: "A `SettlementOfficer` moves the auction `CLOSED → RECONCILED`, which is
        terminal, and this is permitted only when every one of the auction's `CONFIRMED` sales
        has a `POSTED` consignor settlement and no sale of the auction is still `PROVISIONAL`
        or `CONSIGNOR_COUNTERED`. An unresolved negotiation or an unsettled confirmed sale
        refuses the request with `ERR_SETTLEMENT_INCOMPLETE`. Reconciliation recomputes
        `gross_hammer_cents` and increments the auction's `version` by 1."
        PRD 3.7: "It moves the sale `PROVISIONAL → NO_SALE`, which is terminal, moves the lot
        `HAMMERED → UNSOLD`, flips the winning bid `WINNING → LOSING`, and recomputes both the
        consignment's `unsold_lot_count` and the auction's `unsold_lot_count`."

        Design: Corner/endpoints/reconcile_is_refused_until_the_unmet_reserve_sale_is_resolved
        """
        stage = _negotiation_stage(13_000_000)
        auction_id = stage["auction"]["id"]
        winning_bid_id = stage["sale"]["winning_bid_id"]
        validate_success(api_client.close_auction(auction_id, OPERATOR))
        _, meta = validate_paginated(
            api_client.list_invoices(SETTLEMENT, params={"sale_id": stage["sale"]["id"]})
        )
        assert meta["total_count"] == 0

        refused = api_client.reconcile_auction(auction_id, SETTLEMENT)
        validate_error(refused, ApiErrorId.ERR_SETTLEMENT_INCOMPLETE, expected_status=409)
        assert (
            validate_success(api_client.get_auction(auction_id, OPERATOR))["status"]
            == "CLOSED"
        )

        rejected = validate_success(
            api_client.reject_sale(
                stage["sale"]["id"], reject_sale_payload(), stage["consignor_headers"]
            )
        )
        assert rejected["status"] == "NO_SALE"
        assert (
            validate_success(api_client.get_lot(stage["lot"]["id"], OPERATOR))[
                "lifecycle_status"
            ]
            == "UNSOLD"
        )
        assert (
            validate_success(api_client.get_bid(winning_bid_id, OPERATOR))["status"]
            == "LOSING"
        )
        assert (
            validate_success(
                api_client.get_consignment(stage["consignment"]["id"], OPERATOR)
            )["unsold_lot_count"]
            == 1
        )

        reconciled = validate_success(api_client.reconcile_auction(auction_id, SETTLEMENT))

        assert reconciled["status"] == "RECONCILED"
        assert reconciled["unsold_lot_count"] == 1
        assert reconciled["gross_hammer_cents"] == 0
