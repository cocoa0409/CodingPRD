"""The seller's waterfall, fee waivers, default and the abandonment cascade."""
from test_helpers import (
    ApiErrorId,
    SETTLEMENT_USER_ID,
    abandon_invoice_payload,
    api_client,
    approved_registration,
    completed_refurbishment_order,
    confirmed_invoice,
    create_bidder_registration_payload,
    create_consignor_settlement_payload,
    clear_lot_title,
    fee_waiver_payload,
    file_condition_report,
    funded_bidder,
    intake_decision_payload,
    lot_assignment_payload,
    make_consignor_headers,
    new_auction,
    new_consignment,
    new_consignor,
    new_lot,
    new_yard,
    place_bid,
    publish_condition_report,
    reset_clock,
    sequential_sales_batch,
    set_clock,
    settled_then_defaulted_invoice,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import OPERATOR, SECOND_SETTLEMENT, SETTLEMENT

DEFAULT_CLOCK = "2026-08-18T16:00:00Z"

HEAVY_LOT = {
    "serial_number": "CAT-D8T-0001",
    "weight_kg": 36_000,
    "reserve_price_cents": 10_000_000,
}
SECOND_LOT = {
    "make": "Volvo",
    "model": "EC220",
    "model_year": 2020,
    "serial_number": "VOL-EC220-0002",
    "hour_meter_reading": 3_400,
    "weight_kg": 9_000,
    "reserve_price_cents": 1_000_000,
}


def _defaulted_after_settlement():
    """A settled sale whose buyer never paid and whose invoice is now IN_DEFAULT."""
    stage = settled_then_defaulted_invoice(
        lot_overrides=HEAVY_LOT,
        consignment_overrides={"advance_paid_cents": 2_000_000},
        default_clock=DEFAULT_CLOCK,
    )
    assert stage["invoice"]["payment_status"] == "IN_DEFAULT"
    assert stage["invoice"]["release_status"] == "HELD"
    return stage


def _refurbished_sale():
    """A 12,000,000-cent hammer on a batch carrying a cash advance and overspent
    refurbishment, which is what makes all four settlement buckets non-trivial."""
    reset_clock()
    yard = new_yard()
    consignor = new_consignor()
    consignor_headers = make_consignor_headers(consignor["id"])
    consignment = new_consignment(
        consignor, advance_paid_cents=2_000_000, refurb_authorization_cap_cents=500_000
    )
    lot = new_lot(consignment, consignor, **HEAVY_LOT)
    validate_success(api_client.submit_consignment(consignment["id"], consignor_headers))
    validate_success(
        api_client.decide_consignment_intake(
            consignment["id"], intake_decision_payload("ACCEPT"), OPERATOR
        )
    )
    clear_lot_title(lot)
    report = file_condition_report(lot)
    order = completed_refurbishment_order(
        lot, estimated_cost_cents=800_000, actual_cost_cents=800_000
    )
    assert order["status"] == "COMPLETED"
    assert order["actual_cost_cents"] == 800_000
    publish_condition_report(report)

    auction = new_auction(yard)
    validate_success(
        api_client.assign_lot_to_auction(
            auction["id"], lot_assignment_payload(lot["id"]), OPERATOR
        ),
        expected_status=201,
    )
    bidder = funded_bidder(1_500_000)
    registration = approved_registration(bidder, auction, 1_500_000)
    validate_success(api_client.open_auction(auction["id"], OPERATOR))
    set_clock("2026-08-10T16:00:00Z")
    validate_success(place_bid(registration, lot, 12_000_000, bidder), expected_status=201)
    sale = validate_success(api_client.hammer_lot(lot["id"], OPERATOR), expected_status=201)
    assert sale["status"] == "CONFIRMED"
    return {
        "consignor": consignor,
        "consignment": consignment,
        "lot": lot,
        "sale": sale,
    }


class TestAbandonmentCascade:
    def test_the_walking_buyer_writes_off_the_invoice_and_earns_a_strike(self):
        """The abandonment restamps storage as of the current instant, books the compensating
        deficiency claim, defaults the sale and marks the buyer once.

        PRD 3.9: "At the first depth, the invoice's `payment_status` moves `IN_DEFAULT →
        WRITTEN_OFF` and its `release_status` moves to `ABANDONED`, both terminal.
        `storage_fee_cents` is restamped under the final-variant storage rules as of the current
        logical clock, and `deficiency_claim_cents` is computed."
        PRD 3.9: "add `hammer_price_cents`, the storage accrued as of abandonment under the
        final-variant rules, and a re-offer administration fee of 75,000 cents; then subtract the
        forfeited deposit hold and the cash the buyer had already tendered, measured as
        `amount_paid_cents` **before** the payments of this invoice are reversed; and take the
        larger of the result and zero."
        PRD 3.9: "At the second depth, the sale moves to `DEFAULTED` — from `SETTLED` when a
        settlement had been posted, and from `CONFIRMED` when none ever was — and the bidder's
        `default_strike_count` increments by 1, which in turn suspends every `APPROVED`
        registration of that bidder once the count reaches 2. The auction's `gross_hammer_cents`
        is recomputed, since a defaulted sale no longer contributes."

        Design: Difficulty/transitive_cascade/abandonment_cascades_invoice_sale_settlement_lot_consignment
        """
        stage = _defaulted_after_settlement()
        invoice = stage["invoice"]

        abandoned = validate_success(
            api_client.abandon_invoice(invoice["id"], SETTLEMENT, abandon_invoice_payload())
        )

        assert abandoned["payment_status"] == "WRITTEN_OFF"
        assert abandoned["release_status"] == "ABANDONED"
        assert abandoned["chargeable_storage_days"] == 3
        assert abandoned["storage_fee_cents"] == 36_000
        assert abandoned["deficiency_claim_cents"] == 10_611_000

        assert (
            validate_success(api_client.get_sale(stage["sale"]["id"], OPERATOR))["status"]
            == "DEFAULTED"
        )
        bidder = validate_success(api_client.get_bidder(stage["bidder"]["id"], SETTLEMENT))
        assert bidder["default_strike_count"] == 1
        assert bidder["open_exposure_cents"] == 0
        assert bidder["lifetime_purchase_cents"] == 0
        assert (
            validate_success(
                api_client.get_bidder_registration(stage["registration"]["id"], SETTLEMENT)
            )["status"]
            == "APPROVED"
        )
        assert (
            validate_success(api_client.get_auction(stage["auction"]["id"], OPERATOR))[
                "gross_hammer_cents"
            ]
            == 0
        )

    def test_the_same_call_reverses_the_sellers_settlement_and_requeues_the_machine(self):
        """Depths three and four undo the seller's side: the posted waterfall is restamped as a
        25,000-cent no-sale fee, the advance goes back on the batch, and the machine returns to
        the re-offer queue with the deposit forfeited.

        PRD 3.9: "At the third depth, the sale's `POSTED` consignor settlement is reversed.
        Reversal restamps the settlement's figures rather than deleting the row:
        `gross_proceeds_cents`, `commission_cents`, `refurb_recharge_cents` and
        `advance_recovery_cents` all become 0, `no_sale_fee_cents` becomes 25,000 cents, and
        `net_proceeds_cents` becomes negative 25,000 cents — the seller now owes the house the
        no-sale fee. The settlement's `status` moves `POSTED → REVERSED`, the consignment's
        `advance_outstanding_cents` is restored to what it was before the recovery, and the
        consignor's `lifetime_net_proceeds_cents` is recomputed."
        PRD 3.9: "At the fourth depth, and only when a settlement was actually reversed, the lot
        moves `SETTLED → REOFFER_QUEUED` and the consignment's `reoffer_lot_count` is
        recomputed".
        PRD 3.9: "the registration's deposit hold is forfeited in full — the bidder's
        `deposit_held_cents` falls and `deposit_forfeited_cents` rises by `deposit_hold_cents`,
        with `deposit_total_cents` unchanged."

        Design: Difficulty/transitive_cascade/abandonment_cascades_invoice_sale_settlement_lot_consignment
        """
        stage = _defaulted_after_settlement()
        settlement = validate_success(
            api_client.get_consignor_settlement(stage["settlement"]["id"], SETTLEMENT)
        )
        assert settlement["status"] == "POSTED"
        assert settlement["commission_cents"] == 1_380_000
        assert settlement["advance_recovery_cents"] == 2_000_000
        assert settlement["net_proceeds_cents"] == 8_620_000
        assert stage["lot"]["lifecycle_status"] == "SETTLED"

        validate_success(
            api_client.abandon_invoice(
                stage["invoice"]["id"], SETTLEMENT, abandon_invoice_payload()
            )
        )

        reversed_settlement = validate_success(
            api_client.get_consignor_settlement(settlement["id"], SETTLEMENT)
        )
        assert reversed_settlement["status"] == "REVERSED"
        assert reversed_settlement["gross_proceeds_cents"] == 0
        assert reversed_settlement["commission_cents"] == 0
        assert reversed_settlement["refurb_recharge_cents"] == 0
        assert reversed_settlement["advance_recovery_cents"] == 0
        assert reversed_settlement["no_sale_fee_cents"] == 25_000
        assert reversed_settlement["net_proceeds_cents"] == -25_000

        consignment = validate_success(
            api_client.get_consignment(stage["consignment"]["id"], OPERATOR)
        )
        assert consignment["advance_outstanding_cents"] == 2_000_000
        assert consignment["reoffer_lot_count"] == 1
        assert (
            validate_success(api_client.get_lot(stage["lot"]["id"], OPERATOR))[
                "lifecycle_status"
            ]
            == "REOFFER_QUEUED"
        )
        bidder = validate_success(api_client.get_bidder(stage["bidder"]["id"], SETTLEMENT))
        assert bidder["deposit_forfeited_cents"] == 1_500_000
        assert bidder["deposit_held_cents"] == 0
        assert bidder["deposit_available_cents"] == 0
        assert bidder["deposit_total_cents"] == 1_500_000


class TestSecondStrikeSuspends:
    def test_the_second_walk_away_suspends_the_paddle_and_leaves_the_unsettled_lot_alone(self):
        """One abandonment is tolerated; the second closes the buyer out of the platform, and
        the machine whose settlement was never posted stays hammered rather than requeued.

        PRD 3.5: "When an abandonment pushes the owning bidder's `default_strike_count` to 2,
        every `APPROVED` registration of that bidder moves `APPROVED → SUSPENDED` and has its
        `bid_cap_cents` set to 0, with `version` incremented by 1 on each."
        PRD 3.9: "When no settlement had ever been posted, this fourth depth is not taken: the
        lot stays in `HAMMERED`, because there was nothing to reverse."
        PRD 2.8: "The bidder's `default_strike_count` is below the strike limit — otherwise
        `ERR_BIDDER_SUSPENDED` (403). Guards registration creation, the credit decision, and bid
        placement."

        Design: Corner/state_machines/second_abandonment_suspends_the_registration_and_spares_the_unsettled_lot
        """
        stage = sequential_sales_batch(
            [HEAVY_LOT, SECOND_LOT],
            [12_000_000, 2_000_000],
            ["2026-08-10T16:00:00Z", "2026-08-10T16:05:00Z"],
        )
        first_invoice, second_invoice = stage["invoices"]
        first_sale, second_sale = stage["sales"]
        validate_success(
            api_client.create_consignor_settlement(
                create_consignor_settlement_payload(first_sale["id"]), SETTLEMENT
            ),
            expected_status=201,
        )
        set_clock(DEFAULT_CLOCK)

        validate_success(api_client.default_invoice(first_invoice["id"], SETTLEMENT))
        first_abandon = validate_success(
            api_client.abandon_invoice(
                first_invoice["id"], SETTLEMENT, abandon_invoice_payload()
            )
        )
        assert first_abandon["payment_status"] == "WRITTEN_OFF"
        assert first_abandon["release_status"] == "ABANDONED"
        assert first_abandon["deficiency_claim_cents"] == 10_611_000
        assert (
            validate_success(api_client.get_bidder(stage["bidder"]["id"], SETTLEMENT))[
                "default_strike_count"
            ]
            == 1
        )
        assert (
            validate_success(
                api_client.get_bidder_registration(stage["registration"]["id"], SETTLEMENT)
            )["status"]
            == "APPROVED"
        )
        assert (
            validate_success(api_client.get_lot(stage["lots"][0]["id"], OPERATOR))[
                "lifecycle_status"
            ]
            == "REOFFER_QUEUED"
        )

        validate_success(api_client.default_invoice(second_invoice["id"], SETTLEMENT))
        second_abandon = validate_success(
            api_client.abandon_invoice(
                second_invoice["id"], SETTLEMENT, abandon_invoice_payload()
            )
        )

        assert second_abandon["payment_status"] == "WRITTEN_OFF"
        assert second_abandon["deficiency_claim_cents"] > 0
        assert (
            validate_success(api_client.get_sale(second_sale["id"], OPERATOR))["status"]
            == "DEFAULTED"
        )
        assert (
            validate_success(api_client.get_lot(stage["lots"][1]["id"], OPERATOR))[
                "lifecycle_status"
            ]
            == "HAMMERED"
        )
        assert (
            validate_success(api_client.get_bidder(stage["bidder"]["id"], SETTLEMENT))[
                "default_strike_count"
            ]
            == 2
        )
        suspended = validate_success(
            api_client.get_bidder_registration(stage["registration"]["id"], SETTLEMENT)
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["bid_cap_cents"] == 0

        next_auction = new_auction(
            stage["yard"],
            window_start="2026-08-25T14:00:00Z",
            window_end="2026-08-25T22:00:00Z",
        )
        validate_error(
            api_client.create_bidder_registration(
                create_bidder_registration_payload(
                    stage["bidder"]["id"], next_auction["id"], 1_500_000
                ),
                stage["bidder_headers"],
            ),
            ApiErrorId.ERR_BIDDER_SUSPENDED,
            expected_status=403,
        )


class TestConsignorWaterfall:
    def test_the_recharge_stops_at_the_batch_authorisation_before_the_advance_is_clawed_back(
        self,
    ):
        """The house eats the 300,000 cents of refurbishment it never authorised, and the
        2,000,000-cent advance is recovered only out of what the earlier buckets leave.

        PRD 3.9: "Under `RESERVE_STD`, take twelve percent of the portion of gross up to
        10,000,000 cents plus nine percent of everything above it, rounding each tier half up to
        whole cents before adding them, then use the larger of that sum and a floor of 100,000
        cents."
        PRD 3.9: "`refurb_recharge_cents` is the smaller of the actual spend and the remaining
        authorisation, and `house_absorbed_refurb_cents` is the difference the auctioneer eats:
        the actual spend less the recharge."
        PRD 3.9: "Compute what is left in the waterfall — gross less `commission_cents` less
        `refurb_recharge_cents` — and recover the smaller of the consignment's
        `advance_outstanding_cents` and the larger of zero and that remainder. The advance is
        therefore never recovered beyond what the sale can bear."
        PRD 3.9: "`net_proceeds_cents` is the residual: gross less `commission_cents`, less
        `refurb_recharge_cents`, less `advance_recovery_cents`, less `no_sale_fee_cents`."

        Design: Corner/calculations/consignor_waterfall_caps_the_refurb_recharge_then_recovers_the_advance
        """
        stage = _refurbished_sale()

        settlement = validate_success(
            api_client.create_consignor_settlement(
                create_consignor_settlement_payload(stage["sale"]["id"]), SETTLEMENT
            ),
            expected_status=201,
        )

        assert settlement["status"] == "POSTED"
        assert settlement["gross_proceeds_cents"] == 12_000_000
        assert settlement["commission_cents"] == 1_380_000
        assert settlement["refurb_recharge_cents"] == 500_000
        assert settlement["house_absorbed_refurb_cents"] == 300_000
        assert settlement["advance_recovery_cents"] == 2_000_000
        assert settlement["no_sale_fee_cents"] == 0
        assert settlement["net_proceeds_cents"] == 8_120_000

        assert (
            validate_success(api_client.get_sale(stage["sale"]["id"], OPERATOR))["status"]
            == "SETTLED"
        )
        assert (
            validate_success(api_client.get_lot(stage["lot"]["id"], OPERATOR))[
                "lifecycle_status"
            ]
            == "SETTLED"
        )
        assert (
            validate_success(
                api_client.get_consignment(stage["consignment"]["id"], OPERATOR)
            )["advance_outstanding_cents"]
            == 0
        )
        assert (
            validate_success(api_client.get_consignor(stage["consignor"]["id"], OPERATOR))[
                "lifetime_net_proceeds_cents"
            ]
            == 8_120_000
        )


class TestSettlementIsPostedOnce:
    def test_replaying_the_settlement_conflicts_instead_of_writing_a_second_waterfall(self):
        """The create is refused on the existing POSTED row, and the seller's figures are left
        exactly as the first posting stamped them.

        PRD 3.9: "It requires the sale to be `CONFIRMED` and no `POSTED` settlement to exist for
        it already — a replay is refused with `ERR_DUPLICATE_SETTLEMENT`. Posting creates the
        settlement in `POSTED`, moves the sale `CONFIRMED → SETTLED` and the lot `HAMMERED →
        SETTLED`, reduces the consignment's `advance_outstanding_cents` by the recovered advance,
        and recomputes the consignor's `lifetime_net_proceeds_cents`."
        PRD 2.8: "Duplicate-create guards, all 409: the lot has no condition report yet,
        otherwise `ERR_DUPLICATE_CONDITION_REPORT`; the sale has no `POSTED` settlement yet,
        otherwise `ERR_DUPLICATE_SETTLEMENT`; the bidder-and-auction pair has no registration in
        `REQUESTED`, `APPROVED` or `SUSPENDED`, otherwise `ERR_DUPLICATE_REGISTRATION`. Replaying
        a create that already produced a row is a conflict, not a second row."

        Design: Corner/errors/a_second_settlement_on_the_same_sale_is_a_duplicate
        """
        stage = confirmed_invoice(lot_overrides={"serial_number": "CAT-D8T-0001"})
        sale = stage["sale"]

        settlement = validate_success(
            api_client.create_consignor_settlement(
                create_consignor_settlement_payload(sale["id"]), SETTLEMENT
            ),
            expected_status=201,
        )
        assert settlement["status"] == "POSTED"
        assert settlement["gross_proceeds_cents"] == 12_000_000
        assert settlement["commission_cents"] == 1_380_000
        assert settlement["net_proceeds_cents"] == 10_620_000
        assert (
            validate_success(api_client.get_sale(sale["id"], OPERATOR))["status"] == "SETTLED"
        )
        assert (
            validate_success(api_client.get_lot(stage["lot"]["id"], OPERATOR))[
                "lifecycle_status"
            ]
            == "SETTLED"
        )

        replay = api_client.create_consignor_settlement(
            create_consignor_settlement_payload(sale["id"]), SETTLEMENT
        )

        validate_error(replay, ApiErrorId.ERR_DUPLICATE_SETTLEMENT, expected_status=409)
        _, meta = validate_paginated(
            api_client.list_sale_consignor_settlements(sale["id"], SETTLEMENT)
        )
        assert meta["total_count"] == 1
        unchanged = validate_success(
            api_client.get_consignor_settlement(settlement["id"], SETTLEMENT)
        )
        assert unchanged["status"] == "POSTED"
        assert unchanged["net_proceeds_cents"] == 10_620_000
        assert unchanged["version"] == settlement["version"]


class TestFeeWaiverCeiling:
    def test_waivers_accumulate_up_to_five_percent_and_the_credit_approver_may_grant_none(self):
        """The officer who approved the paddle's credit is refused outright, and the second
        officer's two waivers exactly exhaust the 658,750-cent allowance.

        PRD 3.8: "Cumulative waivers on one invoice may not exceed five percent of its
        `subtotal_cents`: the sum of the existing `credit_memo_cents` and the requested
        `waiver_cents` must be no greater than five percent of `subtotal_cents` rounded half up
        to whole cents, and a request that would breach the ceiling is refused with
        `ERR_WAIVER_LIMIT_EXCEEDED`."
        PRD 3.8: "The waiver raises `credit_memo_cents` by `waiver_cents` and recomputes
        `total_due_cents` and `outstanding_cents`, incrementing the invoice's `version` by 1."
        PRD 2.10: "The settlement officer who approved a bidder's credit — recorded as
        `credit_approved_by_user_id` — may not be the acting user who later waives fees on that
        bidder's invoice. Either violation is refused with `ERR_SEGREGATION_OF_DUTIES`, and the
        refusal stands even though the acting role is correct for the endpoint."

        Design: Corner/validations/cumulative_fee_waivers_stop_at_five_percent_of_the_subtotal
        """
        stage = confirmed_invoice(lot_overrides={"serial_number": "CAT-D8T-0001"})
        invoice = stage["invoice"]
        assert stage["registration"]["credit_approved_by_user_id"] == SETTLEMENT_USER_ID
        assert invoice["subtotal_cents"] == 13_175_000
        assert invoice["credit_memo_cents"] == 0

        validate_error(
            api_client.waive_invoice_fee(
                invoice["id"], fee_waiver_payload(400_000), SETTLEMENT
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            expected_status=403,
        )
        assert (
            validate_success(api_client.get_invoice(invoice["id"], SETTLEMENT))[
                "credit_memo_cents"
            ]
            == 0
        )

        first = validate_success(
            api_client.waive_invoice_fee(
                invoice["id"], fee_waiver_payload(400_000), SECOND_SETTLEMENT
            )
        )
        assert first["credit_memo_cents"] == 400_000
        assert first["total_due_cents"] == 12_098_438

        second = validate_success(
            api_client.waive_invoice_fee(
                invoice["id"], fee_waiver_payload(258_750), SECOND_SETTLEMENT
            )
        )
        assert second["credit_memo_cents"] == 658_750
        assert second["total_due_cents"] == 11_839_688

        validate_error(
            api_client.waive_invoice_fee(
                invoice["id"], fee_waiver_payload(1), SECOND_SETTLEMENT
            ),
            ApiErrorId.ERR_WAIVER_LIMIT_EXCEEDED,
            expected_status=422,
        )
        held = validate_success(api_client.get_invoice(invoice["id"], SETTLEMENT))
        assert held["credit_memo_cents"] == 658_750
        assert held["total_due_cents"] == 11_839_688
        assert held["subtotal_cents"] == 13_175_000


class TestDefaultIsStrictlyPastDue:
    def test_the_invoice_is_still_on_time_at_its_due_instant_and_late_one_second_later(self):
        """Exactly at `payment_due_at` the default is refused, the very next second it succeeds,
        and neither call disturbs the custody axis.

        PRD 3.8: "**Default.** Once the logical clock is strictly past `payment_due_at`, a
        `SettlementOfficer` may mark an `UNPAID` or `PARTIALLY_PAID` invoice as `IN_DEFAULT`,
        provided its `release_status` is not already `LOADED_OUT`. Exactly at `payment_due_at`
        the invoice is still on time and the request is refused with `ERR_PAYMENT_NOT_OVERDUE`.
        The transition increments the invoice's `version` by 1 and leaves the custody axis
        alone."
        PRD 3.8: "`payment_due_at` is the sale's `hammered_at` advanced by the number of days
        that the registration's `payment_terms_code` allows: 2 days for `PREPAY`, 7 days for
        `NET_7`, and 30 days for `NET_30`."

        Design: Corner/validations/defaulting_at_exactly_the_due_instant_is_refused_and_one_second_later_succeeds
        """
        stage = confirmed_invoice(lot_overrides={"serial_number": "CAT-D8T-0001"})
        invoice = stage["invoice"]
        assert stage["registration"]["payment_terms_code"] == "NET_7"
        assert invoice["payment_due_at"].startswith("2026-08-17T16:00:00")
        assert invoice["grace_end_at"].startswith("2026-08-15T16:00:00")
        assert invoice["release_status"] == "HELD"

        set_clock("2026-08-17T16:00:00Z")
        validate_error(
            api_client.default_invoice(invoice["id"], SETTLEMENT),
            ApiErrorId.ERR_PAYMENT_NOT_OVERDUE,
            expected_status=409,
        )
        on_time = validate_success(api_client.get_invoice(invoice["id"], SETTLEMENT))
        assert on_time["payment_status"] == "UNPAID"
        assert on_time["release_status"] == "HELD"
        assert on_time["version"] == invoice["version"]

        set_clock("2026-08-17T16:00:01Z")
        defaulted = validate_success(api_client.default_invoice(invoice["id"], SETTLEMENT))

        assert defaulted["payment_status"] == "IN_DEFAULT"
        assert defaulted["release_status"] == "HELD"
        assert defaulted["version"] == invoice["version"] + 1
