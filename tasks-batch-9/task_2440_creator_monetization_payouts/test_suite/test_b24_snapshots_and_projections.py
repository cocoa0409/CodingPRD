"""Snapshotted pricing, the three-term balance and the volume tier boundary."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers.constants import (
    ENTRY_ACCRUAL,
    ENTRY_ACCRUAL_REVERSAL,
    EVENT_REVERSED,
    PAYOUT_METHOD_BANK_TRANSFER,
    PAYOUT_METHOD_CHECK,
    PAYOUT_PENDING,
    PAYOUT_STATE_HOLD,
    PRODUCT_TYPE_TIPS,
    RATING_RED,
    RATING_SOURCE_MANUAL,
)
from test_helpers.fixtures import (
    ads_product,
    august_period,
    content_item,
    eligible_creator,
    ledger_rows,
    payable_creator,
    post_event,
    refresh_creator,
    statement_for,
    subs_product,
    tips_product,
)
from test_helpers.test_users import ADMIN, FINANCE, REVIEWER


def _finalized_subscription_payable(api, gross_amount_cents=1000000):
    """A verified channel whose August statement is finalized and unpaid."""
    creator, _profile = payable_creator(api, display_name="Ada Ads")
    period = august_period(api)
    product = subs_product(api, name="Memberships")
    post_event(
        api,
        creator["id"],
        product["id"],
        gross_amount_cents=gross_amount_cents,
        occurred_at="2026-08-05T00:00:00Z",
    )
    get_success_data(api.close_period(period["id"], FINANCE))
    statement = statement_for(api, creator["id"], period["id"])
    get_success_data(api.finalize_statement(statement["id"], FINANCE))
    return creator, period, statement


def test_a_later_change_of_rail_never_reprices_an_existing_disbursement(api):
    """The stored rail and fee stay put while the channel's rail moves on.

    Design: Corner/entities/payout_method_and_fee_are_snapshots_not_live_reads
    """
    creator, _period, _statement = _finalized_subscription_payable(api)
    payout = get_success_data(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE)
    )

    switched = validate_success(
        api.set_payout_settings(
            creator["id"],
            fac.payout_settings_payload(payout_method=PAYOUT_METHOD_CHECK),
            FINANCE,
        )
    )
    assert switched["payout_method"] == PAYOUT_METHOD_CHECK

    reloaded = validate_success(api.get_payout(payout["id"], FINANCE))
    assert reloaded["method"] == PAYOUT_METHOD_BANK_TRANSFER
    assert reloaded["payable_before_fee_cents"] == 700000
    assert reloaded["fee_cents"] == 100
    assert reloaded["amount_cents"] == 699900
    assert reloaded["statement_count"] == 1
    assert reloaded["state"] == PAYOUT_PENDING


def test_the_spendable_balance_adds_two_terms_and_subtracts_a_third(api):
    """Statement money plus fund money less held money, recomputed on each read.

    Design: Corner/entities/creator_available_balance_is_three_term_projection
    """
    creator, _profile = payable_creator(api, display_name="Ada Ads")
    period = august_period(api)
    fund = get_success_data(
        api.create_fund(
            fac.fund_payload(
                period["id"], name="August Boost", total_pool_cents=20000
            ),
            ADMIN,
        )
    )
    allocated = get_success_data(
        api.allocate_fund(fund["id"], fac.allocate_payload(fund["version"]), FINANCE)
    )
    get_success_data(api.disburse_fund(allocated["id"], FINANCE))
    product = subs_product(api, name="Memberships")
    post_event(
        api,
        creator["id"],
        product["id"],
        gross_amount_cents=1000000,
        occurred_at="2026-08-05T00:00:00Z",
    )
    get_success_data(api.close_period(period["id"], FINANCE))
    statement = statement_for(api, creator["id"], period["id"])
    get_success_data(api.finalize_statement(statement["id"], FINANCE))

    before = validate_success(api.get_creator(creator["id"], FINANCE))
    assert before["statement_payable_cents"] == 700000
    assert before["fund_credit_balance_cents"] == 20000
    assert before["held_cents"] == 0
    assert before["available_balance_cents"] == 720000

    investigation = validate_success(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Reused third-party footage across August uploads",
                violation_window_start="2026-08-20T00:00:00Z",
                violation_window_end="2026-08-25T00:00:00Z",
                hold_payouts=True,
            ),
            REVIEWER,
        ),
        201,
    )
    assert investigation["hold_amount_cents"] == 720000

    after = validate_success(api.get_creator(creator["id"], FINANCE))
    assert after["held_cents"] == 720000
    assert after["statement_payable_cents"] == 700000
    assert after["available_balance_cents"] == 0
    assert after["payout_state"] == PAYOUT_STATE_HOLD


def test_a_larger_payable_can_disburse_more_at_the_tier_boundary(api):
    """A payable of 50000 sits in the middle tier and 49999 in the lowest.

    Design: Corner/cross_cutting_complexity_layers/volume_fee_tier_boundary_between_49999_and_50000
    """
    lower, _lower_profile = payable_creator(api, display_name="Ada Ads")
    upper, _upper_profile = payable_creator(api, display_name="Bob Bits")
    period = august_period(api)
    product = tips_product(
        api,
        product_type=PRODUCT_TYPE_TIPS,
        name="Fan Tips",
        creator_share_bps=9000,
        platform_fee_bps=1000,
        min_payable_cents=0,
    )
    post_event(
        api,
        lower["id"],
        product["id"],
        gross_amount_cents=55554,
        occurred_at="2026-08-05T00:00:00Z",
    )
    post_event(
        api,
        upper["id"],
        product["id"],
        gross_amount_cents=55555,
        occurred_at="2026-08-05T00:00:00Z",
    )
    get_success_data(api.close_period(period["id"], FINANCE))
    lower_statement = statement_for(api, lower["id"], period["id"])
    upper_statement = statement_for(api, upper["id"], period["id"])
    lower_final = get_success_data(
        api.finalize_statement(lower_statement["id"], FINANCE)
    )
    upper_final = get_success_data(
        api.finalize_statement(upper_statement["id"], FINANCE)
    )
    assert lower_final["net_payable_cents"] == 49999
    assert lower_final["withholding_rate_bps"] == 0
    assert upper_final["net_payable_cents"] == 50000

    lowest_tier = validate_success(
        api.create_payout(fac.payout_payload(lower["id"]), FINANCE), 201
    )
    assert lowest_tier["payable_before_fee_cents"] == 49999
    assert lowest_tier["fee_cents"] == 200
    assert lowest_tier["amount_cents"] == 49799

    middle_tier = validate_success(
        api.create_payout(fac.payout_payload(upper["id"]), FINANCE), 201
    )
    assert middle_tier["payable_before_fee_cents"] == 50000
    assert middle_tier["fee_cents"] == 150
    assert middle_tier["amount_cents"] == 49850


def test_the_running_balance_survives_an_accrual_and_its_reversal(api):
    """Every entry carries the balance that entry left behind.

    Design: Corner/cross_cutting_complexity_layers/ledger_balance_is_reconciled_after_create_update_and_debit
    """
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
    august_period(api)
    product = ads_product(
        api,
        name="Pre-roll Ads",
        creator_share_bps=5000,
        platform_fee_bps=5000,
        min_payable_cents=0,
    )
    item = content_item(
        api, creator["id"], title="Launch Vlog", published_at="2026-08-01T00:00:00Z"
    )
    event = post_event(
        api,
        creator["id"],
        product["id"],
        content_item_id=item["id"],
        gross_amount_cents=200000,
        occurred_at="2026-08-05T00:00:00Z",
    )

    accrued = validate_success(api.get_earnings_summary(creator["id"], FINANCE))
    assert accrued["ledger_balance_cents"] == 100000
    assert accrued["available_balance_cents"] == 0

    get_success_data(
        api.rate_content_item(
            item["id"],
            fac.rate_payload(RATING_RED, rating_source=RATING_SOURCE_MANUAL),
            REVIEWER,
        )
    )

    assert validate_success(api.get_earnings_summary(creator["id"], FINANCE))[
        "ledger_balance_cents"
    ] == 0

    rows = ledger_rows(api, creator["id"])
    assert len(rows) == 2
    assert rows[0]["entry_type"] == ENTRY_ACCRUAL
    assert rows[0]["amount_cents"] == 100000
    assert rows[0]["balance_after_cents"] == 100000
    assert rows[1]["entry_type"] == ENTRY_ACCRUAL_REVERSAL
    assert rows[1]["amount_cents"] == -100000
    assert rows[1]["balance_after_cents"] == 0

    stored = next(
        row
        for row in get_success_data(
            api.list_revenue_events(FINANCE, {"creator_id": creator["id"]})
        )
        if row["id"] == event["id"]
    )
    assert stored["status"] == EVENT_REVERSED
    assert stored["creator_share_cents"] == 0
    assert refresh_creator(api, creator["id"])["ledger_balance_cents"] == 0
