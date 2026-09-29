"""Buyer premium schedules, the fee spine and the tax base stamped at the hammer."""
import pytest

from test_helpers import (
    api_client,
    confirmed_invoice,
    sequential_sales_batch,
    validate_success,
)
from test_helpers.fixtures import OPERATOR, SETTLEMENT

NIGERIAN_BUYER = {
    "legal_name": "Lagos Plant Hire Ltd",
    "country_code": "NG",
    "tax_id": "NG-0000001",
}

ONLINE_AUCTION = {
    "kind": "TIMED_ONLINE",
    "premium_schedule_code": "STANDARD",
    "window_start": "2026-08-10T14:00:00Z",
    "window_end": "2026-08-10T22:00:00Z",
}

BIG_TICKET_LOT = {
    "serial_number": "CAT-D8T-0001",
    "weight_kg": 36_000,
    "reserve_price_cents": 50_000_000,
}
FOLLOW_ON_LOT = {
    "make": "Bobcat",
    "model": "S76",
    "model_year": 2021,
    "serial_number": "BOB-S76-0002",
    "hour_meter_reading": 900,
    "weight_kg": 6_000,
    "reserve_price_cents": 10_000_000,
}


def _online_run(lot_specs, bid_amounts, hammer_clocks):
    """A TIMED_ONLINE STANDARD event bought by one heavily funded TIER_A paddle."""
    return sequential_sales_batch(
        lot_specs,
        bid_amounts,
        hammer_clocks,
        auction_overrides=ONLINE_AUCTION,
        deposit_cents=10_000_000,
        deposit_hold_cents=9_000_000,
    )


class TestStandardPremiumOrdering:
    def test_the_online_surcharge_is_added_before_the_ceiling_bites(self):
        """The marginal tiers give 3,950,000, the surcharge lifts that to 4,850,000, and only
        then does the ceiling cut it to 4,000,000.

        PRD 3.8: "Step one applies marginal tiers, each rounded to whole cents before the tiers
        are summed: twelve percent of the portion of the hammer price up to 5,000,000 cents;
        eight percent of the portion between 5,000,000 and 25,000,000 cents; and five percent of
        everything above 25,000,000 cents."
        PRD 3.8: "Step two adds an online surcharge of one and one-half percent — rounded half
        up to whole cents — computed on the **hammer price**, not on the premium, and only when
        the auction's `kind` is `TIMED_ONLINE`; a live on-site event adds nothing."
        PRD 3.8: "Step four clamps the result: the premium is at least 25,000 cents and at most
        4,000,000 cents. Applying the clamp before the surcharge or before the discount produces
        different figures and is not the specified behaviour."

        Design: Difficulty/combinatorial_formula/premium_tier_sum_then_online_surcharge_then_ceiling_clamp
        """
        stage = _online_run([BIG_TICKET_LOT], [60_000_000], ["2026-08-10T16:00:00Z"])
        invoice = stage["invoices"][0]

        assert invoice["buyer_premium_cents"] == 4_000_000
        assert invoice["documentation_fee_cents"] == 15_000
        assert invoice["subtotal_cents"] == 64_015_000
        assert invoice["settlement_variant"] == "PROVISIONAL"
        assert invoice["storage_fee_cents"] == 0

    def test_the_half_up_tax_and_the_deposit_close_out_the_clamped_invoice(self):
        """The 6.25 percent tax on 64,015,000 rounds 4,000,937.5 up, and the 9,000,000-cent hold
        is drawn down in full.

        PRD 3.8: "`tax_cents` is `tax_rate_applied` applied to `subtotal_cents`, rounded half up
        to whole cents. Note carefully that the tax base is the subtotal; storage fees are never
        taxed."
        PRD 3.8: "`total_due_cents` is the gross-before-deposit amount less
        `deposit_applied_cents`, and `outstanding_cents` is the larger of 0 and
        `total_due_cents` less `amount_paid_cents`."

        Design: Difficulty/combinatorial_formula/premium_tier_sum_then_online_surcharge_then_ceiling_clamp
        """
        stage = _online_run([BIG_TICKET_LOT], [60_000_000], ["2026-08-10T16:00:00Z"])
        invoice = stage["invoices"][0]

        assert invoice["tax_rate_applied"] == pytest.approx(0.0625, abs=0.00001)
        assert invoice["tax_cents"] == 4_000_938
        assert invoice["deposit_applied_cents"] == 9_000_000
        assert invoice["total_due_cents"] == 59_015_938
        assert invoice["outstanding_cents"] == 59_015_938


