"""Share, withholding and fee arithmetic reproduced to the cent."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as fac
from test_helpers.assertions import assert_total_count
from test_helpers.constants import (
    ELIGIBILITY_SUSPENDED,
    ENTRY_ACCRUAL,
    ENTRY_WITHHOLDING,
    ENTRY_WITHHOLDING_TRUE_UP,
    EVENT_ACCRUED,
    FAILED_CRITERION_POLICY,
    FORM_W8BEN,
    PAYOUT_METHOD_CHECK,
    RATING_SOURCE_AUTOMATED,
    RATING_YELLOW,
    SOURCE_EARNINGS_STATEMENT,
    STATEMENT_FINALIZED,
    TAX_VERIFIED,
    VARIANT_FINAL,
    VARIANT_PROVISIONAL,
)
from test_helpers.fixtures import (
    ads_product,
    august_period,
    content_item,
    eligible_creator,
    new_creator,
    post_event,
    refresh_creator,
    statement_for,
    subs_product,
)
from test_helpers.test_users import FINANCE, REVIEWER, make_creator_headers


def test_the_suitability_multiplier_only_touches_advertising_revenue(api):
    """A yellow-rated clip discounts ad revenue and leaves subscriptions alone.

    Design: Corner/calculations/suitability_multiplier_applies_only_to_sensitive_products
    """
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
    august_period(api)
    ad_product = ads_product(
        api, name="Pre-roll Ads", creator_share_bps=5000, platform_fee_bps=5000
    )
    sub_product = subs_product(api, name="Memberships")
    item = content_item(
        api, creator["id"], title="Launch Vlog", published_at="2026-08-01T00:00:00Z"
    )
    get_success_data(
        api.rate_content_item(
            item["id"],
            fac.rate_payload(RATING_YELLOW, rating_source=RATING_SOURCE_AUTOMATED),
            REVIEWER,
        )
    )

    ad_event = validate_success(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"],
                ad_product["id"],
                content_item_id=item["id"],
                gross_amount_cents=200000,
                occurred_at="2026-08-05T00:00:00Z",
            ),
            FINANCE,
        ),
        201,
    )
    assert ad_event["suitability_rating_at_accrual"] == RATING_YELLOW
    assert ad_event["effective_share_bps"] == 3000
    assert ad_event["creator_share_cents"] == 60000
    assert ad_event["status"] == EVENT_ACCRUED

    sub_event = validate_success(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"],
                sub_product["id"],
                gross_amount_cents=1000000,
                occurred_at="2026-08-06T00:00:00Z",
            ),
            FINANCE,
        ),
        201,
    )
    assert sub_event["effective_share_bps"] == 7000
    assert sub_event["creator_share_cents"] == 700000
    assert refresh_creator(api, creator["id"])["ledger_balance_cents"] == 760000


def _verify(api, creator, **profile_overrides):
    """Take a fresh channel's document all the way to a verification decision."""
    profile = get_success_data(
        api.create_tax_profile(
            fac.tax_profile_payload(
                creator["id"], creator["version"], **profile_overrides
            ),
            make_creator_headers(creator["id"]),
        )
    )
    get_success_data(
        api.submit_tax_profile(profile["id"], make_creator_headers(creator["id"]))
    )
    return validate_success(
        api.verify_tax_profile(profile["id"], fac.verify_payload(), FINANCE)
    )


