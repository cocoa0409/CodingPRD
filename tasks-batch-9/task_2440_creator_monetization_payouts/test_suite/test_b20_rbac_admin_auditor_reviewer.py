"""Each role is confined to the surface its duties require."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_total_count
from test_helpers.constants import (
    ELIGIBILITY_ELIGIBLE,
    ENTRY_FUND_CREDIT,
    PERIOD_OPEN,
    RATING_GREEN,
    RATING_RED,
    RATING_SOURCE_MANUAL,
    TAX_SUBMITTED,
)
from test_helpers.fixtures import (
    august_period,
    content_item,
    eligible_creator,
    new_creator,
    post_event,
    refresh_creator,
    subs_product,
)
from test_helpers.test_users import ADMIN, AUDITOR, FINANCE, REVIEWER, make_creator_headers


def test_an_auditor_is_refused_before_the_target_is_even_looked_up(api):
    """The role check answers ahead of the unknown identifier.

    Design: Corner/rbac/auditor_mutation_is_403_before_the_404
    """
    validate_error(
        api.submit_payout(NON_EXISTENT_UUID, AUDITOR), err.ERR_ROLE_NOT_PERMITTED, 403
    )
    validate_error(
        api.create_creator(
            fac.creator_payload(
                display_name="Auditor's Creator",
                country_code="US",
                follower_count=50000,
                watch_time_minutes_365d=300000,
            ),
            AUDITOR,
        ),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    assert_total_count(api.list_creators(AUDITOR), 0)


def test_an_auditor_may_read_every_collection(api):
    """Ledger, fund allocations and the channel collection are all readable.

    Design: Corner/rbac/auditor_can_read_every_collection_including_ledger_and_allocations
    """
    top = eligible_creator(
        api,
        display_name="Top Creator",
        country_code="US",
        watch_time_minutes_365d=800000,
    )
    eligible_creator(
        api,
        display_name="Next Creator",
        country_code="GB",
        watch_time_minutes_365d=240000,
    )
    period = august_period(api)
    fund = get_success_data(
        api.create_fund(
            fac.fund_payload(
                period["id"], name="August Boost", total_pool_cents=104000
            ),
            ADMIN,
        )
    )
    allocated = get_success_data(
        api.allocate_fund(fund["id"], fac.allocate_payload(fund["version"]), FINANCE)
    )
    get_success_data(api.disburse_fund(allocated["id"], FINANCE))

    ledger = assert_total_count(api.list_ledger_entries(top["id"], AUDITOR), 1)
    assert ledger[0]["entry_type"] == ENTRY_FUND_CREDIT

    allocations = assert_total_count(api.list_fund_allocations(fund["id"], AUDITOR), 2)
    assert allocations[0]["amount_cents"] == 80000
    assert allocations[1]["amount_cents"] == 24000

    assert_total_count(api.list_creators(AUDITOR), 2)


def test_an_administrator_may_not_move_or_verify_money(api):
    """Verification, window closing and evaluation all belong to finance.

    Design: Corner/rbac/platform_admin_cannot_perform_finance_money_operations
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    profile = get_success_data(
        api.create_tax_profile(
            fac.tax_profile_payload(creator["id"], creator["version"]),
            make_creator_headers(creator["id"]),
        )
    )
    get_success_data(
        api.submit_tax_profile(profile["id"], make_creator_headers(creator["id"]))
    )
    period = august_period(api)

    validate_error(
        api.verify_tax_profile(profile["id"], fac.verify_payload(), ADMIN),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.close_period(period["id"], ADMIN), err.ERR_ROLE_NOT_PERMITTED, 403
    )
    validate_error(
        api.evaluate_creator(creator["id"], ADMIN), err.ERR_ROLE_NOT_PERMITTED, 403
    )

    assert validate_success(api.get_tax_profile(profile["id"], FINANCE))["status"] == (
        TAX_SUBMITTED
    )
    assert validate_success(api.get_period(period["id"], FINANCE))["status"] == (
        PERIOD_OPEN
    )
    assert refresh_creator(api, creator["id"])["evaluation_count"] == 0


def test_an_administrator_may_not_act_on_policy(api):
    """Rating, striking and opening a case are all a reviewer's work.

    Design: Corner/rbac/platform_admin_cannot_perform_policy_operations
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    item = content_item(
        api, creator["id"], title="Launch Vlog", published_at="2026-08-01T00:00:00Z"
    )

    validate_error(
        api.rate_content_item(
            item["id"],
            fac.rate_payload(RATING_RED, rating_source=RATING_SOURCE_MANUAL),
            ADMIN,
        ),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_policy_strike(
            creator["id"],
            fac.policy_strike_payload(reason="Admin thinks this is a violation"),
            ADMIN,
        ),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Admin-opened review",
                violation_window_start="2026-07-01T00:00:00Z",
                violation_window_end="2026-07-02T00:00:00Z",
            ),
            ADMIN,
        ),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    assert validate_success(api.get_content_item(item["id"], REVIEWER))[
        "suitability_rating"
    ] == RATING_GREEN
    assert refresh_creator(api, creator["id"])["active_strike_count"] == 0
    assert_total_count(
        api.list_investigations(REVIEWER, {"creator_id": creator["id"]}), 0
    )


def _accrued_channel(api):
    """An eligible channel with one 1000000-cent subscription accrual."""
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
    return creator, period, product


def test_a_reviewer_may_not_read_the_money_surface(api):
    """Statements, disbursements, the ledger and funds are all closed to policy.

    The channel record itself stays readable, since ratings depend on it.

    Design: Corner/rbac/policy_reviewer_cannot_read_the_money_surface
    """
    creator, period, _product = _accrued_channel(api)
    fund = get_success_data(
        api.create_fund(
            fac.fund_payload(
                period["id"], name="August Boost", total_pool_cents=104000
            ),
            ADMIN,
        )
    )
    get_success_data(api.close_period(period["id"], FINANCE))

    validate_error(
        api.list_statements(REVIEWER, {"creator_id": creator["id"]}),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.list_payouts(REVIEWER, {"creator_id": creator["id"]}),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.list_ledger_entries(creator["id"], REVIEWER),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.get_fund(fund["id"], REVIEWER), err.ERR_ROLE_NOT_PERMITTED, 403
    )

    readable = validate_success(api.get_creator(creator["id"], REVIEWER))
    assert readable["id"] == creator["id"]
    assert readable["eligibility_status"] == ELIGIBILITY_ELIGIBLE


def test_a_reviewer_may_not_move_money(api):
    """Closing, disbursing and posting revenue are all refused.

    Design: Corner/rbac/policy_reviewer_cannot_move_money
    """
    creator, period, product = _accrued_channel(api)

    validate_error(
        api.close_period(period["id"], REVIEWER), err.ERR_ROLE_NOT_PERMITTED, 403
    )
    validate_error(
        api.create_payout(fac.payout_payload(creator["id"]), REVIEWER),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"],
                product["id"],
                gross_amount_cents=5000,
                occurred_at="2026-08-06T00:00:00Z",
            ),
            REVIEWER,
        ),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    reloaded = validate_success(api.get_period(period["id"], FINANCE))
    assert reloaded["status"] == PERIOD_OPEN
    assert reloaded["statement_count"] == 0
    assert refresh_creator(api, creator["id"])["ledger_balance_cents"] == 700000