class TestVolumeDiscount:
    def test_the_discount_is_keyed_on_the_earlier_hammer_and_taken_before_the_clamp(self):
        """The second machine of the same paddle in the same event earns ten percent off its
        post-surcharge premium, which is 1,206,000 rather than the undiscounted 1,340,000.

        PRD 3.8: "Step three applies a same-auction volume discount, evaluated against prior
        hammer volume only. The prior volume is the sum of `hammer_price_cents` across sales of
        the **same auction and same registration** whose `status` is `CONFIRMED` or `SETTLED`
        and whose `hammered_at` is strictly earlier than this sale's, with ties broken by
        ascending `created_at`; the sale being priced never counts toward its own discount."
        PRD 3.8: "A prior volume of at least 100,000,000 cents earns a twenty percent discount;
        failing that, at least 50,000,000 cents earns ten percent; below that there is no
        discount. The discount is taken by rounding the discount percentage of the
        post-surcharge premium half up to whole cents and subtracting it."

        Design: Difficulty/combinatorial_formula/volume_discount_keyed_on_prior_hammer_evaluated_before_clamp
        """
        stage = _online_run(
            [BIG_TICKET_LOT, FOLLOW_ON_LOT],
            [60_000_000, 12_000_000],
            ["2026-08-10T16:00:00Z", "2026-08-10T16:05:00Z"],
        )
        second = stage["invoices"][1]

        assert stage["invoices"][0]["buyer_premium_cents"] == 4_000_000
        assert second["buyer_premium_cents"] == 1_206_000
        assert second["buyer_premium_cents"] != 1_340_000
        assert second["subtotal_cents"] == 13_221_000
        assert second["tax_cents"] == 826_313

    def test_the_exhausted_deposit_leaves_the_second_invoice_to_pay_its_gross_in_full(self):
        """The first machine absorbed the whole hold, so the later invoice applies nothing and
        the event's aggregates count both sales.

        PRD 3.8: "Because one registration may buy several machines, the hold is consumed by a
        waterfall across every invoice of that registration, ordered by ascending `hammered_at`
        of the underlying sale with ties broken by ascending `created_at` of the invoice."
        PRD 2.9: "`gross_hammer_cents` sums `hammer_price_cents` across its sales whose `status`
        is `CONFIRMED` or `SETTLED`."

        Design: Difficulty/combinatorial_formula/volume_discount_keyed_on_prior_hammer_evaluated_before_clamp
        """
        stage = _online_run(
            [BIG_TICKET_LOT, FOLLOW_ON_LOT],
            [60_000_000, 12_000_000],
            ["2026-08-10T16:00:00Z", "2026-08-10T16:05:00Z"],
        )
        first, second = stage["invoices"]

        assert first["deposit_applied_cents"] == 9_000_000
        assert second["deposit_applied_cents"] == 0
        assert second["total_due_cents"] == 14_047_313

        auction = validate_success(api_client.get_auction(stage["auction"]["id"], OPERATOR))
        assert auction["gross_hammer_cents"] == 72_000_000
        assert auction["sold_lot_count"] == 2


