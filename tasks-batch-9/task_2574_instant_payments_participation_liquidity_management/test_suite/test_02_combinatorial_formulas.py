"""Formulas whose answer depends on combining several inputs in a pinned order.

The origination fraud score sums four independent terms and only then applies the
segment multiplier and the ceiling, so the same four terms route a corporate send
into a hold and a consumer send straight through.

The intraday liquidity access fee is the other combinatorial site: each settled
transfer is rounded on its own before the sum is taken, and the volume rebate is
then discarded down to whole cents, so the order of the steps is the answer.
"""

from test_helpers import (
    accept_transfer,
    alpha_scenario,
    assert_account_position,
    assert_ledger_entry,
    assert_transfer_dimensions,
    cutoff_cycle,
    list_ledger_entries,
    read_account,
    read_transfer,
    send_from_alpha,
    set_clock,
    settle_transfer,
)

CONSUMER_POLICY_WIDE_COUNT = {
    "segment": "CONSUMER",
    "per_transaction_limit_cents": 250_000_000,
    "daily_aggregate_limit_cents": 500_000_000,
    "rolling_window_count_limit": 20,
    "rolling_window_amount_limit_cents": 400_000_000,
    "effective_from": "2026-08-01T00:00:00Z",
}

CONSUMER_POLICY = dict(CONSUMER_POLICY_WIDE_COUNT, rolling_window_count_limit=5)


def _four_small_sends(api, scenario):
    """Four 300,000-cent sends at 13:00, 13:05, 13:10 and 13:15, all left initiated."""
    sends = []
    for instant in ("2026-08-03T13:00:00Z", "2026-08-03T13:05:00Z",
                    "2026-08-03T13:10:00Z", "2026-08-03T13:15:00Z"):
        set_clock(api, instant)
        sends.append(send_from_alpha(api, scenario, 300_000))
    set_clock(api, "2026-08-03T13:20:00Z")
    return sends


def test_four_terms_are_summed_then_scaled_by_the_corporate_multiplier(api):
    """Baseline, capped amount band, velocity burst and new beneficiary combine to 62.

    PRD 3.4: "Those four terms are summed into a raw subtotal, the subtotal is
    multiplied by the customer's segment multiplier — 1.00 for `CONSUMER`, 1.05 for
    `SMALL_BUSINESS`, 1.10 for `CORPORATE` and 1.25 for `HIGH_RISK` — the product is
    rounded half up to a whole number, and only then is the result capped at 100."

    Design: Difficulty/combinatorial_formula/fraud_score_multi_term_combination_with_segment_multiplier
    """
    scenario = alpha_scenario(api)
    sends = _four_small_sends(api, scenario)

    assert sends[0]["fraud_score"] == 42
    assert sends[3]["fraud_score"] == 42

    scored = send_from_alpha(api, scenario, 250_000_000)

    assert scored["fraud_score"] == 62
    assert_transfer_dimensions(scored, "FRAUD_HOLD", "NONE")
    assert scored["fraud_reason_codes"] == ["AMOUNT_BAND", "VELOCITY_BURST", "NEW_BENEFICIARY"]

    account = read_account(api, scenario.alpha.account_id)
    assert_account_position(
        account,
        current_balance_cents=1_200_000_000,
        reserved_cents=251_200_000,
        available_cents=948_800_000,
    )


def test_same_four_terms_under_the_consumer_multiplier_stay_below_the_hold(api):
    """Only the multiplier changes, and the identical term sum routes differently.

    PRD 3.4: "A score below 60 leaves the transfer in `INITIATED`, and it proceeds to
    the ordinary clearing path."

    PRD 3.4: "Those four terms are summed into a raw subtotal, the subtotal is
    multiplied by the customer's segment multiplier — 1.00 for `CONSUMER`, 1.05 for
    `SMALL_BUSINESS`, 1.10 for `CORPORATE` and 1.25 for `HIGH_RISK` — the product is
    rounded half up to a whole number, and only then is the result capped at 100."

    Design: Difficulty/combinatorial_formula/fraud_score_multi_term_combination_with_segment_multiplier
    """
    scenario = alpha_scenario(
        api, policy=CONSUMER_POLICY, customer_segment="CONSUMER"
    )
    sends = _four_small_sends(api, scenario)
    assert sends[0]["fraud_score"] == 38

    scored = send_from_alpha(api, scenario, 250_000_000)

    assert scored["fraud_score"] == 56
    assert_transfer_dimensions(scored, "INITIATED", "NONE")
    assert scored["fraud_reason_codes"] == ["AMOUNT_BAND", "VELOCITY_BURST", "NEW_BENEFICIARY"]
    assert read_transfer(api, scored["id"])["fraud_score"] == 56


