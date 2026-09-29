"""Settlement arithmetic: per-day-line rounding, the loss waterfall and ledger conservation."""

from __future__ import annotations

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    OwnerSpec,
    api_client,
    assert_batch_conservation,
    assert_ledger_conservation,
    create_batch,
    day_start,
    ingest_activity,
    list_reserve_ledger,
    make_portfolio_controller_headers,
    onboard_standard_merchant,
    read_batch,
    read_merchant,
    read_reserve_account,
    reverse_batch,
    set_clock,
)

CLEAN_LINE = {
    "txn_count": 100,
    "volume_cents": 100_050,
    "distinct_card_count": 98,
    "decline_count": 1,
    "cross_border_count": 0,
    "refund_cents": 0,
    "unique_bin_count": 55,
    "chargeback_count": 0,
    "chargeback_amount_cents": 0,
}


def _merchant_with_three_awkward_day_lines(api):
    onboarded = onboard_standard_merchant(
        api,
        clock="2026-07-01T00:00:00Z",
        legal_business_name="Pinecrest Supply LLC",
        average_ticket_cents=1_000,
        owners=[OwnerSpec(ownership_pct=90.00, full_name="Ivo Bell")],
    )
    for business_date in ("2026-07-01", "2026-07-02", "2026-07-03"):
        set_clock(api, day_start(business_date))
        ingest_activity(api, onboarded.merchant_id, business_date, **CLEAN_LINE)
    return onboarded


class TestReserveHoldRoundsPerDayLine:
    """Three 100050-cent lines at 500 bps: 5003 three times, not one rounding of the total."""

    def test_the_hold_is_the_sum_of_per_line_roundings(self):
        """Each line rounds to 5003, so the hold is 15009 and never the 15008 of one rounding.

        PRD 3.9: "For each day line, multiply that line's `volume_cents` by the reserve
        percentage, divide by 10000 and round half up to whole cents; then add those per-line
        integers together. Rounding per line and then summing is the rule; summing the volumes
        and rounding once is explicitly not, and the two differ whenever two or more lines round
        up."

        Design: Difficulty/combinatorial_formula/settlement_hold_rounds_per_day_line_not_per_period
        """
        api = api_client
        onboarded = _merchant_with_three_awkward_day_lines(api)

        batch = create_batch(api, onboarded.merchant_id, "2026-07-01", "2026-07-03", 300_150)

        assert batch["day_line_count"] == 3
        assert batch["reserve_hold_cents"] == 15_009
        assert batch["reserve_hold_cents"] != 15_008
        assert batch["loss_offset_from_settlement_cents"] == 0
        assert batch["reserve_offset_cents"] == 0
        assert batch["uncovered_loss_cents"] == 0
        assert batch["net_payout_cents"] == 285_141
        assert_batch_conservation(batch)

    def test_the_per_line_hold_flows_into_the_reserve_account_and_the_merchant_mirrors(self):
        """15009 cents accrue, and the payout is scheduled for the day after the period ends.

        PRD 3.9: "A `NORMAL` merchant's batch is created in `payout_state` `SCHEDULED` with
        `scheduled_payout_date` set to `period_end_date` plus 1 day."

        Design: Difficulty/combinatorial_formula/settlement_hold_rounds_per_day_line_not_per_period
        """
        api = api_client
        onboarded = _merchant_with_three_awkward_day_lines(api)

        created = create_batch(api, onboarded.merchant_id, "2026-07-01", "2026-07-03", 300_150)

        batch = read_batch(api, created["id"])
        assert batch["payout_state"] == "SCHEDULED"
        assert batch["scheduled_payout_date"] == "2026-07-04"

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["total_accrued_cents"] == 15_009
        assert account["held_balance_cents"] == 15_009
        assert_ledger_conservation(account)

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["pending_payout_cents"] == 285_141
        assert merchant["reserve_balance_cents"] == 15_009


