"""Computed reads, metric writes, settings and multi-statement disbursement."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers.assertions import assert_instant, assert_total_count
from test_helpers.constants import (
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
    ENTRY_ACCRUAL,
    ENTRY_PAYOUT_DEBIT,
    ENTRY_WITHHOLDING,
    FAILED_CRITERION_FOLLOWER,
    FAILED_CRITERION_WATCH_TIME,
    FAILURE_CODE_BANK_REJECTED,
    PAYOUT_METHOD_BANK_TRANSFER,
    PAYOUT_METHOD_CHECK,
    PAYOUT_STATE_ACCRUING,
    RATING_GREEN,
    RATING_SOURCE_DEFAULT,
    SOURCE_EARNINGS_STATEMENT,
    SOURCE_REVENUE_EVENT,
)
from test_helpers.fixtures import (
    august_period,
    content_item,
    eligible_creator,
    new_creator,
    payable_creator,
    post_event,
    refresh_creator,
    statement_for,
    subs_product,
)
from test_helpers.test_users import ADMIN, AUDITOR, FINANCE, make_creator_headers


def test_the_earnings_summary_recomputes_without_drifting(api):
    """Two reads by different roles agree and neither advances the version.

    Design: Corner/endpoints/earnings_summary_recomputes_without_drifting_or_bumping_version
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
    stored = validate_success(api.get_creator(creator["id"], FINANCE))

    own = validate_success(
        api.get_earnings_summary(creator["id"], make_creator_headers(creator["id"]))
    )
    assert own["ledger_balance_cents"] == 532000
    assert own["statement_payable_cents"] == 532000
    assert own["fund_credit_balance_cents"] == 0
    assert own["held_cents"] == 0
    assert own["available_balance_cents"] == 532000
    assert own["payout_state"] == PAYOUT_STATE_ACCRUING
    assert own["version"] == stored["version"]

    operator = validate_success(api.get_earnings_summary(creator["id"], FINANCE))
    assert operator["available_balance_cents"] == 532000
    assert operator["version"] == stored["version"]


def test_writing_new_metrics_does_not_re_evaluate_eligibility(api):
    """The stored verdict is stale until an evaluation is asked for.

    Design: Corner/endpoints/patch_metrics_writes_counters_without_re_evaluating_eligibility
    """
    creator = new_creator(
        api,
        display_name="Small Creator",
        country_code="US",
        follower_count=500,
        watch_time_minutes_365d=100,
    )
    evaluated = get_success_data(api.evaluate_creator(creator["id"], FINANCE))

    patched = validate_success(
        api.patch_creator_metrics(
            creator["id"],
            fac.metrics_payload(follower_count=50000, watch_time_minutes_365d=300000),
            ADMIN,
        )
    )
    assert patched["follower_count"] == 50000
    assert patched["watch_time_minutes_365d"] == 300000
    assert patched["eligibility_status"] == ELIGIBILITY_INELIGIBLE
    assert patched["evaluation_count"] == 1
    assert patched["last_evaluation_failed_criteria"] == [
        FAILED_CRITERION_FOLLOWER,
        FAILED_CRITERION_WATCH_TIME,
    ]
    assert patched["version"] == evaluated["version"] + 1

    re_evaluated = validate_success(api.evaluate_creator(creator["id"], FINANCE))
    assert re_evaluated["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    assert re_evaluated["last_evaluation_failed_criteria"] == []
    assert re_evaluated["evaluation_count"] == 2


def _failed_payout(api):
    """A verified channel whose only disbursement was rejected by the bank."""
    creator, _profile = payable_creator(api, display_name="Ada Ads")
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
    payout = get_success_data(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE)
    )
    get_success_data(api.submit_payout(payout["id"], FINANCE))
    get_success_data(
        api.record_settlement(
            payout["id"],
            fac.settlement_payload("FAILED", failure_code=FAILURE_CODE_BANK_REJECTED),
            FINANCE,
        )
    )
    return creator, payout


def test_changing_the_disbursement_method_clears_the_failure_run(api):
    """A new threshold leaves the run intact; a new method resets it.

    Design: Corner/endpoints/payout_settings_method_change_resets_the_failure_counter
    """
    creator, payout = _failed_payout(api)

    threshold_only = validate_success(
        api.set_payout_settings(
            creator["id"],
            fac.payout_settings_payload(
                payout_threshold_cents=2000, payout_method=fac.OMIT
            ),
            make_creator_headers(creator["id"]),
        )
    )
    assert threshold_only["payout_threshold_cents"] == 2000
    assert threshold_only["consecutive_payment_failures"] == 1

    method_change = validate_success(
        api.set_payout_settings(
            creator["id"],
            fac.payout_settings_payload(payout_method=PAYOUT_METHOD_CHECK),
            FINANCE,
        )
    )
    assert method_change["payout_method"] == PAYOUT_METHOD_CHECK
    assert method_change["consecutive_payment_failures"] == 0

    reloaded = validate_success(api.get_payout(payout["id"], FINANCE))
    assert reloaded["method"] == PAYOUT_METHOD_BANK_TRANSFER
    assert reloaded["fee_cents"] == 100
    assert reloaded["amount_cents"] == 699900


