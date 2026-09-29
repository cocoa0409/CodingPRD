"""Multi-stage formulas must compose in the documented order."""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as fac
from test_helpers.assertions import assert_ledger_sequence, assert_total_count
from test_helpers.constants import (
    ENTRY_ACCRUAL,
    ENTRY_PAYOUT_DEBIT,
    ENTRY_PAYOUT_FEE,
    EVENT_ACCRUED,
    PAYOUT_METHOD_BANK_TRANSFER,
    PAYOUT_METHOD_CHECK,
    PAYOUT_METHOD_INSTANT_DEBIT,
    PAYOUT_PAID,
    PAYOUT_STATE_IN_FLIGHT,
    RATING_YELLOW,
    STATEMENT_PAID,
)
from test_helpers.fixtures import (
    ads_product,
    august_period,
    close,
    content_item,
    finalize,
    july_period,
    ledger_rows,
    payable_creator,
    post_event,
    refresh_creator,
    statement_for,
    tips_product,
)
from test_helpers.test_users import FINANCE, REVIEWER


def _paid_out_channel(api, gross_amount_cents, payout_method):
    """Take one channel through a full paid payout so loyalty accrues."""
    creator, _profile = payable_creator(api, payout_method=payout_method)
    product = tips_product(api)
    period = july_period(api)
    post_event(
        api, creator["id"], product["id"], gross_amount_cents=gross_amount_cents
    )
    close(api, period["id"])
    statement = finalize(api, statement_for(api, creator["id"], period["id"])["id"])
    payout = validate_success(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE), 201
    )
    get_success_data(api.submit_payout(payout["id"], FINANCE))
    settled = get_success_data(
        api.record_settlement(
            payout["id"], fac.settlement_payload("SUCCEEDED"), FINANCE
        )
    )
    return creator, statement, payout, settled


def test_a_check_payout_settles_and_lifts_the_channel_into_a_loyalty_tier(api):
    """A check disbursement of 1000250 cents costs 250 and pays 1000000.

    The flat 500-cent check fee is scaled by the 5000-basis-point tier that a
    payable above 500000 cents earns, and settling the payout records the paid
    amount as lifetime earnings.

    Design: Difficulty/combinatorial_formula/revenue_share_cap_before_suitability_multiplier_mode_a
    """
    creator, statement, payout, settled = _paid_out_channel(
        api, 2000500, PAYOUT_METHOD_CHECK
    )

    assert payout["method"] == PAYOUT_METHOD_CHECK
    assert payout["payable_before_fee_cents"] == 1000250
    assert payout["fee_cents"] == 250
    assert payout["amount_cents"] == 1000000
    assert settled["state"] == PAYOUT_PAID
    assert validate_success(api.get_statement(statement["id"], FINANCE))["status"] == (
        STATEMENT_PAID
    )
    assert refresh_creator(api, creator["id"])["lifetime_paid_cents"] == 1000000


def test_the_nine_thousand_cap_binds_before_the_suitability_multiplier(api):
    """The loyalty bonus is capped first and only then discounted for risk.

    A base share of 8800 plus a 400-basis-point loyalty bonus caps at 9000 and
    a limited rating multiplies that by 6000 basis points to 5400, so a gross
    of 1234 cents pays 666 rather than the 681 an uncapped 9200 would give.

    Design: Difficulty/combinatorial_formula/revenue_share_cap_before_suitability_multiplier_mode_a
    """
    creator, _statement, _payout, _settled = _paid_out_channel(
        api, 2000500, PAYOUT_METHOD_CHECK
    )
    product = ads_product(api, creator_share_bps=8800, platform_fee_bps=1200)
    item = content_item(api, creator["id"])
    rated = get_success_data(
        api.rate_content_item(item["id"], fac.rate_payload(RATING_YELLOW), REVIEWER)
    )
    assert rated["suitability_rating"] == RATING_YELLOW
    august_period(api)

    event = validate_success(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"],
                product["id"],
                content_item_id=item["id"],
                gross_amount_cents=1234,
                occurred_at="2026-08-01T00:00:00Z",
            ),
            FINANCE,
        ),
        201,
    )

    assert event["effective_share_bps"] == 5400
    assert event["effective_share_bps"] != 5520
    assert event["creator_share_cents"] == 666
    assert event["creator_share_cents"] != 681
    assert event["status"] == EVENT_ACCRUED
    assert event["terms_version_at_accrual"] == 1
    assert event["suitability_rating_at_accrual"] == RATING_YELLOW


