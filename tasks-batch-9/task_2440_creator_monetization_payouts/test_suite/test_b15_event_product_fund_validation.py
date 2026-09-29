"""Cross-entity and aggregate rules on events, surfaces and funds."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_total_count
from test_helpers.constants import (
    FUND_DRAFT,
    METHODOLOGY_GUARANTEED_FLOOR,
    METHODOLOGY_PRO_RATA,
    PRODUCT_RETIRED,
    PRODUCT_TYPE_SUBSCRIPTIONS,
)
from test_helpers.fixtures import (
    ads_product,
    august_period,
    content_item,
    eligible_creator,
    refresh_creator,
    subs_product,
)
from test_helpers.test_users import ADMIN, FINANCE


def test_an_advertising_event_must_name_the_clip_it_monetized(api):
    """Without the clip link the event is refused and nothing accrues.

    Design: Corner/validations/advertising_event_without_a_content_link_is_rejected
    """
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
    august_period(api)
    product = ads_product(
        api, name="Pre-roll Ads", creator_share_bps=5000, platform_fee_bps=5000
    )

    validate_error(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"],
                product["id"],
                gross_amount_cents=200000,
                occurred_at="2026-08-05T00:00:00Z",
            ),
            FINANCE,
        ),
        err.ERR_CONTENT_LINK_REQUIRED,
        422,
    )
    assert_total_count(
        api.list_revenue_events(FINANCE, {"creator_id": creator["id"]}), 0
    )
    assert refresh_creator(api, creator["id"])["ledger_balance_cents"] == 0


def test_a_subscription_event_may_not_name_a_clip(api):
    """The clip link is only meaningful for suitability-sensitive revenue.

    Design: Corner/validations/subscriptions_event_with_a_content_link_is_rejected
    """
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
    item = content_item(
        api, creator["id"], title="Launch Vlog", published_at="2026-08-01T00:00:00Z"
    )
    august_period(api)
    product = subs_product(api, name="Memberships")

    validate_error(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"],
                product["id"],
                content_item_id=item["id"],
                gross_amount_cents=200000,
                occurred_at="2026-08-05T00:00:00Z",
            ),
            FINANCE,
        ),
        err.ERR_CONTENT_LINK_FORBIDDEN,
        422,
    )
    assert_total_count(
        api.list_revenue_events(FINANCE, {"creator_id": creator["id"]}), 0
    )


def test_a_retired_surface_accrues_nothing_further(api):
    """Revenue posted against a retired surface is refused.

    Design: Corner/validations/revenue_event_on_a_retired_product_is_rejected
    """
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
    august_period(api)
    product = subs_product(api, name="Memberships")
    get_success_data(api.retire_product(product["id"], ADMIN))

    validate_error(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"],
                product["id"],
                gross_amount_cents=1000000,
                occurred_at="2026-08-05T00:00:00Z",
            ),
            FINANCE,
        ),
        err.ERR_PRODUCT_RETIRED,
        409,
    )
    rows = get_success_data(api.list_products(ADMIN))
    assert rows[0]["status"] == PRODUCT_RETIRED
    assert_total_count(
        api.list_revenue_events(FINANCE, {"product_id": product["id"]}), 0
    )


def test_a_share_split_must_account_for_the_whole_amount(api):
    """A split that leaves a gap is refused and stores no surface.

    Design: Corner/validations/product_share_split_must_sum_to_ten_thousand_bps
    """
    validate_error(
        api.create_product(
            fac.product_payload(
                product_type=PRODUCT_TYPE_SUBSCRIPTIONS,
                name="Lopsided Memberships",
                creator_share_bps=7000,
                platform_fee_bps=2000,
                min_payable_cents=fac.OMIT,
            ),
            ADMIN,
        ),
        err.ERR_SHARE_SPLIT_NOT_WHOLE,
        422,
    )
    assert_total_count(api.list_products(ADMIN), 0)


def test_an_amended_split_is_checked_against_the_resulting_surface(api):
    """Changing one half of the split without the other is refused.

    Design: Corner/validations/patch_product_share_split_is_checked_on_the_resulting_row
    """
    product = subs_product(api, name="Memberships")

    validate_error(
        api.patch_product(product["id"], {"creator_share_bps": 6000}, ADMIN),
        err.ERR_SHARE_SPLIT_NOT_WHOLE,
        422,
    )
    rows = get_success_data(api.list_products(ADMIN))
    assert rows[0]["creator_share_bps"] == 7000
    assert rows[0]["platform_fee_bps"] == 3000
    assert rows[0]["version"] == product["version"]


def test_one_window_carries_at_most_one_live_fund(api):
    """The second fund for the same window is refused.

    Design: Corner/validations/second_live_fund_for_the_same_period_is_rejected
    """
    period = august_period(api)
    fund = get_success_data(
        api.create_fund(fac.fund_payload(period["id"], name="August Boost"), ADMIN)
    )

    validate_error(
        api.create_fund(
            fac.fund_payload(
                period["id"], name="August Boost Two", total_pool_cents=50000
            ),
            ADMIN,
        ),
        err.ERR_FUND_ALREADY_EXISTS_FOR_PERIOD,
        409,
    )
    assert_total_count(api.list_funds(ADMIN, {"period_id": period["id"]}), 1)
    assert validate_success(api.get_fund(fund["id"], FINANCE))["status"] == FUND_DRAFT


def test_a_floor_methodology_needs_a_cap_that_clears_the_floor(api):
    """The cap check binds only for the methodology that guarantees a floor.

    Design: Corner/validations/guaranteed_floor_fund_cap_below_the_floor_is_rejected
    """
    period = august_period(api)

    validate_error(
        api.create_fund(
            fac.fund_payload(
                period["id"],
                name="Floor Fund",
                methodology=METHODOLOGY_GUARANTEED_FLOOR,
                max_allocation_cents=4999,
            ),
            ADMIN,
        ),
        err.ERR_FUND_CAP_BELOW_FLOOR,
        422,
    )

    accepted = validate_success(
        api.create_fund(
            fac.fund_payload(
                period["id"],
                name="Pro Rata Fund",
                methodology=METHODOLOGY_PRO_RATA,
                max_allocation_cents=4999,
            ),
            ADMIN,
        ),
        201,
    )
    assert accepted["methodology"] == METHODOLOGY_PRO_RATA
    assert accepted["max_allocation_cents"] == 4999