class TestLossWaterfallOverflow:
    """Losses larger than the whole period drain settlement, then reserve, then the facilitator."""

    def _overflowed_batch(self, api):
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-07-01T00:00:00Z",
            legal_business_name="Saltmarsh Studio LLC",
            owners=[OwnerSpec(full_name="Mira Chase")],
        )
        ingest_activity(
            api,
            onboarded.merchant_id,
            "2026-07-01",
            txn_count=10,
            volume_cents=100_000,
            distinct_card_count=10,
            decline_count=0,
            unique_bin_count=9,
            chargeback_count=2,
            chargeback_amount_cents=120_000,
            chargeback_network="VISA",
        )
        batch = create_batch(api, onboarded.merchant_id, "2026-07-01", "2026-07-01", 100_000)
        return onboarded, batch

    def test_the_three_buckets_drain_in_order_and_the_remainder_is_uncovered(self):
        """5000 held off the top, 95000 from settlement, 5000 from reserve, 20000 uncovered.

        PRD 3.9: "The amount available to fund losses is the greater of 0 and
        `gross_volume_cents` less `reserve_hold_cents` - the reserve is taken off the top and is
        never reachable by the settlement bucket."

        Design: Difficulty/compensating_invariant/reserve_ledger_conservation_survives_a_loss_offset_overflow
        """
        api = api_client
        _, batch = self._overflowed_batch(api)

        assert batch["reserve_hold_cents"] == 5_000
        assert batch["loss_offset_from_settlement_cents"] == 95_000
        assert batch["reserve_offset_cents"] == 5_000
        assert batch["uncovered_loss_cents"] == 20_000
        assert batch["net_payout_cents"] == 0
        assert batch["payout_state"] == "SCHEDULED"
        assert_batch_conservation(batch)

    def test_conservation_still_holds_after_the_hold_and_the_offset_are_appended(self):
        """Two entries land, the reserve empties to zero and never goes negative.

        PRD 2.12: "The **conservation invariant** must therefore hold after every append:
        `total_accrued_cents` equals `held_balance_cents` plus `released_to_date_cents` plus
        `offset_to_date_cents`."

        Design: Difficulty/compensating_invariant/reserve_ledger_conservation_survives_a_loss_offset_overflow
        """
        api = api_client
        onboarded, batch = self._overflowed_batch(api)

        entries = get_success_data(
            api.list_batch_ledger_entries(batch["id"], make_portfolio_controller_headers())
        )
        assert len(entries) == 2
        by_type = {entry["entry_type"]: entry for entry in entries}
        assert set(by_type) == {"HOLD", "OFFSET_LOSS"}
        assert by_type["HOLD"]["amount_cents"] == 5_000
        assert by_type["OFFSET_LOSS"]["amount_cents"] == 5_000

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["total_accrued_cents"] == 5_000
        assert account["offset_to_date_cents"] == 5_000
        assert account["released_to_date_cents"] == 0
        assert account["held_balance_cents"] == 0
        assert account["state"] == "ACCRUING"
        assert_ledger_conservation(account)

        assert read_merchant(api, onboarded.merchant_id)["pending_payout_cents"] == 0


class TestBatchReversalRestoresThePayablePosition:
    """A compensating reversal returns the merchant to its exact pre-batch position."""

    def _reversed_batch(self, api):
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-07-01T00:00:00Z",
            legal_business_name="Windrow Ceramics LLC",
            owners=[OwnerSpec(full_name="Owen Reyes")],
        )
        ingest_activity(
            api,
            onboarded.merchant_id,
            "2026-07-01",
            txn_count=100,
            volume_cents=1_000_000,
            distinct_card_count=96,
            decline_count=1,
            unique_bin_count=60,
            chargeback_count=1,
            chargeback_amount_cents=200_000,
            chargeback_network="MASTERCARD",
        )
        batch = create_batch(api, onboarded.merchant_id, "2026-07-01", "2026-07-01", 1_000_000)
        assert batch["reserve_hold_cents"] == 50_000
        assert batch["loss_offset_from_settlement_cents"] == 200_000
        assert batch["net_payout_cents"] == 750_000
        reversed_batch = reverse_batch(api, batch["id"], "FUNDING_ERROR")
        return onboarded, reversed_batch

    def test_pending_payout_returns_to_zero_and_the_loss_is_recorded(self):
        """The 750000 payout leaves the pending set and 200000 lands in lifetime_reversed_cents.

        PRD 3.9: "`lifetime_reversed_cents` is the merchant's running record of value unwound by
        reversal: each reversal adds this batch's `uncovered_loss_cents`, `reserve_offset_cents`
        and `loss_offset_from_settlement_cents` to it."

        Design: Difficulty/compensating_invariant/batch_reversal_restores_pending_payout_and_reserve_balance
        """
        api = api_client
        onboarded, reversed_batch = self._reversed_batch(api)

        assert reversed_batch["payout_state"] == "REVERSED"
        assert reversed_batch["reversal_reason_code"] == "FUNDING_ERROR"

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["pending_payout_cents"] == 0
        assert merchant["lifetime_reversed_cents"] == 200_000

    def test_the_hold_is_unwound_by_a_compensating_release_rather_than_deleted(self):
        """A RELEASE entry with reason BATCH_REVERSAL_RELEASE joins the original HOLD.

        PRD 3.9: "Two compensating ledger entries restore the account: a `RELEASE` entry with
        `reason_code` `BATCH_REVERSAL_RELEASE` for `amount_cents` equal to this batch's
        `reserve_hold_cents`, with `settlement_batch_id` naming this batch, `effective_date` the
        logical clock date and both tranche dates null - skipped when the batch withheld
        nothing"

        Design: Difficulty/compensating_invariant/batch_reversal_restores_pending_payout_and_reserve_balance
        """
        api = api_client
        onboarded, _ = self._reversed_batch(api)

        entries = list_reserve_ledger(api, onboarded.reserve_account_id)
        assert len(entries) == 2
        by_type = {entry["entry_type"]: entry for entry in entries}
        assert set(by_type) == {"HOLD", "RELEASE"}
        assert by_type["HOLD"]["amount_cents"] == 50_000
        assert by_type["RELEASE"]["amount_cents"] == 50_000
        assert by_type["RELEASE"]["reason_code"] == "BATCH_REVERSAL_RELEASE"
        assert by_type["RELEASE"]["tranche_start_date"] is None
        assert by_type["RELEASE"]["tranche_end_date"] is None

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["total_accrued_cents"] == 50_000
        assert account["released_to_date_cents"] == 50_000
        assert account["offset_to_date_cents"] == 0
        assert account["held_balance_cents"] == 0
        assert_ledger_conservation(account)
