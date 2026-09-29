"""Clawbacks, arrears precedence, capped allocations and the loyalty tier."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as fac
from test_helpers.assertions import assert_total_count
from test_helpers.constants import (
    DEMONETIZED,
    ENTRY_ACCRUAL_REVERSAL,
    EVENT_ACCRUED,
    EVENT_BELOW_MINIMUM,
    EVENT_CLAWED_BACK,
    FUND_ALLOCATED,
    INVESTIGATION_OPEN,
    METHODOLOGY_PRO_RATA,
    PAYOUT_STATE_ARREARS,
    RATING_GREEN,
    RATING_RED,
    RATING_SOURCE_MANUAL,
)
from test_helpers.fixtures import (
    ads_product,
    august_period,
    content_item,
    eligible_creator,
    post_event,
    refresh_creator,
    statement_for,
    subs_product,
)
from test_helpers.test_users import (
    ADMIN,
    FINANCE,
    REVIEWER,
    REVIEWER_ALT,
    make_creator_headers,
    make_reviewer_headers,
)


def _substantiated_ad_clawback(api, hold_payouts=False):
    """A substantiated case over one 200000-cent ad accrual on a rated clip."""
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
    august_period(api)
    product = ads_product(
        api, name="Pre-roll Ads", creator_share_bps=5000, platform_fee_bps=5000
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
    investigation = get_success_data(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Licensed footage reuse in the August upload",
                violation_window_start="2026-08-04T00:00:00Z",
                violation_window_end="2026-08-06T00:00:00Z",
                hold_payouts=hold_payouts,
            ),
            REVIEWER,
        )
    )
    get_success_data(
        api.substantiate_investigation(
            investigation["id"],
            fac.substantiate_payload(finding="Footage was licensed to a third party."),
            REVIEWER_ALT,
        )
    )
    return creator, item, event, investigation


def test_a_clawed_back_accrual_is_not_rescored_by_a_later_rating(api):
    """Demonetizing the clip leaves the recovered share exactly as it was.

    No reversal entry is written for an accrual that was already clawed back.

    Design: Corner/calculations/clawed_back_events_are_excluded_from_rescoring_on_rerating
    """
    creator, item, event, investigation = _substantiated_ad_clawback(api)

    rated = validate_success(
        api.rate_content_item(
            item["id"],
            fac.rate_payload(RATING_RED, rating_source=RATING_SOURCE_MANUAL),
            make_reviewer_headers("reviewer-r3"),
        )
    )
    assert rated["suitability_rating"] == RATING_RED
    assert rated["monetization_state"] == DEMONETIZED

    rows = get_success_data(
        api.list_revenue_events(FINANCE, {"creator_id": creator["id"]})
    )
    reloaded = next(row for row in rows if row["id"] == event["id"])
    assert reloaded["status"] == EVENT_CLAWED_BACK
    assert reloaded["creator_share_cents"] == 100000
    assert_total_count(
        api.list_ledger_entries(
            creator["id"], FINANCE, {"entry_type": ENTRY_ACCRUAL_REVERSAL}
        ),
        0,
    )

    case = validate_success(api.get_investigation(investigation["id"], REVIEWER))
    assert case["clawback_base_cents"] == 100000
    assert case["clawback_unrecovered_cents"] == 100000
    assert refresh_creator(api, creator["id"])["outstanding_clawback_cents"] == 100000


def test_arrears_outranks_a_newly_opened_hold(api):
    """An unrecovered clawback keeps the channel in arrears past a new hold.

    Design: Corner/calculations/payout_state_precedence_puts_arrears_above_a_new_hold
    """
    creator, _item, _event, _investigation = _substantiated_ad_clawback(api)

    before = validate_success(api.get_creator(creator["id"], FINANCE))
    assert before["payout_state"] == PAYOUT_STATE_ARREARS
    assert before["outstanding_clawback_cents"] == 100000

    second = validate_success(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Second unrelated review window",
                violation_window_start="2026-08-10T00:00:00Z",
                violation_window_end="2026-08-12T00:00:00Z",
                hold_payouts=True,
            ),
            REVIEWER,
        ),
        201,
    )
    assert second["state"] == INVESTIGATION_OPEN
    assert second["hold_payouts"] is True
    assert second["hold_amount_cents"] == 0

    after = validate_success(api.get_creator(creator["id"], FINANCE))
    assert after["payout_state"] == PAYOUT_STATE_ARREARS
    assert after["outstanding_clawback_cents"] == 100000


def test_a_statement_ignores_events_that_fell_below_the_product_minimum(api):
    """Only the qualifying event reaches the swept statement.

    Design: Corner/calculations/statement_event_set_excludes_below_minimum_events
    """
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
    period = august_period(api)
    product = subs_product(
        api,
        name="Memberships",
        creator_share_bps=5000,
        platform_fee_bps=5000,
        min_payable_cents=250,
    )
    post_event(
        api,
        creator["id"],
        product["id"],
        gross_amount_cents=500,
        occurred_at="2026-08-05T00:00:00Z",
    )
    low = post_event(
        api,
        creator["id"],
        product["id"],
        gross_amount_cents=498,
        occurred_at="2026-08-06T00:00:00Z",
    )
    assert low["status"] == EVENT_BELOW_MINIMUM
    assert low["creator_share_cents"] == 0

    get_success_data(api.close_period(period["id"], FINANCE))
    rows = get_success_data(
        api.list_statements(
            FINANCE, {"creator_id": creator["id"], "period_id": period["id"]}
        )
    )
    assert len(rows) == 1
    assert rows[0]["event_count"] == 1
    assert rows[0]["gross_cents"] == 500
    assert rows[0]["creator_share_cents"] == 250
    assert rows[0]["withholding_rate_bps"] == 2400
    assert rows[0]["withholding_cents"] == 60
    assert rows[0]["net_payable_cents"] == 190


def test_the_per_recipient_cap_leaves_the_excess_unallocated(api):
    """Both recipients are capped and the surplus stays in the remainder.

    Design: Corner/calculations/fund_max_allocation_cap_excess_is_not_redistributed
    """
    top = eligible_creator(
        api,
        display_name="Top Creator",
        country_code="US",
        watch_time_minutes_365d=800000,
    )
    nxt = eligible_creator(
        api,
        display_name="Next Creator",
        country_code="GB",
        watch_time_minutes_365d=240000,
    )
    period = august_period(api)
    fund = get_success_data(
        api.create_fund(
            fac.fund_payload(
                period["id"], name="Capped Boost", max_allocation_cents=20000
            ),
            ADMIN,
        )
    )

    allocated = validate_success(
        api.allocate_fund(fund["id"], fac.allocate_payload(fund["version"]), FINANCE)
    )
    assert allocated["status"] == FUND_ALLOCATED
    assert allocated["allocated_cents"] == 40000
    assert allocated["unallocated_remainder_cents"] == 60000
    assert allocated["recipient_count"] == 2
    assert allocated["allocation_run_count"] == 1

    rows = assert_total_count(api.list_fund_allocations(fund["id"], FINANCE), 2)
    assert rows[0]["rank"] == 1
    assert rows[0]["creator_id"] == top["id"]
    assert rows[0]["amount_cents"] == 20000
    assert rows[0]["watch_time_minutes_at_allocation"] == 800000
    assert rows[0]["methodology_snapshot"] == METHODOLOGY_PRO_RATA
    assert rows[1]["rank"] == 2
    assert rows[1]["creator_id"] == nxt["id"]
    assert rows[1]["amount_cents"] == 20000


def test_the_loyalty_bonus_is_read_from_the_lifetime_paid_total(api):
    """A settled disbursement lifts the next accrual into the next bonus band.

    Design: Corner/calculations/tier_bonus_is_read_from_lifetime_paid_at_evaluation_time
    """
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
    profile = get_success_data(
        api.create_tax_profile(
            fac.tax_profile_payload(creator["id"], creator["version"]),
            make_creator_headers(creator["id"]),
        )
    )
    get_success_data(
        api.submit_tax_profile(profile["id"], make_creator_headers(creator["id"]))
    )
    get_success_data(
        api.verify_tax_profile(profile["id"], fac.verify_payload(), FINANCE)
    )
    august = august_period(api)
    product = subs_product(api, name="Memberships")
    august_event = post_event(
        api,
        creator["id"],
        product["id"],
        gross_amount_cents=1000000,
        occurred_at="2026-08-05T00:00:00Z",
    )
    assert august_event["effective_share_bps"] == 7000
    assert august_event["creator_share_cents"] == 700000

    get_success_data(api.close_period(august["id"], FINANCE))
    statement = statement_for(api, creator["id"], august["id"])
    get_success_data(api.finalize_statement(statement["id"], FINANCE))
    payout = get_success_data(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE)
    )
    get_success_data(api.submit_payout(payout["id"], FINANCE))
    get_success_data(
        api.record_settlement(
            payout["id"], fac.settlement_payload("SUCCEEDED"), FINANCE
        )
    )
    assert refresh_creator(api, creator["id"])["lifetime_paid_cents"] == 699900

    september = get_success_data(
        api.create_period(
            fac.period_payload(
                label="2026-09",
                period_start="2026-09-01T00:00:00Z",
                period_end="2026-10-01T00:00:00Z",
            ),
            ADMIN,
        )
    )
    later = validate_success(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"],
                product["id"],
                gross_amount_cents=1000000,
                occurred_at="2026-09-05T00:00:00Z",
            ),
            FINANCE,
        ),
        201,
    )
    assert later["period_id"] == september["id"]
    assert later["effective_share_bps"] == 7200
    assert later["creator_share_cents"] == 720000
    assert later["status"] == EVENT_ACCRUED
    assert later["suitability_rating_at_accrual"] == RATING_GREEN