def test_one_disbursement_sweeps_every_unattached_finalized_statement(api):
    """Two months of finalized statements are paid together in window order.

    Design: Corner/endpoints/payout_attaches_every_unattached_finalized_statement_in_period_order
    """
    creator, _profile = payable_creator(api, display_name="Ada Ads")
    product = subs_product(api, name="Memberships")

    august = august_period(api)
    post_event(
        api,
        creator["id"],
        product["id"],
        gross_amount_cents=1000000,
        occurred_at="2026-08-05T00:00:00Z",
    )
    get_success_data(api.close_period(august["id"], FINANCE))
    august_statement = statement_for(api, creator["id"], august["id"])
    get_success_data(api.finalize_statement(august_statement["id"], FINANCE))

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
    post_event(
        api,
        creator["id"],
        product["id"],
        gross_amount_cents=1000000,
        occurred_at="2026-09-05T00:00:00Z",
    )
    get_success_data(api.close_period(september["id"], FINANCE))
    september_statement = statement_for(api, creator["id"], september["id"])
    get_success_data(api.finalize_statement(september_statement["id"], FINANCE))

    payout = validate_success(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE), 201
    )
    assert payout["payable_before_fee_cents"] == 1400000
    assert payout["fee_cents"] == 100
    assert payout["amount_cents"] == 1399900
    assert payout["statement_count"] == 2

    assert_total_count(api.list_statements(FINANCE, {"payout_id": payout["id"]}), 2)
    assert validate_success(api.get_statement(august_statement["id"], FINANCE))[
        "payout_id"
    ] == payout["id"]
    assert validate_success(api.get_statement(september_statement["id"], FINANCE))[
        "payout_id"
    ] == payout["id"]
    assert refresh_creator(api, creator["id"])["available_balance_cents"] == 0


def test_the_ledger_can_be_filtered_down_to_a_single_causing_row(api):
    """Each filter combination returns exactly the entry that row caused.

    Design: Corner/endpoints/ledger_listing_filters_by_source_entity_and_source_id
    """
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
    period = august_period(api)
    product = subs_product(api, name="Memberships")
    event = post_event(
        api,
        creator["id"],
        product["id"],
        gross_amount_cents=1000000,
        occurred_at="2026-08-05T00:00:00Z",
    )
    get_success_data(api.close_period(period["id"], FINANCE))
    statement = statement_for(api, creator["id"], period["id"])

    by_event = assert_total_count(
        api.list_ledger_entries(
            creator["id"],
            AUDITOR,
            {"source_entity": SOURCE_REVENUE_EVENT, "source_id": event["id"]},
        ),
        1,
    )
    assert by_event[0]["entry_type"] == ENTRY_ACCRUAL
    assert by_event[0]["amount_cents"] == 700000

    by_statement = assert_total_count(
        api.list_ledger_entries(
            creator["id"],
            AUDITOR,
            {"source_entity": SOURCE_EARNINGS_STATEMENT, "source_id": statement["id"]},
        ),
        1,
    )
    assert by_statement[0]["entry_type"] == ENTRY_WITHHOLDING
    assert by_statement[0]["amount_cents"] == -168000

    rows, meta = validate_paginated(
        api.list_ledger_entries(
            creator["id"], AUDITOR, {"entry_type": ENTRY_PAYOUT_DEBIT}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_advancing_the_clock_stamps_every_later_write(api):
    """A clip created after the move carries the new instant, not the old one.

    Design: Corner/endpoints/clock_advance_stamps_every_later_write
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    early = content_item(
        api, creator["id"], title="Early Vlog", published_at="2026-08-01T00:00:00Z"
    )

    validate_success(api.set_clock(fac.clock_payload("2026-08-14T12:00:00Z"), ADMIN))
    late = validate_success(
        api.create_content_item(
            fac.content_item_payload(
                creator["id"],
                title="Mid-Month Vlog",
                published_at="2026-08-14T00:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )
    assert_instant(late["published_at"], "2026-08-14T00:00:00Z")
    assert_instant(late["created_at"], "2026-08-14T12:00:00Z")
    assert late["suitability_rating"] == RATING_GREEN
    assert late["rating_source"] == RATING_SOURCE_DEFAULT

    stored_early = validate_success(api.get_content_item(early["id"], ADMIN))
    assert_instant(stored_early["created_at"], "2026-08-01T00:00:00Z")
    assert_total_count(api.list_content_items(ADMIN, {"creator_id": creator["id"]}), 2)
