"""Portfolio loss forecasting: which ratio variant feeds which consumer, and the frozen tier."""

from __future__ import annotations

from test_helpers import (
    OwnerSpec,
    api_client,
    create_batch,
    create_forecast,
    ingest_activity,
    onboard_standard_merchant,
    read_merchant,
    run_monitoring,
    set_clock,
)


def _one_merchant_book_at_mid_july(api, *, name: str, owner_pct: float, network: str):
    """One ACTIVE merchant at 500 bps ROLLING, one settled day, clock at 2026-07-15."""
    onboarded = onboard_standard_merchant(
        api,
        clock="2026-07-01T00:00:00Z",
        legal_business_name=name,
        mcc_code="5999",
        average_ticket_cents=10_000,
        owners=[OwnerSpec(ownership_pct=owner_pct, full_name="Ann Ito")],
    )
    ingest_activity(
        api,
        onboarded.merchant_id,
        "2026-07-01",
        txn_count=500,
        volume_cents=5_000_000,
        distinct_card_count=480,
        decline_count=4,
        unique_bin_count=210,
        chargeback_count=3,
        chargeback_amount_cents=60_000,
        chargeback_network=network,
    )
    batch = create_batch(api, onboarded.merchant_id, "2026-07-01", "2026-07-01", 5_000_000)
    set_clock(api, "2026-07-15T00:00:00Z")
    return onboarded, batch


class TestTheTwoChargebackRatioVariantsServeDifferentConsumers:
    """60 bps count-based keeps the merchant clean while 120 bps amount-based prices the loss."""

    def test_the_sweep_reads_only_the_count_based_variant_and_raises_nothing(self):
        """3 chargebacks in 500 transactions is 60 bps, below the early-warning line.

        PRD 3.6: "This is the network-standard measure, and it is the **only** variant that may
        restrict an account - the chargeback-threshold detector, the remediation month evaluation
        and every `account_state` cascade read it and nothing else."

        Design: Difficulty/dual_variant_calc/chargeback_ratio_count_variant_gates_amount_variant_forecasts
        """
        api = api_client
        onboarded, _ = _one_merchant_book_at_mid_july(
            api, name="Harbor Provisions LLC", owner_pct=80.00, network="VISA"
        )

        alerts = run_monitoring(api, "2026-07-15")
        assert alerts == []

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["rolling_chargeback_ratio_bps"] == 60
        assert merchant["amount_based_chargeback_ratio_bps"] == 120
        assert merchant["open_alert_count"] == 0
        assert merchant["account_state"] == "ACTIVE"

    def test_the_forecast_reads_only_the_amount_based_variant_when_it_picks_the_tier(self):
        """120 bps lands in the 900 bps default tier, not the 100 bps tier the count would give.

        PRD 3.13: "The probability of default in basis points is selected from the
        **amount-based** ratio variant, and only that variant: 100 basis points when
        `amount_based_chargeback_ratio_bps` is below 65; 300 when it is 65 or more but below 90;
        900 when it is 90 or more but below 180; and 2000 when it is 180 or more."

        Design: Difficulty/dual_variant_calc/chargeback_ratio_count_variant_gates_amount_variant_forecasts
        """
        api = api_client
        _, batch = _one_merchant_book_at_mid_july(
            api, name="Harbor Provisions LLC", owner_pct=80.00, network="VISA"
        )
        assert batch["net_payout_cents"] == 4_690_000

        run_monitoring(api, "2026-07-15")
        forecast = create_forecast(api, "2026-07-15", "EXPECTED_LOSS")

        assert forecast["unpaid_exposure_cents"] == 4_690_000
        assert forecast["gross_expected_loss_cents"] == 253_260
        assert forecast["gross_expected_loss_cents"] != 28_140
        assert forecast["total_reserve_held_cents"] == 250_000
        assert forecast["net_expected_loss_cents"] == 3_260


class TestTheAdequacyTierIsFrozenBeforeTheUplift:
    """The tier that sizes the additional reserve is read once, from the pre-uplift ratio."""

    def test_expected_loss_calls_a_quarter_of_the_gap_at_a_9871_bps_ratio(self):
        """9871 bps sits in the partial band, so only 815 of the 3260 gap is demanded.

        PRD 3.13: "`required_additional_reserve_cents` is 0 when `reserve_adequacy_ratio_bps` is
        10000 basis points or more - the book is fully covered; otherwise it is
        `coverage_gap_cents` multiplied by 2500, divided by 10000, rounded half up when
        `reserve_adequacy_ratio_bps` is 7500 or more - a partial call for a quarter of the gap;
        otherwise it is the whole `coverage_gap_cents`."

        Design: Difficulty/combinatorial_formula/forecast_adequacy_tier_frozen_before_uplift
        """
        api = api_client
        _one_merchant_book_at_mid_july(
            api, name="Foxglove Media LLC", owner_pct=85.00, network="MASTERCARD"
        )

        forecast = create_forecast(api, "2026-07-15", "EXPECTED_LOSS")

        assert forecast["merchant_count"] == 1
        assert forecast["gross_expected_loss_cents"] == 253_260
        assert forecast["coverage_gap_cents"] == 3_260
        assert forecast["reserve_adequacy_ratio_bps"] == 9_871
        assert forecast["required_additional_reserve_cents"] == 815
        assert forecast["projected_adequacy_ratio_bps"] == 9_903

    def test_stressed_multiplies_the_default_probability_and_calls_the_whole_gap(self):
        """At 3949 bps adequacy the whole 383150 gap is demanded on identical portfolio data.

        PRD 3.13: "Under `STRESSED`, and only under `STRESSED`, the resulting figure is then
        multiplied by `stress_multiplier_bps`, divided by 10000, rounded half up, and capped at
        10000 basis points - a certainty of default."

        Design: Difficulty/combinatorial_formula/forecast_adequacy_tier_frozen_before_uplift
        """
        api = api_client
        _one_merchant_book_at_mid_july(
            api, name="Foxglove Media LLC", owner_pct=85.00, network="MASTERCARD"
        )

        forecast = create_forecast(api, "2026-07-15", "STRESSED", stress_multiplier_bps=25_000)

        assert forecast["gross_expected_loss_cents"] == 633_150
        assert forecast["net_expected_loss_cents"] == 383_150
        assert forecast["coverage_gap_cents"] == 383_150
        assert forecast["reserve_adequacy_ratio_bps"] == 3_949
        assert forecast["required_additional_reserve_cents"] == 383_150

    def test_the_tier_is_never_re_selected_from_the_projected_ratio(self):
        """The stressed run reports a projected 10000 bps while still calling the full gap.

        PRD 3.13: "Re-selecting the tier from this projected ratio, or iterating the two steps to
        a fixed point, is explicitly wrong."

        Design: Difficulty/combinatorial_formula/forecast_adequacy_tier_frozen_before_uplift
        """
        api = api_client
        _one_merchant_book_at_mid_july(
            api, name="Foxglove Media LLC", owner_pct=85.00, network="MASTERCARD"
        )

        base = create_forecast(api, "2026-07-15", "EXPECTED_LOSS")
        stressed = create_forecast(api, "2026-07-15", "STRESSED", stress_multiplier_bps=25_000)

        assert stressed["projected_adequacy_ratio_bps"] == 10_000
        assert stressed["required_additional_reserve_cents"] == 383_150
        assert base["projected_adequacy_ratio_bps"] == 9_903
        assert base["required_additional_reserve_cents"] == 815
        # The two methods disagree on the tier itself, over the same portfolio rows.
        assert base["reserve_adequacy_ratio_bps"] != stressed["reserve_adequacy_ratio_bps"]