def test_access_fee_rounds_each_settled_transfer_before_summing(api):
    """Three settled amounts of 1,500 / 2,500 / 3,500 cents cost 9 cents, not 8.

    PRD 3.10: "The rounding order is pinned and is not interchangeable with the
    obvious alternative: three settled amounts of 1,500, 2,500 and 3,500 cents
    produce per-transfer fees of 2, 3 and 4 cents for a gross of 9 cents, whereas
    summing the amounts first and rounding once would give 8 cents."

    Design: Difficulty/combinatorial_formula/intraday_access_fee_rounds_per_transfer_then_sums
    """
    scenario = alpha_scenario(api)
    settled = []
    for amount in (1_500, 2_500, 3_500):
        transfer = send_from_alpha(api, scenario, amount)
        assert transfer["fraud_score"] == 35
        settled.append(transfer)
    for transfer in settled:
        accept_transfer(api, transfer["id"])
    for transfer in settled:
        settle_transfer(api, transfer["id"])

    set_clock(api, "2026-08-03T13:30:00Z")
    cycle = cutoff_cycle(api, scenario.cycle_id)

    assert cycle["assessed_fee_total_cents"] == 9
    assert cycle["settled_transfer_count"] == 3
    assert cycle["status"] == "CUTOFF"

    fee_entries = list_ledger_entries(
        api, scenario.alpha.account_id, {"entry_type": "FEE_DEBIT"}
    )
    assert len(fee_entries) == 1
    assert_ledger_entry(
        fee_entries[0],
        entry_type="FEE_DEBIT",
        amount_cents=-9,
        balance_after_cents=1_199_992_491,
        sequence_no=4,
        business_date="2026-08-03",
    )
    assert read_account(api, scenario.alpha.account_id)["current_balance_cents"] == 1_199_992_491


def test_volume_rebate_is_one_tenth_of_the_gross_fee_with_the_fraction_discarded(api):
    """Ten settled transfers earn a gross of 25 cents, a rebate of 2 and a net of 23.

    PRD 3.10: "A volume rebate then applies: when the participant settled at least 10
    transfers on that date, the rebate is one tenth of the gross fee with any fraction
    discarded, and otherwise the rebate is zero."

    Design: Difficulty/combinatorial_formula/intraday_access_fee_rounds_per_transfer_then_sums
    """
    scenario = alpha_scenario(
        api, policy=CONSUMER_POLICY_WIDE_COUNT, customer_segment="CONSUMER"
    )
    transfers = [send_from_alpha(api, scenario, 1_500) for _ in range(5)]
    transfers += [send_from_alpha(api, scenario, 2_500) for _ in range(5)]
    for transfer in transfers:
        accept_transfer(api, transfer["id"])
    for transfer in transfers:
        settle_transfer(api, transfer["id"])

    set_clock(api, "2026-08-03T13:30:00Z")
    cycle = cutoff_cycle(api, scenario.cycle_id)

    assert cycle["settled_transfer_count"] == 10
    assert cycle["assessed_fee_total_cents"] == 23

    fee_entries = list_ledger_entries(
        api, scenario.alpha.account_id, {"entry_type": "FEE_DEBIT"}
    )
    assert len(fee_entries) == 1
    assert_ledger_entry(
        fee_entries[0],
        entry_type="FEE_DEBIT",
        amount_cents=-23,
        balance_after_cents=1_199_979_977,
        sequence_no=11,
        business_date="2026-08-03",
    )