class TestFlatSchedule:
    def test_the_flat_schedule_floors_the_premium_and_ignores_the_online_surcharge(self):
        """A 100,000-cent machine sold online yields 10,000 cents of raw premium, which the flat
        floor lifts to 50,000 with no surcharge added on top.

        PRD 3.8: "Under `LOW_VALUE_FLAT` the computation is short: take ten percent of
        `hammer_price_cents`, rounded half up to whole cents, and use the larger of that figure
        and 50,000 cents. The flat schedule applies no online surcharge, no volume discount and
        — importantly — no ceiling. A 100,000-cent machine therefore yields 10,000 cents of raw
        premium, which the floor lifts to 50,000 cents."
        PRD 3.8: "A read-only settlement preview lets the desk compare the two variants before
        committing. It takes a `variant` and returns, without mutating anything, the
        `invoice_id`, the `variant` requested, `hammer_price_cents`, `buyer_premium_cents`".

        Design: Corner/calculations/low_value_flat_schedule_floors_the_premium_and_skips_the_online_surcharge
        """
        stage = confirmed_invoice(
            bid_amount_cents=100_000,
            lot_overrides={
                "make": "Bobcat",
                "model": "S76",
                "model_year": 2021,
                "serial_number": "BOB-S76-0001",
                "hour_meter_reading": 900,
                "weight_kg": 6_000,
                "reserve_price_cents": 100_000,
            },
            auction_overrides={
                "kind": "TIMED_ONLINE",
                "premium_schedule_code": "LOW_VALUE_FLAT",
                "window_start": "2026-08-10T14:00:00Z",
                "window_end": "2026-08-10T22:00:00Z",
            },
            deposit_cents=100_000,
            deposit_hold_cents=100_000,
        )
        invoice = stage["invoice"]

        assert stage["sale"]["reserve_met"] is True
        assert stage["sale"]["status"] == "CONFIRMED"
        assert invoice["buyer_premium_cents"] == 50_000
        assert invoice["documentation_fee_cents"] == 15_000
        assert invoice["title_transfer_fee_cents"] == 0
        assert invoice["financing_fee_cents"] == 0
        assert invoice["subtotal_cents"] == 165_000
        assert invoice["tax_rate_applied"] == pytest.approx(0.0625, abs=0.00001)
        assert invoice["tax_cents"] == 10_313
        assert invoice["storage_fee_cents"] == 0
        assert invoice["deposit_applied_cents"] == 100_000
        assert invoice["total_due_cents"] == 75_313

        preview = validate_success(
            api_client.get_settlement_preview(
                invoice["id"], SETTLEMENT, params={"variant": "PROVISIONAL"}
            )
        )
        assert preview["buyer_premium_cents"] == 50_000
        assert preview["total_due_cents"] == 75_313


