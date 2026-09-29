"""Striking the hammer, meeting the reserve, and closing the whole ring in one call."""
from test_helpers import (
    api_client,
    open_auction_with_catalogue,
    open_auction_with_catalogue_batch,
    place_bid,
    sequential_sales_batch,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import OPERATOR, SETTLEMENT

HAMMER_INSTANT = "2026-08-10T16:00:00Z"

THREE_LOT_BATCH = [
    {"serial_number": "CAT-D8T-0001", "reserve_price_cents": 1_000_000},
    {
        "make": "Komatsu",
        "model": "PC210",
        "model_year": 2020,
        "serial_number": "KOM-PC210-0002",
        "hour_meter_reading": 3_100,
        "weight_kg": 9_000,
        "reserve_price_cents": 1_000_000,
    },
    {
        "make": "Bobcat",
        "model": "S76",
        "model_year": 2021,
        "serial_number": "BOB-S76-0003",
        "hour_meter_reading": 900,
        "weight_kg": 6_000,
        "reserve_price_cents": 1_000_000,
    },
]

TWO_RESERVE_LOTS = [
    {"serial_number": "CAT-D8T-0001", "reserve_price_cents": 12_000_000},
    {
        "make": "Komatsu",
        "model": "PC490",
        "model_year": 2020,
        "serial_number": "KOM-PC490-0002",
        "hour_meter_reading": 4_100,
        "weight_kg": 48_000,
        "reserve_price_cents": 12_000_001,
    },
]


def _ring_ready_to_close():
    """Three catalogued lots on one OPEN event, two of them carrying standing bids."""
    stage = open_auction_with_catalogue_batch(THREE_LOT_BATCH, open_clock=HAMMER_INSTANT)
    lot_a, lot_b, _ = stage["lots"]
    validate_success(
        place_bid(stage["registration"], lot_a, 4_000_000, stage["bidder"]),
        expected_status=201,
    )
    validate_success(
        place_bid(stage["registration"], lot_b, 2_000_000, stage["bidder"]),
        expected_status=201,
    )
    return stage


class TestHammerSideEffects:
    def test_one_hammer_call_settles_the_lot_the_bids_the_sale_and_the_invoice(self):
        """The strike moves the lot, elects the winning bid, demotes the earlier one, mints the
        confirmed sale, writes the provisional invoice and restamps both counters.

        PRD 3.6: "**Hammering** a single lot moves it `ASSIGNED → HAMMERED` and creates the
        `Sale`."
        PRD 3.6: "The winning bid's `status` becomes `WINNING` and every other `ACTIVE` bid on
        that lot becomes `LOSING`."
        PRD 3.6: "When `reserve_met` is true, the sale moves straight from `PROVISIONAL` to
        `CONFIRMED` and an `Invoice` is created at the provisional variant; the bidder's
        `open_exposure_cents`, the registration's `bid_cap_cents`, and the auction's
        `sold_lot_count` and `gross_hammer_cents` are all recomputed."
        PRD 3.8: "`subtotal_cents` is then the sum of `hammer_price_cents`,
        `buyer_premium_cents`, `documentation_fee_cents`, `title_transfer_fee_cents` and
        `financing_fee_cents`."

        Design: Corner/state_machines/hammer_applies_every_declared_side_effect_in_one_call
        """
        stage = open_auction_with_catalogue(
            lot_overrides={
                "serial_number": "CAT-D8T-0001",
                "reserve_price_cents": 10_000_000,
            },
            open_clock=HAMMER_INSTANT,
        )
        lot, registration = stage["lot"], stage["registration"]
        first_bid = validate_success(
            place_bid(registration, lot, 11_000_000, stage["bidder"]), expected_status=201
        )
        second_bid = validate_success(
            place_bid(registration, lot, 12_000_000, stage["bidder"]), expected_status=201
        )

        sale = validate_success(
            api_client.hammer_lot(lot["id"], OPERATOR), expected_status=201
        )

        assert sale["status"] == "CONFIRMED"
        assert sale["reserve_met"] is True
        assert sale["hammer_price_cents"] == 12_000_000
        assert sale["winning_bid_id"] == second_bid["id"]
        assert sale["hammered_at"].startswith("2026-08-10T16:00:00")
        assert sale["counter_round"] == 0

        assert (
            validate_success(api_client.get_bid(first_bid["id"], OPERATOR))["status"]
            == "LOSING"
        )
        assert (
            validate_success(api_client.get_bid(second_bid["id"], OPERATOR))["status"]
            == "WINNING"
        )
        assert (
            validate_success(api_client.get_lot(lot["id"], OPERATOR))["lifecycle_status"]
            == "HAMMERED"
        )

        rows, meta = validate_paginated(
            api_client.list_invoices(SETTLEMENT, params={"sale_id": sale["id"]})
        )
        assert meta["total_count"] == 1
        invoice = validate_success(api_client.get_invoice(rows[0]["id"], SETTLEMENT))
        assert invoice["settlement_variant"] == "PROVISIONAL"
        assert invoice["buyer_premium_cents"] == 1_160_000
        assert invoice["subtotal_cents"] == 13_175_000
        assert invoice["tax_cents"] == 823_438
        assert invoice["deposit_applied_cents"] == 1_500_000
        assert invoice["total_due_cents"] == 12_498_438

        auction = validate_success(api_client.get_auction(stage["auction"]["id"], OPERATOR))
        assert auction["sold_lot_count"] == 1
        assert auction["gross_hammer_cents"] == 12_000_000
        stored_registration = validate_success(
            api_client.get_bidder_registration(registration["id"], SETTLEMENT)
        )
        assert stored_registration["bid_cap_cents"] == 2_501_562
        assert stored_registration["deposit_applied_total_cents"] == 1_500_000

    def test_the_hammer_response_and_the_reads_that_follow_it_already_agree(self):
        """No settling step exists: the response itself carries the derived sale, and the very
        next reads of the lot, the invoice and the counters show the post-strike values.

        PRD 2.9: "A large fraction of the fields in this system are **derived**: they are never
        supplied by a client and are recomputed by the server whenever anything they depend on
        is written. Recomputation is immediate and synchronous — there is no
        eventual-consistency window".
        PRD 3.6: "The sale is created with its `lot_id`, an `auction_id` copied from the lot, a
        `winning_bid_id` naming the highest `ACTIVE` bid on the lot, the `registration_id` of
        that winning bid, a `hammer_price_cents` equal to the lot's `high_bid_cents`, a
        `hammered_at` taken from the logical clock, `counter_round` at 0, and
        `counter_price_cents` and `reject_reason` at null."

        Design: Corner/consistency model/hammer_response_and_immediate_reads_agree_with_no_settling_time
        """
        stage = open_auction_with_catalogue(
            lot_overrides={
                "serial_number": "CAT-D8T-0001",
                "reserve_price_cents": 10_000_000,
            },
            open_clock=HAMMER_INSTANT,
        )
        lot = stage["lot"]
        validate_success(
            place_bid(stage["registration"], lot, 12_000_000, stage["bidder"]),
            expected_status=201,
        )

        sale = validate_success(
            api_client.hammer_lot(lot["id"], OPERATOR), expected_status=201
        )

        assert sale["status"] == "CONFIRMED"
        assert sale["hammer_price_cents"] == 12_000_000
        assert sale["reserve_met"] is True
        assert sale["hammered_at"].startswith("2026-08-10T16:00:00")
        assert sale["lot_id"] == lot["id"]
        assert sale["auction_id"] == stage["auction"]["id"]
        assert sale["counter_price_cents"] is None
        assert sale["reject_reason"] is None

        assert (
            validate_success(api_client.get_lot(lot["id"], OPERATOR))["lifecycle_status"]
            == "HAMMERED"
        )
        rows, meta = validate_paginated(
            api_client.list_invoices(SETTLEMENT, params={"sale_id": sale["id"]})
        )
        assert meta["total_count"] == 1
        auction = validate_success(api_client.get_auction(stage["auction"]["id"], OPERATOR))
        assert auction["sold_lot_count"] == 1
        assert auction["unsold_lot_count"] == 0
        invoice = validate_success(api_client.get_invoice(rows[0]["id"], SETTLEMENT))
        assert invoice["settlement_variant"] == "PROVISIONAL"
        assert invoice["total_due_cents"] == 12_498_438


class TestReserveBoundary:
    def test_a_hammer_exactly_at_the_reserve_confirms_and_invoices(self):
        """The comparison is inclusive, so 12,000,000 against a 12,000,000 reserve sells the
        machine outright.

        PRD 3.6: "It is true when the auction's `reserve_policy` is `UNRESERVED`, or when the
        lot's `reserve_price_cents` is null, or when `hammer_price_cents` is greater than or
        equal to the lot's `reserve_price_cents`. A hammer price exactly equal to the reserve
        satisfies the comparison and confirms the sale."

        Design: Difficulty/boundary_precision_check/reserve_exact_match_confirms_while_one_cent_short_stays_provisional
        """
        stage = sequential_sales_batch(
            TWO_RESERVE_LOTS,
            [12_000_000, 12_000_000],
            [HAMMER_INSTANT, "2026-08-10T16:05:00Z"],
        )
        at_reserve_sale = stage["sales"][0]

        assert at_reserve_sale["reserve_met"] is True
        assert at_reserve_sale["status"] == "CONFIRMED"
        assert at_reserve_sale["hammer_price_cents"] == 12_000_000
        assert stage["lots"][0]["lifecycle_status"] == "HAMMERED"

        rows, meta = validate_paginated(
            api_client.list_invoices(
                SETTLEMENT, params={"sale_id": at_reserve_sale["id"]}
            )
        )
        assert meta["total_count"] == 1
        invoice = validate_success(api_client.get_invoice(rows[0]["id"], SETTLEMENT))
        assert invoice["total_due_cents"] == 12_498_438

    def test_a_hammer_one_cent_short_of_the_reserve_stays_provisional_and_uninvoiced(self):
        """The identical 12,000,000 strike against a 12,000,001 reserve mints no invoice and
        contributes nothing to the gross, while still counting as a sold lot.

        PRD 3.6: "When `reserve_met` is false, the sale stays in `PROVISIONAL` awaiting the
        seller's judgement, no invoice exists yet, and §3.7 takes over."
        PRD 2.9: "On an auction, `assigned_lot_count` counts lots pointing at it whose
        `lifecycle_status` is anything other than `WITHDRAWN`, `sold_lot_count` counts its
        sales whose `status` is `PROVISIONAL`, `CONSIGNOR_COUNTERED`, `CONFIRMED`, `SETTLED` or
        `DEFAULTED`, `unsold_lot_count` counts its lots whose `lifecycle_status` is `UNSOLD`,
        and `gross_hammer_cents` sums `hammer_price_cents` across its sales whose `status` is
        `CONFIRMED` or `SETTLED`."

        Design: Difficulty/boundary_precision_check/reserve_exact_match_confirms_while_one_cent_short_stays_provisional
        """
        stage = sequential_sales_batch(
            TWO_RESERVE_LOTS,
            [12_000_000, 12_000_000],
            [HAMMER_INSTANT, "2026-08-10T16:05:00Z"],
        )
        short_sale = stage["sales"][1]

        assert short_sale["reserve_met"] is False
        assert short_sale["status"] == "PROVISIONAL"
        assert short_sale["hammer_price_cents"] == 12_000_000
        assert short_sale["hammered_at"].startswith("2026-08-10T16:05:00")
        assert stage["invoices"][1] is None

        _, meta = validate_paginated(
            api_client.list_invoices(SETTLEMENT, params={"sale_id": short_sale["id"]})
        )
        assert meta["total_count"] == 0

        auction = validate_success(api_client.get_auction(stage["auction"]["id"], OPERATOR))
        assert auction["sold_lot_count"] == 2
        assert auction["gross_hammer_cents"] == 12_000_000
        bidder = validate_success(api_client.get_bidder(stage["bidder"]["id"], SETTLEMENT))
        assert bidder["open_exposure_cents"] == 12_498_438


class TestCloseCascade:
    def test_closing_hammers_every_bid_lot_in_created_order_and_shelves_the_rest(self):
        """One call closes the event, strikes the two lots that carry bids at the same instant,
        and moves the untouched lot to UNSOLD without minting a sale for it.

        PRD 3.6: "First, the auction moves `OPEN → CLOSED`. Second, every still-`ASSIGNED` lot
        of the auction is processed in ascending `created_at` order: a lot whose
        `high_bid_cents` is greater than zero is auto-hammered exactly as above, moving
        `ASSIGNED → HAMMERED` with a `Sale` created; a lot whose `high_bid_cents` is zero moves
        `ASSIGNED → UNSOLD` and no sale row is created for it at all."

        Design: Difficulty/transitive_cascade/auction_close_fans_out_hammer_sale_invoice_and_counters
        """
        stage = _ring_ready_to_close()
        lot_a, lot_b, lot_c = stage["lots"]

        closed = validate_success(
            api_client.close_auction(stage["auction"]["id"], OPERATOR)
        )

        assert closed["status"] == "CLOSED"
        assert (
            validate_success(api_client.get_lot(lot_a["id"], OPERATOR))["lifecycle_status"]
            == "HAMMERED"
        )
        assert (
            validate_success(api_client.get_lot(lot_b["id"], OPERATOR))["lifecycle_status"]
            == "HAMMERED"
        )
        assert (
            validate_success(api_client.get_lot(lot_c["id"], OPERATOR))["lifecycle_status"]
            == "UNSOLD"
        )

        sales, meta = validate_paginated(
            api_client.list_sales(OPERATOR, params={"auction_id": stage["auction"]["id"]})
        )
        assert meta["total_count"] == 2
        assert all(sale["hammered_at"].startswith("2026-08-10T16:00:00") for sale in sales)
        assert {sale["lot_id"] for sale in sales} == {lot_a["id"], lot_b["id"]}
        assert lot_c["id"] not in {sale["lot_id"] for sale in sales}

    def test_the_deposit_lands_on_the_first_hammered_invoice_and_the_counters_follow(self):
        """The created-order walk is what puts the whole 1,500,000-cent hold on the first
        machine's invoice, leaving the second one to pay its gross in full.

        PRD 3.6: "Third, every sale created with `reserve_met` true becomes `CONFIRMED` and an
        invoice is created at the provisional variant. Fourth, the derived aggregates are
        recomputed: the bidder's `open_exposure_cents`, the registration's
        `deposit_applied_total_cents` and `bid_cap_cents`, the auction's `sold_lot_count`,
        `unsold_lot_count` and `gross_hammer_cents`, and the consignment's `unsold_lot_count`."
        PRD 3.8: "Each invoice in turn consumes the smaller of the remaining hold and its own
        gross-before-deposit amount, so the earliest machines absorb the deposit first and
        later ones may get nothing."

        Design: Difficulty/transitive_cascade/auction_close_fans_out_hammer_sale_invoice_and_counters
        """
        stage = _ring_ready_to_close()
        lot_a, lot_b, _ = stage["lots"]

        validate_success(api_client.close_auction(stage["auction"]["id"], OPERATOR))

        sales, _ = validate_paginated(
            api_client.list_sales(OPERATOR, params={"auction_id": stage["auction"]["id"]})
        )
        by_lot = {sale["lot_id"]: sale for sale in sales}
        assert by_lot[lot_a["id"]]["status"] == "CONFIRMED"
        assert by_lot[lot_b["id"]]["status"] == "CONFIRMED"

        invoices, invoice_meta = validate_paginated(
            api_client.list_invoices(
                SETTLEMENT, params={"registration_id": stage["registration"]["id"]}
            )
        )
        assert invoice_meta["total_count"] == 2
        by_sale = {
            invoice["sale_id"]: validate_success(
                api_client.get_invoice(invoice["id"], SETTLEMENT)
            )
            for invoice in invoices
        }
        first = by_sale[by_lot[lot_a["id"]]["id"]]
        second = by_sale[by_lot[lot_b["id"]]["id"]]

        assert first["buyer_premium_cents"] == 480_000
        assert first["subtotal_cents"] == 4_495_000
        assert first["tax_cents"] == 280_938
        assert first["deposit_applied_cents"] == 1_500_000
        assert first["total_due_cents"] == 3_275_938

        assert second["buyer_premium_cents"] == 240_000
        assert second["subtotal_cents"] == 2_255_000
        assert second["tax_cents"] == 140_938
        assert second["deposit_applied_cents"] == 0
        assert second["total_due_cents"] == 2_395_938

        auction = validate_success(api_client.get_auction(stage["auction"]["id"], OPERATOR))
        assert auction["sold_lot_count"] == 2
        assert auction["unsold_lot_count"] == 1
        assert auction["gross_hammer_cents"] == 6_000_000
        assert auction["assigned_lot_count"] == 3
        assert (
            validate_success(
                api_client.get_consignment(stage["consignment"]["id"], OPERATOR)
            )["unsold_lot_count"]
            == 1
        )
        bidder = validate_success(api_client.get_bidder(stage["bidder"]["id"], SETTLEMENT))
        assert bidder["open_exposure_cents"] == 5_671_876
        stored_registration = validate_success(
            api_client.get_bidder_registration(stage["registration"]["id"], SETTLEMENT)
        )
        assert stored_registration["deposit_applied_total_cents"] == 1_500_000
        assert stored_registration["bid_cap_cents"] == 9_328_124
