"""The settlement desk: the two invoice variants, storage accrual, payment and release."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    cleared_export_packet,
    confirmed_invoice,
    create_payment_payload,
    open_auction_with_catalogue_batch,
    place_bid,
    release_authorized_invoice,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import OPERATOR, SETTLEMENT

GERMAN_BUYER = {
    "legal_name": "Rheintal Baumaschinen GmbH",
    "country_code": "DE",
    "tax_id": "DE811234567",
}
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
    "weight_kg": 22_000,
    "reserve_price_cents": 1_000_000,
}


def _preview(invoice, variant):
    return validate_success(
        api_client.get_settlement_preview(
            invoice["id"], SETTLEMENT, params={"variant": variant}
        )
    )


class TestTheTwoVariants:
    def test_the_provisional_variant_taxes_a_cross_border_sale_at_the_buyers_own_rate(self):
        """At hammer time no clearance can exist, so the German rate applies in full and no
        storage has accrued.

        PRD 3.8: "The provisional variant is stamped at invoice creation and always applies the
        buyer's own domestic tax rate — even on a cross-border sale — because no customs
        clearance can exist at hammer time; it also forces `storage_fee_cents` and
        `chargeable_storage_days` to zero."
        PRD 3.8: "`documentation_fee_cents` is 45,000 cents when `is_cross_border` is true and
        15,000 cents when it is false."

        Design: Difficulty/dual_variant_calc/invoice_provisional_versus_final_export_zero_rating
        """
        stage = confirmed_invoice(lot_overrides=HEAVY_LOT, bidder_overrides=GERMAN_BUYER)
        invoice = stage["invoice"]
        cleared_export_packet(invoice, "DE")
        set_clock("2026-08-16T16:00:00Z")

        preview = _preview(invoice, "PROVISIONAL")

        assert preview["buyer_premium_cents"] == 1_160_000
        assert preview["documentation_fee_cents"] == 45_000
        assert preview["subtotal_cents"] == 13_205_000
        assert preview["tax_rate_applied"] == pytest.approx(0.1900, abs=0.00001)
        assert preview["tax_cents"] == 2_508_950
        assert preview["chargeable_storage_days"] == 0
        assert preview["storage_fee_cents"] == 0
        assert preview["deposit_applied_cents"] == 1_500_000
        assert preview["total_due_cents"] == 14_213_950

    def test_the_final_variant_zero_rates_the_cleared_export_and_charges_the_stored_day(self):
        """The same row read at the final variant drops the whole German tax and adds one heavy
        machine day, and neither preview writes anything.

        PRD 3.8: "One exception overrides it: at the final variant, a cross-border invoice whose
        export packet has reached `EXPORT_CLEARED` is zero-rated, with `tax_rate_applied` set to
        0.0000."
        PRD 3.8: "The daily rate is keyed to the machine's `weight_kg`: 2,500 cents per day for
        a light machine of at most 10,000 kg, 6,000 cents per day for a medium machine of at
        most 30,000 kg, and 12,000 cents per day for anything heavier."
        PRD 3.8: "It takes a `variant` and returns, without mutating anything, the `invoice_id`,
        the `variant` requested, `hammer_price_cents`, `buyer_premium_cents`".

        Design: Difficulty/dual_variant_calc/invoice_provisional_versus_final_export_zero_rating
        """
        stage = confirmed_invoice(lot_overrides=HEAVY_LOT, bidder_overrides=GERMAN_BUYER)
        invoice = stage["invoice"]
        packet = cleared_export_packet(invoice, "DE")
        assert packet["status"] == "EXPORT_CLEARED"
        assert invoice["grace_end_at"].startswith("2026-08-15T16:00:00")
        set_clock("2026-08-16T16:00:00Z")

        preview = _preview(invoice, "FINAL")

        assert preview["tax_rate_applied"] == pytest.approx(0.0000, abs=0.00001)
        assert preview["tax_cents"] == 0
        assert preview["chargeable_storage_days"] == 1
        assert preview["storage_fee_cents"] == 12_000
        assert preview["total_due_cents"] == 11_717_000

        stored = validate_success(api_client.get_invoice(invoice["id"], SETTLEMENT))
        assert stored["settlement_variant"] == "PROVISIONAL"
        assert stored["total_due_cents"] == 14_213_950


class TestStorageBoundaries:
    def test_whole_days_only_so_one_second_short_of_the_first_day_accrues_nothing(self):
        """At the grace end and one second short of a full day past it the machine is still
        free, and the very next second buys the first day.

        PRD 3.8: "Take the elapsed time from `grace_end_at` to the logical clock's current
        instant, floored at zero, and divide by a full day, discarding any remainder:
        `chargeable_storage_days` counts **whole** days only, so a machine collected 23 hours
        and 59 minutes past the grace end accrues nothing, and one collected exactly 24 hours
        past accrues a single day."
        PRD 3.8: "`payment_due_at` is the sale's `hammered_at` advanced by the number of days
        that the registration's `payment_terms_code` allows: 2 days for `PREPAY`, 7 days for
        `NET_7`, and 30 days for `NET_30`."

        Design: Difficulty/boundary_precision_check/storage_grace_boundary_zero_versus_one_chargeable_day_and_cap
        """
        stage = confirmed_invoice(lot_overrides=HEAVY_LOT)
        invoice = stage["invoice"]
        assert invoice["grace_end_at"].startswith("2026-08-15T16:00:00")
        assert invoice["payment_due_at"].startswith("2026-08-17T16:00:00")

        for instant in ("2026-08-15T16:00:00Z", "2026-08-16T15:59:59Z"):
            set_clock(instant)
            free = _preview(invoice, "FINAL")
            assert free["chargeable_storage_days"] == 0
            assert free["storage_fee_cents"] == 0
            assert free["total_due_cents"] == 12_498_438
            assert free["tax_cents"] == 823_438

        set_clock("2026-08-16T16:00:00Z")
        first_day = _preview(invoice, "FINAL")

        assert first_day["chargeable_storage_days"] == 1
        assert first_day["storage_fee_cents"] == 12_000
        assert first_day["total_due_cents"] == 12_510_438
        assert first_day["tax_cents"] == 823_438

    def test_the_accrual_is_capped_at_a_quarter_of_the_hammer_price(self):
        """Three days accrue linearly, and a year of storage stops at 3,000,000 cents instead of
        the 4,392,000 the daily rate would give.

        PRD 3.8: "Multiply days by rate, then cap the result at twenty-five percent of
        `hammer_price_cents` rounded half up to whole cents; `storage_fee_cents` is the smaller
        of the uncapped accrual and that cap."
        PRD 3.8: "Note carefully that the tax base is the subtotal; storage fees are never
        taxed."

        Design: Difficulty/boundary_precision_check/storage_grace_boundary_zero_versus_one_chargeable_day_and_cap
        """
        stage = confirmed_invoice(lot_overrides=HEAVY_LOT)
        invoice = stage["invoice"]

        set_clock("2026-08-18T16:00:00Z")
        three_days = _preview(invoice, "FINAL")
        assert three_days["chargeable_storage_days"] == 3
        assert three_days["storage_fee_cents"] == 36_000
        assert three_days["total_due_cents"] == 12_534_438

        set_clock("2027-08-16T16:00:00Z")
        capped = _preview(invoice, "FINAL")

        assert capped["chargeable_storage_days"] == 366
        assert capped["storage_fee_cents"] == 3_000_000
        assert capped["storage_fee_cents"] != 4_392_000
        assert capped["total_due_cents"] == 15_498_438
        assert capped["tax_cents"] == 823_438
        assert (
            validate_success(api_client.get_invoice(invoice["id"], SETTLEMENT))[
                "settlement_variant"
            ]
            == "PROVISIONAL"
        )


class TestTheTwoAxesDisagree:
    def test_finalising_a_paid_invoice_pushes_the_money_axis_backwards(self):
        """One day of storage restamps the total above what the buyer already tendered, so a
        settled invoice becomes partially paid again.

        PRD 3.8: "Because accrued storage can push `total_due_cents` above what the buyer has
        already tendered, the money axis may **regress**: an invoice whose `payment_status` was
        `PAID` moves back to `PARTIALLY_PAID` with `outstanding_cents` set to the new
        `total_due_cents` less `amount_paid_cents`."
        PRD 3.8: "**Finalisation** restamps the invoice at the final variant. A
        `SettlementOfficer` triggers it; it moves `settlement_variant` `PROVISIONAL → FINAL` and
        restamps `storage_fee_cents`, `chargeable_storage_days`, `tax_rate_applied`, `tax_cents`,
        `deposit_applied_cents` and `total_due_cents`, recomputes the bidder's
        `open_exposure_cents`, and increments the invoice's `version` by 1."

        Design: Difficulty/non_linear_state_machine/invoice_payment_axis_regresses_while_release_axis_holds
        """
        stage = release_authorized_invoice(
            lot_overrides=HEAVY_LOT, settle_consignor=False
        )
        invoice = stage["invoice"]
        assert invoice["payment_status"] == "PAID"
        assert invoice["release_status"] == "RELEASE_AUTHORIZED"
        set_clock("2026-08-16T16:00:00Z")

        finalized = validate_success(api_client.finalize_invoice(invoice["id"], SETTLEMENT))

        assert finalized["settlement_variant"] == "FINAL"
        assert finalized["chargeable_storage_days"] == 1
        assert finalized["storage_fee_cents"] == 12_000
        assert finalized["tax_cents"] == 823_438
        assert finalized["total_due_cents"] == 12_510_438
        assert finalized["amount_paid_cents"] == 12_498_438
        assert finalized["outstanding_cents"] == 12_000
        assert finalized["payment_status"] == "PARTIALLY_PAID"

    def test_the_custody_axis_is_left_exactly_where_the_release_put_it(self):
        """The regression on the money axis does not disturb the authorised release, and the
        bidder's exposure follows the new total.

        PRD 3.8: "The custody axis is untouched by finalisation — this is the clearest
        illustration of the two axes being independent."
        PRD 2.9: "An invoice has a `payment_status` describing money and a `release_status`
        describing custody; the money axis can regress from `PAID` back to `PARTIALLY_PAID`
        while the custody axis stays exactly where it was, and custody can advance while the
        money axis is untouched."

        Design: Difficulty/non_linear_state_machine/invoice_payment_axis_regresses_while_release_axis_holds
        """
        stage = release_authorized_invoice(
            lot_overrides=HEAVY_LOT, settle_consignor=False
        )
        invoice = stage["invoice"]
        set_clock("2026-08-16T16:00:00Z")

        validate_success(api_client.finalize_invoice(invoice["id"], SETTLEMENT))

        stored = validate_success(api_client.get_invoice(invoice["id"], SETTLEMENT))
        assert stored["release_status"] == "RELEASE_AUTHORIZED"
        assert stored["payment_status"] == "PARTIALLY_PAID"
        assert stored["outstanding_cents"] == 12_000
        assert (
            validate_success(api_client.get_bidder(stage["bidder"]["id"], SETTLEMENT))[
                "open_exposure_cents"
            ]
            == 12_510_438
        )


class TestMoneyGuardsBeforeRelease:
    def test_the_currency_and_overpayment_guards_stand_between_the_buyer_and_release(self):
        """Release is refused while the invoice is unpaid, a euro tender and a one-cent
        overpayment are both refused, and only the exact tender opens the gate.

        PRD 3.8: "The currency must equal the auction yard's `currency_code`; cross-currency
        tenders are refused with `ERR_CURRENCY_MISMATCH` rather than converted. The amount may
        not exceed `outstanding_cents` — the house holds no buyer credit balances, so settlement
        is exact or short, and an overpayment is refused with `ERR_OVERPAYMENT`."
        PRD 3.8: "the invoice's `payment_status` must be `PAID`, otherwise
        `ERR_INVOICE_NOT_PAID`".
        PRD 3.8: "A tender exactly equal to `outstanding_cents` moves the invoice to `PAID` —
        from `UNPAID` when the whole balance is settled in one instrument, and from
        `PARTIALLY_PAID` when the final instalment closes it out — and sets `outstanding_cents`
        to 0."

        Design: Corner/validations/release_guards_are_cleared_in_order_before_authorisation_succeeds
        """
        stage = confirmed_invoice(lot_overrides=HEAVY_LOT)
        invoice, bidder_headers = stage["invoice"], stage["bidder_headers"]
        assert invoice["outstanding_cents"] == 12_498_438

        validate_error(
            api_client.authorize_release(invoice["id"], SETTLEMENT),
            ApiErrorId.ERR_INVOICE_NOT_PAID,
            expected_status=409,
        )
        validate_error(
            api_client.create_payment(
                create_payment_payload(invoice["id"], 12_498_438, currency_code="EUR"),
                bidder_headers,
            ),
            ApiErrorId.ERR_CURRENCY_MISMATCH,
            expected_status=422,
        )
        validate_error(
            api_client.create_payment(
                create_payment_payload(invoice["id"], 12_498_439), bidder_headers
            ),
            ApiErrorId.ERR_OVERPAYMENT,
            expected_status=422,
        )

        payment = validate_success(
            api_client.create_payment(
                create_payment_payload(invoice["id"], 12_498_438), bidder_headers
            ),
            expected_status=201,
        )
        assert payment["status"] == "SETTLED"

        settled = validate_success(api_client.get_invoice(invoice["id"], SETTLEMENT))
        assert settled["payment_status"] == "PAID"
        assert settled["amount_paid_cents"] == 12_498_438
        assert settled["outstanding_cents"] == 0

        authorized = validate_success(api_client.authorize_release(invoice["id"], SETTLEMENT))
        assert authorized["release_status"] == "RELEASE_AUTHORIZED"

        _, meta = validate_paginated(
            api_client.list_invoice_payments(invoice["id"], SETTLEMENT)
        )
        assert meta["total_count"] == 1

    def test_settling_the_invoice_drops_it_out_of_the_forecast_exposure(self):
        """The forecast counts only open obligations, so paying in full restores the paddle's
        whole 15,000,000-cent headroom.

        PRD 3.5: "Compute the forecast exposure as the sum of `total_due_cents` across the
        registration's invoices whose `payment_status` is `UNPAID` or `PARTIALLY_PAID` and whose
        underlying sale's `status` is `CONFIRMED` or `SETTLED`; this is the same quantity the
        bidder carries as `open_exposure_cents`. The forecast cap is then the base headroom plus
        `approved_credit_limit_cents` less that exposure, floored at zero."
        PRD 3.5: "This forecast is restamped on the registration whenever any invoice of the
        registration is written, so `bid_cap_cents` tracks the money actually owed."

        Design: Corner/calculations/paying_an_invoice_removes_it_from_the_forecast_exposure_input_set
        """
        stage = confirmed_invoice(lot_overrides=HEAVY_LOT)
        invoice, registration = stage["invoice"], stage["registration"]

        assert (
            validate_success(api_client.get_bidder(stage["bidder"]["id"], SETTLEMENT))[
                "open_exposure_cents"
            ]
            == 12_498_438
        )
        assert (
            validate_success(
                api_client.get_bidder_registration(registration["id"], SETTLEMENT)
            )["bid_cap_cents"]
            == 2_501_562
        )

        payment = validate_success(
            api_client.create_payment(
                create_payment_payload(invoice["id"], 12_498_438), stage["bidder_headers"]
            ),
            expected_status=201,
        )

        assert payment["status"] == "SETTLED"
        settled = validate_success(api_client.get_invoice(invoice["id"], SETTLEMENT))
        assert settled["payment_status"] == "PAID"
        assert settled["outstanding_cents"] == 0
        assert (
            validate_success(api_client.get_bidder(stage["bidder"]["id"], SETTLEMENT))[
                "open_exposure_cents"
            ]
            == 0
        )
        assert (
            validate_success(
                api_client.get_bidder_registration(registration["id"], SETTLEMENT)
            )["bid_cap_cents"]
            == 15_000_000
        )


class TestDepositWaterfallAcrossInvoices:
    def test_the_single_hold_is_drawn_down_by_the_earlier_machine_alone(self):
        """One close mints two invoices for the same paddle, and the whole hold lands on the
        first machine while the second is billed its gross.

        PRD 3.8: "`deposit_applied_cents` then draws down the registration's deposit hold.
        Because one registration may buy several machines, the hold is consumed by a waterfall
        across every invoice of that registration, ordered by ascending `hammered_at` of the
        underlying sale with ties broken by ascending `created_at` of the invoice."
        PRD 2.9: "On a registration, `deposit_applied_total_cents` sums `deposit_applied_cents`
        across that registration's invoices."

        Design: Corner/calculations/deposit_hold_is_consumed_by_the_earlier_invoice_first
        """
        stage = open_auction_with_catalogue_batch(
            [HEAVY_LOT, SECOND_LOT], open_clock="2026-08-10T16:00:00Z"
        )
        first_lot, second_lot = stage["lots"]
        validate_success(
            place_bid(stage["registration"], first_lot, 12_000_000, stage["bidder"]),
            expected_status=201,
        )
        validate_success(
            place_bid(stage["registration"], second_lot, 2_000_000, stage["bidder"]),
            expected_status=201,
        )

        validate_success(api_client.close_auction(stage["auction"]["id"], OPERATOR))

        sales, _ = validate_paginated(
            api_client.list_sales(OPERATOR, params={"auction_id": stage["auction"]["id"]})
        )
        by_lot = {sale["lot_id"]: sale for sale in sales}
        assert by_lot[first_lot["id"]]["status"] == "CONFIRMED"
        assert by_lot[second_lot["id"]]["status"] == "CONFIRMED"

        invoices, meta = validate_paginated(
            api_client.list_invoices(
                SETTLEMENT, params={"registration_id": stage["registration"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        by_sale = {
            row["sale_id"]: validate_success(api_client.get_invoice(row["id"], SETTLEMENT))
            for row in invoices
        }
        first = by_sale[by_lot[first_lot["id"]]["id"]]
        second = by_sale[by_lot[second_lot["id"]]["id"]]

        assert first["deposit_applied_cents"] == 1_500_000
        assert first["total_due_cents"] == 12_498_438
        assert second["buyer_premium_cents"] == 240_000
        assert second["subtotal_cents"] == 2_255_000
        assert second["tax_cents"] == 140_938
        assert second["deposit_applied_cents"] == 0
        assert second["total_due_cents"] == 2_395_938

        assert (
            validate_success(
                api_client.get_bidder_registration(
                    stage["registration"]["id"], SETTLEMENT
                )
            )["deposit_applied_total_cents"]
            == 1_500_000
        )
        assert (
            validate_success(api_client.get_bidder(stage["bidder"]["id"], SETTLEMENT))[
                "open_exposure_cents"
            ]
            == 14_894_376
        )