class TestFallbacksAndFeeSpine:
    def test_an_unlisted_country_falls_back_to_tier_c_leverage_and_the_default_tax_rate(self):
        """Nigeria appears in neither tier list nor the tax table, so the paddle gets leverage 2
        on prepay terms and the invoice is taxed at the ten percent default.

        PRD 3.5: "Every other country falls into `TIER_C`."
        PRD 3.5: "`leverage_multiplier` is the deposit leverage granted by the tier: 10 for
        `TIER_A`, 5 for `TIER_B`, and 2 for `TIER_C`."
        PRD 3.8: "`tax_rate_applied` is keyed to the buyer's country: 0.0625 for `US`, 0.13 for
        `CA`, 0.16 for `MX`, 0.19 for `DE`, 0.10 for `AU`, 0.05 for `AE`, 0.20 for `GB`, 0.17
        for `BR`, 0.10 for `JP`, 0.15 for `ZA`, and a default of 0.10 for any country not in
        that table."
        PRD 3.8: "`grace_end_at` is the sale's `hammered_at` advanced by the free-storage
        allowance of the same terms code: 3 days for `PREPAY`, 5 days for `NET_7`, and 10 days
        for `NET_30`."

        Design: Corner/calculations/unlisted_country_uses_the_default_tax_rate_and_tier_c_leverage
        """
        stage = confirmed_invoice(
            bid_amount_cents=2_000_000,
            lot_overrides={
                "make": "Komatsu",
                "model": "PC210",
                "model_year": 2020,
                "serial_number": "KOM-PC210-0001",
                "hour_meter_reading": 3_100,
                "weight_kg": 9_000,
                "reserve_price_cents": 2_000_000,
            },
            bidder_overrides=NIGERIAN_BUYER,
            deposit_cents=1_600_000,
            deposit_hold_cents=1_500_000,
        )
        invoice = stage["invoice"]

        bidder = validate_success(api_client.get_bidder(stage["bidder"]["id"], SETTLEMENT))
        assert bidder["country_tier"] == "TIER_C"
        assert bidder["deposit_held_cents"] == 1_500_000
        assert stage["registration"]["leverage_multiplier"] == 2
        assert stage["registration"]["payment_terms_code"] == "PREPAY"

        assert invoice["is_cross_border"] is True
        assert invoice["buyer_premium_cents"] == 240_000
        assert invoice["documentation_fee_cents"] == 45_000
        assert invoice["subtotal_cents"] == 2_285_000
        assert invoice["tax_rate_applied"] == pytest.approx(0.1000, abs=0.00001)
        assert invoice["tax_cents"] == 228_500
        assert invoice["deposit_applied_cents"] == 1_500_000
        assert invoice["total_due_cents"] == 1_013_500
        assert invoice["grace_end_at"].startswith("2026-08-13T16:00:00")
        assert (
            validate_success(
                api_client.get_bidder_registration(
                    stage["registration"]["id"], SETTLEMENT
                )
            )["bid_cap_cents"]
            == 1_986_500
        )

    def test_the_financing_and_title_fees_are_taxed_because_they_sit_in_the_subtotal(self):
        """Two percent of the hammer plus the title transfer fee enter the subtotal before the
        tax rate is applied, so the same 12,000,000 hammer costs more than the unfinanced one.

        PRD 3.8: "`title_transfer_fee_cents` is 12,500 cents when the lot's `title_required` is
        true and 0 otherwise. `financing_fee_cents` is two percent of the hammer price, rounded
        half up to whole cents, when the registration's `financing_approved` is true, and 0
        otherwise."
        PRD 3.5: "`financing_approved` becomes true when the officer approved a positive credit
        limit and the bidder had set `financing_requested`; otherwise it stays false.
        `payment_terms_code` follows from that outcome and the tier: an approved financing
        arrangement earns `NET_30`; failing that, a `TIER_A` bidder earns `NET_7`; every other
        bidder is `PREPAY`."

        Design: Corner/calculations/financing_and_title_fees_enter_the_subtotal_before_the_tax_base
        """
        stage = confirmed_invoice(
            lot_overrides={"serial_number": "CAT-D8T-0001", "title_required": True},
            financing_requested=True,
            approved_credit_limit_cents=5_000_000,
        )
        registration, invoice = stage["registration"], stage["invoice"]

        assert registration["financing_approved"] is True
        assert registration["payment_terms_code"] == "NET_30"
        assert registration["bid_cap_cents"] == 20_000_000

        assert invoice["buyer_premium_cents"] == 1_160_000
        assert invoice["documentation_fee_cents"] == 15_000
        assert invoice["title_transfer_fee_cents"] == 12_500
        assert invoice["financing_fee_cents"] == 240_000
        assert invoice["subtotal_cents"] == 13_427_500
        assert invoice["tax_cents"] == 839_219
        assert invoice["deposit_applied_cents"] == 1_500_000
        assert invoice["total_due_cents"] == 12_766_719
        assert invoice["grace_end_at"].startswith("2026-08-20T16:00:00")
        assert (
            validate_success(
                api_client.get_bidder_registration(registration["id"], SETTLEMENT)
            )["bid_cap_cents"]
            == 7_233_281
        )
