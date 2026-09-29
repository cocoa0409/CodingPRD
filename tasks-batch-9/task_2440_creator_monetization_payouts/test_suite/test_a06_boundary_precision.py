"""Inclusive and exclusive comparisons must hold at the exact unit."""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_instant, assert_total_count
from test_helpers.constants import (
    ALLOCATION_ACTIVE,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
    ENTRY_ACCRUAL,
    EVENT_ACCRUED,
    EVENT_BELOW_MINIMUM,
    FAILED_CRITERION_FOLLOWER,
    FAILED_CRITERION_WATCH_TIME,
    FORM_W8BEN,
    FUND_ALLOCATED,
    FUND_DRAFT,
    MIN_FOLLOWERS,
    MIN_WATCH_MINUTES_365D,
    SOURCE_REVENUE_EVENT,
    TAX_VERIFIED,
)
from test_helpers.fixtures import (
    august_period,
    eligible_creator,
    july_period,
    new_creator,
    post_event,
    refresh_creator,
    tips_product,
)
from test_helpers.test_users import ADMIN, FINANCE, make_creator_headers


def test_both_audience_minimums_pass_at_exact_equality(api):
    """Exactly 240000 watch minutes clears the gate; 9999 followers does not.

    The channel fails on the follower criterion alone, and once the count is
    lifted to exactly 10000 the next evaluation returns eligible with no failed
    criteria at all.

    Design: Difficulty/boundary_precision_check/eligibility_follower_and_watch_minimums_are_inclusive
    """
    creator = new_creator(
        api,
        display_name="Rae Edge",
        follower_count=MIN_FOLLOWERS - 1,
        watch_time_minutes_365d=MIN_WATCH_MINUTES_365D,
    )

    first = validate_success(api.evaluate_creator(creator["id"], FINANCE))
    assert first["eligibility_status"] == ELIGIBILITY_INELIGIBLE
    assert first["last_evaluation_failed_criteria"] == [FAILED_CRITERION_FOLLOWER]
    assert first["evaluation_count"] == 1

    patched = get_success_data(
        api.patch_creator_metrics(
            creator["id"], fac.metrics_payload(follower_count=MIN_FOLLOWERS), ADMIN
        )
    )
    assert patched["follower_count"] == MIN_FOLLOWERS
    assert patched["eligibility_status"] == ELIGIBILITY_INELIGIBLE
    assert patched["evaluation_count"] == 1

    second = validate_success(api.evaluate_creator(creator["id"], FINANCE))
    assert second["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    assert second["last_evaluation_failed_criteria"] == []
    assert second["evaluation_count"] == 2
    assert_instant(second["last_evaluated_at"], "2026-08-01T00:00:00Z")


def test_a_channel_short_on_both_metrics_reports_them_in_order(api):
    """One unit below each minimum yields both criteria in declared order.

    The follower criterion is listed before the watch-time criterion and the
    single evaluation is counted once.

    Design: Difficulty/boundary_precision_check/eligibility_follower_and_watch_minimums_are_inclusive
    """
    creator = new_creator(
        api,
        display_name="Sam Edge",
        follower_count=MIN_FOLLOWERS - 1,
        watch_time_minutes_365d=MIN_WATCH_MINUTES_365D - 1,
    )

    evaluated = validate_success(api.evaluate_creator(creator["id"], FINANCE))
    assert evaluated["eligibility_status"] == ELIGIBILITY_INELIGIBLE
    assert evaluated["last_evaluation_failed_criteria"] == [
        FAILED_CRITERION_FOLLOWER,
        FAILED_CRITERION_WATCH_TIME,
    ]
    assert refresh_creator(api, creator["id"])["evaluation_count"] == 1


def _gated_channel(api):
    creator = eligible_creator(api, display_name="Tao Min")
    product = tips_product(api, name="Tips Gated", min_payable_cents=250)
    period = july_period(api)
    return creator, product, period


def test_a_share_equal_to_the_minimum_still_accrues(api):
    """The minimum-payable gate excludes only shares strictly below it.

    A gross of 500 cents yields a share of exactly 250, which is accrued at the
    full rate and written to the ledger with a running balance of 250.

    Design: Difficulty/boundary_precision_check/revenue_event_min_payable_is_strictly_below
    """
    creator, product, _period = _gated_channel(api)

    event = post_event(api, creator["id"], product["id"], gross_amount_cents=500)
    assert event["effective_share_bps"] == 5000
    assert event["creator_share_cents"] == 250
    assert event["status"] == EVENT_ACCRUED

    rows = assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 1)
    assert rows[0]["entry_type"] == ENTRY_ACCRUAL
    assert rows[0]["amount_cents"] == 250
    assert rows[0]["balance_after_cents"] == 250
    assert rows[0]["source_entity"] == SOURCE_REVENUE_EVENT
    assert rows[0]["source_id"] == event["id"]
    assert refresh_creator(api, creator["id"])["ledger_balance_cents"] == 250