def test_a_domestic_form_without_a_taxpayer_number_gets_the_backup_rate(api):
    """Verification succeeds but the rate falls back to the backup figure.

    Design: Corner/calculations/withholding_rate_w9_without_tin_falls_back_to_backup_rate
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")

    verified = _verify(api, creator, country_code="US", tin_provided=False)
    assert verified["status"] == TAX_VERIFIED
    assert verified["withholding_rate_bps"] == 2400


def test_a_foreign_form_with_no_treaty_claim_gets_the_default_rate(api):
    """Without a claimed treaty the non-resident default rate applies.

    Design: Corner/calculations/withholding_rate_w8ben_without_treaty_uses_nra_default
    """
    creator = new_creator(api, display_name="Basil British", country_code="GB")

    verified = _verify(
        api, creator, form_type=FORM_W8BEN, country_code="GB", tin_provided=True
    )
    assert verified["status"] == TAX_VERIFIED
    assert verified["withholding_rate_bps"] == 3000


def test_a_zero_treaty_floor_permits_a_zero_rate(api):
    """A claimed rate that matches its country floor of zero is honoured.

    Design: Corner/calculations/gb_zero_treaty_floor_permits_a_zero_percent_verified_rate
    """
    creator = new_creator(api, display_name="Basil British", country_code="GB")

    verified = _verify(
        api,
        creator,
        form_type=FORM_W8BEN,
        country_code="GB",
        tin_provided=True,
        treaty_claimed=True,
        treaty_rate_bps=0,
    )
    assert verified["status"] == TAX_VERIFIED
    assert verified["treaty_claimed"] is True
    assert verified["treaty_rate_bps"] == 0
    assert verified["withholding_rate_bps"] == 0


def _foreign_default_rate_accrual(api):
    """A non-resident channel with one 1500-cent accrual at a 6700 bps share."""
    creator = eligible_creator(api, display_name="Basil British", country_code="GB")
    _verified = _verify(
        api, creator, form_type=FORM_W8BEN, country_code="GB", tin_provided=True
    )
    period = august_period(api)
    product = subs_product(
        api, name="Memberships", creator_share_bps=6700, platform_fee_bps=3300
    )
    event = post_event(
        api,
        creator["id"],
        product["id"],
        gross_amount_cents=1500,
        occurred_at="2026-08-05T00:00:00Z",
    )
    return creator, period, event


def test_the_provisional_withholding_rounds_half_up_on_an_exact_half_cent(api):
    """The swept statement rounds 301.5 up to 302 and nets the remainder.

    Design: Corner/calculations/provisional_withholding_rounds_half_up_at_exact_half_cent
    """
    creator, period, event = _foreign_default_rate_accrual(api)
    assert event["creator_share_cents"] == 1005

    get_success_data(api.close_period(period["id"], FINANCE))
    rows = get_success_data(
        api.list_statements(
            FINANCE, {"creator_id": creator["id"], "period_id": period["id"]}
        )
    )
    assert len(rows) == 1
    assert rows[0]["creator_share_cents"] == 1005
    assert rows[0]["withholding_rate_bps"] == 3000
    assert rows[0]["withholding_cents"] == 302
    assert rows[0]["net_payable_cents"] == 703
    assert rows[0]["withholding_variant"] == VARIANT_PROVISIONAL


def test_no_true_up_is_written_when_the_final_rate_matches_the_provisional_one(api):
    """Finalization switches the variant without moving a single cent.

    The ledger keeps only the accrual and the original withholding.

    Design: Corner/calculations/withholding_true_up_is_omitted_when_final_variant_delta_is_zero
    """
    creator, period, _event = _foreign_default_rate_accrual(api)
    get_success_data(api.close_period(period["id"], FINANCE))
    statement = statement_for(api, creator["id"], period["id"])

    finalized = validate_success(api.finalize_statement(statement["id"], FINANCE))
    assert finalized["status"] == STATEMENT_FINALIZED
    assert finalized["withholding_variant"] == VARIANT_FINAL
    assert finalized["withholding_cents"] == 302
    assert finalized["net_payable_cents"] == 703

    rows = assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 2)
    assert rows[0]["entry_type"] == ENTRY_ACCRUAL
    assert rows[0]["amount_cents"] == 1005
    assert rows[1]["entry_type"] == ENTRY_WITHHOLDING
    assert rows[1]["amount_cents"] == -302
    assert all(row["entry_type"] != ENTRY_WITHHOLDING_TRUE_UP for row in rows)
    assert refresh_creator(api, creator["id"])["ledger_balance_cents"] == 703


def test_the_cheque_fee_cap_binds_exactly_at_its_flat_fee(api):
    """The tiered percentage adds nothing once the cap equals the flat charge.

    Design: Corner/calculations/check_method_fee_cap_binds_exactly_at_the_flat_fee
    """
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
    _verify(api, creator, country_code="US", tin_provided=True)
    get_success_data(
        api.set_payout_settings(
            creator["id"],
            fac.payout_settings_payload(payout_method=PAYOUT_METHOD_CHECK),
            FINANCE,
        )
    )
    period = august_period(api)
    product = subs_product(
        api, name="Memberships", creator_share_bps=4000, platform_fee_bps=6000
    )
    post_event(
        api,
        creator["id"],
        product["id"],
        gross_amount_cents=100000,
        occurred_at="2026-08-05T00:00:00Z",
    )
    get_success_data(api.close_period(period["id"], FINANCE))
    statement = statement_for(api, creator["id"], period["id"])
    get_success_data(api.finalize_statement(statement["id"], FINANCE))

    payout = validate_success(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE), 201
    )
    assert payout["method"] == PAYOUT_METHOD_CHECK
    assert payout["payable_before_fee_cents"] == 40000
    assert payout["fee_cents"] == 500
    assert payout["amount_cents"] == 39500
    assert payout["fund_credit_cents"] == 0
    assert payout["statement_count"] == 1


def test_a_policy_strike_short_circuits_the_audience_criteria(api):
    """A struck channel is suspended and reports only the policy failure.

    Design: Corner/calculations/eligibility_policy_gate_short_circuits_metric_criteria
    """
    creator = new_creator(
        api,
        display_name="Small Creator",
        country_code="GB",
        follower_count=500,
        watch_time_minutes_365d=100,
    )
    get_success_data(
        api.create_policy_strike(
            creator["id"],
            fac.policy_strike_payload(reason="Confirmed reuse of licensed footage."),
            REVIEWER,
        )
    )

    evaluated = validate_success(api.evaluate_creator(creator["id"], FINANCE))
    assert evaluated["eligibility_status"] == ELIGIBILITY_SUSPENDED
    assert evaluated["last_evaluation_failed_criteria"] == [FAILED_CRITERION_POLICY]
    assert evaluated["active_strike_count"] == 1
    assert evaluated["evaluation_count"] == 2


def test_each_ledger_row_carries_the_signed_running_total(api):
    """The withholding row's balance continues from the accrual's balance.

    Design: Corner/calculations/ledger_balance_after_tracks_signed_running_total
    """
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
    period = august_period(api)
    product = subs_product(api, name="Memberships")
    post_event(
        api,
        creator["id"],
        product["id"],
        gross_amount_cents=1000000,
        occurred_at="2026-08-05T00:00:00Z",
    )

    get_success_data(api.close_period(period["id"], FINANCE))
    rows = assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 2)
    assert rows[0]["entry_type"] == ENTRY_ACCRUAL
    assert rows[0]["amount_cents"] == 700000
    assert rows[0]["balance_after_cents"] == 700000
    assert rows[1]["entry_type"] == ENTRY_WITHHOLDING
    assert rows[1]["amount_cents"] == -168000
    assert rows[1]["balance_after_cents"] == 532000
    assert rows[1]["source_entity"] == SOURCE_EARNINGS_STATEMENT
    assert refresh_creator(api, creator["id"])["ledger_balance_cents"] == 532000
