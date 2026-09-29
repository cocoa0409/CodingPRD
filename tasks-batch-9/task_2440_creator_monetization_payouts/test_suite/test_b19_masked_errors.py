"""Two guard conditions that a stronger guard always answers first."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.constants import (
    FUND_DRAFT,
    PERIOD_FINALIZED,
    STATEMENT_FINALIZED,
    VARIANT_FINAL,
)
from test_helpers.fixtures import (
    august_period,
    eligible_creator,
    post_event,
    refresh_creator,
    statement_for,
    subs_product,
)
from test_helpers.test_users import ADMIN, FINANCE


def test_a_finalized_window_is_never_reported_as_still_open(api):
    """The statement's own status answers before the window's status can.

    Design: Corner/errors/period_not_closed_is_unreachable_and_masked_by_statement_not_provisional
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
    statement = statement_for(api, creator["id"], period["id"])
    get_success_data(api.finalize_statement(statement["id"], FINANCE))

    validate_error(
        api.finalize_statement(statement["id"], FINANCE),
        err.ERR_STATEMENT_NOT_PROVISIONAL,
        409,
    )
    assert validate_success(api.get_period(period["id"], FINANCE))["status"] == (
        PERIOD_FINALIZED
    )
    reloaded = validate_success(api.get_statement(statement["id"], FINANCE))
    assert reloaded["status"] == STATEMENT_FINALIZED
    assert reloaded["withholding_variant"] == VARIANT_FINAL


def test_an_emptied_fund_is_reported_as_unallocated_not_as_recipientless(api):
    """Discarding the rows returns the fund to draft, which answers first.

    Design: Corner/errors/fund_no_recipients_is_unreachable_and_masked_by_fund_not_allocated
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
    get_success_data(
        api.void_fund_allocations(
            fund["id"],
            fac.void_allocations_payload(
                allocated["version"], reason="Recomputing the candidate pool"
            ),
            FINANCE,
        )
    )

    validate_error(
        api.disburse_fund(fund["id"], FINANCE), err.ERR_FUND_NOT_ALLOCATED, 409
    )
    reloaded = validate_success(api.get_fund(fund["id"], FINANCE))
    assert reloaded["status"] == FUND_DRAFT
    assert reloaded["recipient_count"] == 0
    assert reloaded["allocated_cents"] == 0
    assert reloaded["unallocated_remainder_cents"] == 104000
    assert refresh_creator(api, top["id"])["fund_credit_balance_cents"] == 0