def test_one_cent_short_suppresses_the_share_and_writes_no_entry(api):
    """A share of 249 is zeroed, and a zero movement leaves no ledger row.

    The event is still stored against its period with its original gross, but
    its payable share is zero and the channel's ledger stays empty.

    Design: Difficulty/boundary_precision_check/revenue_event_min_payable_is_strictly_below
    """
    creator, product, period = _gated_channel(api)

    event = post_event(api, creator["id"], product["id"], gross_amount_cents=498)
    assert event["effective_share_bps"] == 5000
    assert event["creator_share_cents"] == 0
    assert event["status"] == EVENT_BELOW_MINIMUM

    assert_total_count(
        api.list_ledger_entries(creator["id"], FINANCE, {"source_id": event["id"]}), 0
    )
    assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 0)
    assert event["period_id"] == period["id"]
    assert event["gross_amount_cents"] == 498


def test_a_floor_one_minute_above_the_only_candidate_empties_the_pool(api):
    """The watch-time floor is inclusive, so 240001 excludes 240000 minutes.

    Allocation is refused because no channel qualifies, and the fund is left
    untouched in draft with no runs and no rows.

    Design: Difficulty/boundary_precision_check/fund_candidate_pool_empty_at_one_minute_above_watch_floor
    """
    creator = eligible_creator(api, display_name="Uma Floor", country_code="US")
    assert creator["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    period = july_period(api)
    fund = get_success_data(
        api.create_fund(
            fac.fund_payload(
                period["id"],
                name="Floor High",
                min_watch_time_minutes=MIN_WATCH_MINUTES_365D + 1,
            ),
            ADMIN,
        )
    )

    response = api.allocate_fund(
        fund["id"], fac.allocate_payload(fund["version"]), FINANCE
    )
    validate_error(response, err.ERR_FUND_POOL_EMPTY, 422)

    reloaded = validate_success(api.get_fund(fund["id"], FINANCE))
    assert reloaded["status"] == FUND_DRAFT
    assert reloaded["allocation_run_count"] == 0
    assert reloaded["allocated_cents"] == 0
    assert reloaded["unallocated_remainder_cents"] == fund["total_pool_cents"]
    assert reloaded["recipient_count"] == 0
    assert reloaded["version"] == fund["version"]
    assert_total_count(api.list_fund_allocations(fund["id"], FINANCE), 0)


def test_a_floor_exactly_at_the_candidate_allocates_the_whole_pool(api):
    """At equality the same channel qualifies and takes everything.

    The fund becomes allocated with one recipient and no remainder, the single
    row records the 240000 minutes it was measured on, and allocation alone
    credits no ledger.

    Design: Difficulty/boundary_precision_check/fund_candidate_pool_empty_at_one_minute_above_watch_floor
    """
    creator = eligible_creator(api, display_name="Uma Floor", country_code="US")
    period = august_period(api)
    fund = get_success_data(
        api.create_fund(
            fac.fund_payload(
                period["id"],
                name="Floor Exact",
                min_watch_time_minutes=MIN_WATCH_MINUTES_365D,
            ),
            ADMIN,
        )
    )

    allocated = validate_success(
        api.allocate_fund(fund["id"], fac.allocate_payload(fund["version"]), FINANCE)
    )
    assert allocated["status"] == FUND_ALLOCATED
    assert allocated["recipient_count"] == 1
    assert allocated["allocated_cents"] == 100000
    assert allocated["unallocated_remainder_cents"] == 0

    rows = assert_total_count(api.list_fund_allocations(fund["id"], FINANCE), 1)
    assert rows[0]["status"] == ALLOCATION_ACTIVE
    assert rows[0]["rank"] == 1
    assert rows[0]["amount_cents"] == 100000
    assert rows[0]["watch_time_minutes_at_allocation"] == MIN_WATCH_MINUTES_365D

    assert refresh_creator(api, creator["id"])["fund_credit_balance_cents"] == 0
    assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 0)