def test_the_percentage_and_tier_components_each_round_up_separately(api):
    """An instant debit of 60340 cents costs 755, not the 754 of one rounding.

    The 150-basis-point percentage rounds up to 906 before the flat 100 is
    added, and the resulting 1006 is scaled by the 7500-basis-point tier and
    rounded up again to 755.

    Design: Difficulty/combinatorial_formula/payout_fee_double_ceiling_nesting_order_mode_b
    """
    creator, _profile = payable_creator(api, payout_method=PAYOUT_METHOD_INSTANT_DEBIT)
    product = tips_product(api)
    period = july_period(api)
    post_event(api, creator["id"], product["id"], gross_amount_cents=120680)
    close(api, period["id"])
    finalize(api, statement_for(api, creator["id"], period["id"])["id"])

    payout = validate_success(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE), 201
    )
    assert payout["payable_before_fee_cents"] == 60340
    assert payout["fee_cents"] == 755
    assert payout["fee_cents"] != 754
    assert payout["amount_cents"] == 59585


def test_a_payout_debit_and_its_fee_are_two_separate_ledger_entries(api):
    """Creating the disbursement empties the ledger in two ordered entries.

    The debit of 59585 is followed by the fee of 755, together cancelling the
    60340 accrual, and the channel enters the in-flight disbursement state.

    Design: Difficulty/combinatorial_formula/payout_fee_double_ceiling_nesting_order_mode_b
    """
    creator, _profile = payable_creator(api, payout_method=PAYOUT_METHOD_INSTANT_DEBIT)
    product = tips_product(api)
    period = july_period(api)
    post_event(api, creator["id"], product["id"], gross_amount_cents=120680)
    close(api, period["id"])
    finalize(api, statement_for(api, creator["id"], period["id"])["id"])
    validate_success(api.create_payout(fac.payout_payload(creator["id"]), FINANCE), 201)

    rows = assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 3)
    assert_ledger_sequence(
        rows,
        [
            (ENTRY_ACCRUAL, 60340),
            (ENTRY_PAYOUT_DEBIT, -59585),
            (ENTRY_PAYOUT_FEE, -755),
        ],
    )
    after = refresh_creator(api, creator["id"])
    assert after["ledger_balance_cents"] == 0
    assert after["payout_state"] == PAYOUT_STATE_IN_FLIGHT


@pytest.mark.parametrize(
    "gross_amount_cents,payable,fee,amount",
    [(99998, 49999, 200, 49799), (100000, 50000, 150, 49850)],
)
def test_the_volume_tier_reads_the_payable_before_the_fee(
    api, gross_amount_cents, payable, fee, amount
):
    """One cent of payable moves the tier from 10000 to 7500 basis points.

    A payable of 49999 keeps the full 200-cent bank fee while a payable of
    exactly 50000 scales it down to 150, which is only possible if the tier is
    keyed on the payable before the fee has been subtracted.

    Design: Difficulty/combinatorial_formula/payout_volume_tier_keyed_on_pre_fee_payable_mode_c
    """
    creator, _profile = payable_creator(api, payout_method=PAYOUT_METHOD_BANK_TRANSFER)
    product = tips_product(api)
    period = july_period(api)
    post_event(
        api, creator["id"], product["id"], gross_amount_cents=gross_amount_cents
    )
    close(api, period["id"])
    finalize(api, statement_for(api, creator["id"], period["id"])["id"])

    payout = validate_success(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE), 201
    )
    assert payout["payable_before_fee_cents"] == payable
    assert payout["fee_cents"] == fee
    assert payout["amount_cents"] == amount
    assert ledger_rows(api, creator["id"])[-1]["amount_cents"] == -fee