def _verified_treaty_rate(api, country_code, treaty_rate_bps, tin_provided=True):
    creator = new_creator(api, display_name=f"Treaty {country_code}", country_code=country_code)
    draft = get_success_data(
        api.create_tax_profile(
            fac.tax_profile_payload(
                creator["id"],
                creator["version"],
                form_type=FORM_W8BEN,
                country_code=country_code,
                tin_provided=tin_provided,
                treaty_claimed=True,
                treaty_rate_bps=treaty_rate_bps,
            ),
            FINANCE,
        )
    )
    get_success_data(
        api.submit_tax_profile(draft["id"], make_creator_headers(creator["id"]))
    )
    verified = get_success_data(
        api.verify_tax_profile(draft["id"], fac.verify_payload(), FINANCE)
    )
    return draft, verified


@pytest.mark.parametrize(
    "country_code,claimed,expected,rejected",
    [
        ("IN", 1000, 1500, 1000),
        ("JP", 1000, 1000, 2400),
        ("BR", 500, 3000, 500),
    ],
)
def test_a_treaty_claim_is_lifted_to_the_floor_but_never_pushed_below_it(
    api, country_code, claimed, expected, rejected
):
    """A claim under the floor rises to it while a claim at the floor stands.

    A country with no treaty floor at all cannot use the treaty branch and falls
    back to the non-resident default rate instead of honouring the claim.

    Design: Difficulty/boundary_precision_check/treaty_rate_floor_is_a_lower_bound_not_an_override
    """
    draft, verified = _verified_treaty_rate(api, country_code, claimed)

    assert draft["withholding_rate_bps"] == 2400
    assert verified["withholding_rate_bps"] == expected
    assert verified["withholding_rate_bps"] != rejected
    assert verified["treaty_rate_bps"] == claimed


def test_a_treaty_claim_without_a_taxpayer_number_never_reaches_the_floor(api):
    """The claim is discarded before the floor is consulted at all.

    A country whose floor is zero still resolves to the non-resident default
    rate of 3000 basis points when no taxpayer number was supplied.

    Design: Difficulty/boundary_precision_check/treaty_rate_floor_is_a_lower_bound_not_an_override
    """
    _draft, verified = _verified_treaty_rate(api, "DE", 500, tin_provided=False)

    assert verified["withholding_rate_bps"] == 3000
    assert verified["withholding_rate_bps"] != 0
    assert verified["withholding_rate_bps"] != 500


def test_verification_stamps_a_three_year_validity_window(api):
    """Verifying sets the expiry exactly 1095 days after the verified instant.

    The profile is verified at the current instant with no rejection reason and
    expires on the last day of July 2029.

    Design: Difficulty/boundary_precision_check/treaty_rate_floor_is_a_lower_bound_not_an_override
    """
    _draft, verified = _verified_treaty_rate(api, "IN", 1000)

    assert verified["status"] == TAX_VERIFIED
    assert_instant(verified["verified_at"], "2026-08-01T00:00:00Z")
    assert_instant(verified["expires_at"], "2029-07-31T00:00:00Z")
    assert verified["rejection_reason"] is None
