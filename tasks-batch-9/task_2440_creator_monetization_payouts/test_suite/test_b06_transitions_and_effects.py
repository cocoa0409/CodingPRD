"""Legal transitions and the side effects they are required to fire."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as fac
from test_helpers.assertions import assert_instant, assert_total_count
from test_helpers.constants import (
    APPEAL_UPHELD,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
    ELIGIBILITY_SUSPENDED,
    ENTRY_PAYOUT_REVERSAL,
    FAILED_CRITERION_FOLLOWER,
    FAILED_CRITERION_POLICY,
    FAILED_CRITERION_WATCH_TIME,
    FAILURE_CODE_BANK_REJECTED,
    INVESTIGATION_CLEARED,
    LIMITED,
    PAYOUT_FAILED,
    PAYOUT_PAID,
    PAYOUT_PROCESSING,
    PAYOUT_STATE_ACCRUING,
    PERIOD_CLOSED,
    PRODUCT_RETIRED,
    RATING_RED,
    RATING_SOURCE_APPEAL,
    RATING_YELLOW,
    SOURCE_PAYOUT,
    STATEMENT_FINALIZED,
    STATEMENT_PAID,
)
from test_helpers.fixtures import (
    august_period,
    content_item,
    finalize,
    new_creator,
    payable_creator,
    post_event,
    refresh_creator,
    statement_for,
    subs_product,
)
from test_helpers.test_users import ADMIN, FINANCE, REVIEWER, REVIEWER_ALT, make_creator_headers


def test_retiring_a_surface_stamps_the_retirement_instant(api):
    """Retirement is terminal and leaves the commercial split as it was.

    Design: Corner/state_machines/revenue_product_active_to_retired_stamps_retired_at
    """
    product = subs_product(api, name="Memberships")

    retired = validate_success(api.retire_product(product["id"], ADMIN), 200)
    assert retired["status"] == PRODUCT_RETIRED
    assert_instant(retired["retired_at"], "2026-08-01T00:00:00Z")
    assert retired["creator_share_bps"] == 7000


def test_an_upheld_appeal_can_restore_only_part_of_the_rating(api):
    """The requested partial rating is what is granted, by appeal provenance.

    The clip returns to a limited state whose provenance is the appeal itself, so
    no reviewer is recorded as its last rater and no appeal is left open.

    Design: Corner/state_machines/appeal_upheld_to_yellow_restores_partial_rating_and_clears_rater
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    item = content_item(
        api, creator["id"], title="Launch Vlog", published_at="2026-08-01T00:00:00Z"
    )
    get_success_data(
        api.rate_content_item(item["id"], fac.rate_payload(RATING_RED), REVIEWER)
    )
    appeal = get_success_data(
        api.create_appeal(
            fac.appeal_payload(
                item["id"],
                requested_rating=RATING_YELLOW,
                statement_text="Only one segment is borderline.",
            ),
            make_creator_headers(creator["id"]),
        )
    )
    get_success_data(api.start_appeal_review(appeal["id"], REVIEWER_ALT))

    decided = validate_success(
        api.decide_appeal(
            appeal["id"],
            fac.decide_appeal_payload(
                "UPHELD", rationale="Partial restoration is warranted."
            ),
            REVIEWER_ALT,
        )
    )
    assert decided["state"] == APPEAL_UPHELD
    assert decided["decided_by_user_id"] == "reviewer-r2"

    restored = validate_success(api.get_content_item(item["id"], REVIEWER_ALT))
    assert restored["suitability_rating"] == RATING_YELLOW
    assert restored["monetization_state"] == LIMITED
    assert restored["rating_source"] == RATING_SOURCE_APPEAL
    assert restored["last_rated_by_user_id"] is None
    assert restored["open_appeal_count"] == 0


def test_closing_a_window_re_evaluates_every_channel(api):
    """A close with nothing to sweep still re-runs the monetization decision.

    The channel that clears both minimums becomes eligible with no failed
    criteria, and the one that clears neither is marked ineligible on both.

    Design: Corner/state_machines/period_close_reevaluates_every_creator_in_creation_order
    """
    big = new_creator(
        api,
        display_name="Big Creator",
        country_code="US",
        follower_count=50000,
        watch_time_minutes_365d=300000,
    )
    small = new_creator(
        api,
        display_name="Small Creator",
        country_code="GB",
        follower_count=500,
        watch_time_minutes_365d=100,
    )
    period = august_period(api)

    closed = validate_success(api.close_period(period["id"], FINANCE))
    assert closed["status"] == PERIOD_CLOSED
    assert closed["statement_count"] == 0

    cleared = refresh_creator(api, big["id"])
    assert cleared["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    assert cleared["evaluation_count"] == 1
    assert cleared["last_evaluation_failed_criteria"] == []

    refused = refresh_creator(api, small["id"])
    assert refused["eligibility_status"] == ELIGIBILITY_INELIGIBLE
    assert refused["evaluation_count"] == 1
    assert refused["last_evaluation_failed_criteria"] == [
        FAILED_CRITERION_FOLLOWER,
        FAILED_CRITERION_WATCH_TIME,
    ]


def _finalized_subs_statement(api):
    """A verified channel with one finalized 700000-cent statement."""
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
    statement = finalize(api, statement_for(api, creator["id"], period["id"])["id"])
    return creator, period, statement


def test_a_settled_disbursement_pays_the_statement_and_the_lifetime_total(api):
    """Success is recorded on the payout, the statement and the channel at once.

    The three ledger rows leave the channel with nothing payable, the failure
    counter untouched and the disbursement state back to accruing.

    Design: Corner/state_machines/payout_pending_to_processing_to_paid_cascades_statement_and_lifetime_paid
    """
    creator, _period, statement = _finalized_subs_statement(api)
    payout = get_success_data(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE)
    )

    submitted = validate_success(api.submit_payout(payout["id"], FINANCE))
    assert submitted["state"] == PAYOUT_PROCESSING
    assert_instant(submitted["submitted_at"], "2026-08-01T00:00:00Z")

    settled = validate_success(
        api.record_settlement(
            payout["id"], fac.settlement_payload("SUCCEEDED"), FINANCE
        )
    )
    assert settled["state"] == PAYOUT_PAID
    assert_instant(settled["settled_at"], "2026-08-01T00:00:00Z")
    assert validate_success(api.get_statement(statement["id"], FINANCE))["status"] == (
        STATEMENT_PAID
    )

    after = refresh_creator(api, creator["id"])
    assert after["lifetime_paid_cents"] == 699900
    assert after["consecutive_payment_failures"] == 0
    assert after["payout_state"] == PAYOUT_STATE_ACCRUING
    assert after["ledger_balance_cents"] == 0
    assert after["statement_payable_cents"] == 0
    assert after["available_balance_cents"] == 0
    assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 3)


def test_a_failed_settlement_reverses_the_debit_and_the_fee_together(api):
    """The single reversal is the amount plus the fee, and the statement returns.

    Nothing was paid, the failure counter advances by one, the statement is
    detached with its finalized status intact, and the whole payable is available
    again.

    Design: Corner/state_machines/payout_processing_to_failed_reverses_debit_and_detaches_statement
    """
    creator, _period, statement = _finalized_subs_statement(api)
    payout = get_success_data(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE)
    )
    get_success_data(api.submit_payout(payout["id"], FINANCE))

    failed = validate_success(
        api.record_settlement(
            payout["id"],
            fac.settlement_payload("FAILED", failure_code=FAILURE_CODE_BANK_REJECTED),
            FINANCE,
        )
    )
    assert failed["state"] == PAYOUT_FAILED
    assert failed["failure_code"] == FAILURE_CODE_BANK_REJECTED
    assert failed["retry_count"] == 0
    assert failed["amount_cents"] == 699900
    assert failed["fee_cents"] == 100

    rows = assert_total_count(
        api.list_ledger_entries(
            creator["id"], FINANCE, {"entry_type": ENTRY_PAYOUT_REVERSAL}
        ),
        1,
    )
    assert rows[0]["amount_cents"] == 700000
    assert rows[0]["source_entity"] == SOURCE_PAYOUT
    assert rows[0]["source_id"] == payout["id"]

    detached = validate_success(api.get_statement(statement["id"], FINANCE))
    assert detached["payout_id"] is None
    assert detached["status"] == STATEMENT_FINALIZED

    after = refresh_creator(api, creator["id"])
    assert after["consecutive_payment_failures"] == 1
    assert after["lifetime_paid_cents"] == 0
    assert after["payout_state"] == PAYOUT_STATE_ACCRUING
    assert after["available_balance_cents"] == 700000


def test_clearing_a_case_releases_the_hold_and_issues_no_strike(api):
    """A cleared case records its finding, its resolver and no clawback at all.

    The channel keeps its eligibility and its whole payable, nothing is held and
    no clawback is outstanding.

    Design: Corner/state_machines/investigation_open_to_cleared_releases_hold_without_strike
    """
    creator, _period, _statement = _finalized_subs_statement(api)
    investigation = get_success_data(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Suspected inorganic engagement in August",
                violation_window_start="2026-08-02T00:00:00Z",
                violation_window_end="2026-08-09T00:00:00Z",
                hold_payouts=True,
            ),
            REVIEWER,
        )
    )

    cleared = validate_success(
        api.clear_investigation(
            investigation["id"],
            fac.clear_payload(
                finding="Traffic patterns were organic after manual review."
            ),
            REVIEWER_ALT,
        )
    )
    assert cleared["state"] == INVESTIGATION_CLEARED
    assert cleared["finding"] == "Traffic patterns were organic after manual review."
    assert cleared["resolved_by_user_id"] == "reviewer-r2"
    assert_instant(cleared["resolved_at"], "2026-08-01T00:00:00Z")
    assert cleared["clawback_base_cents"] == 0
    assert cleared["clawback_recovered_cents"] == 0

    after = refresh_creator(api, creator["id"])
    assert after["held_cents"] == 0
    assert after["available_balance_cents"] == 700000
    assert after["payout_state"] == PAYOUT_STATE_ACCRUING
    assert after["active_strike_count"] == 0
    assert after["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    assert after["outstanding_clawback_cents"] == 0


def test_a_strike_suspends_the_channel_without_touching_the_cash_state(api):
    """The two channel dimensions move independently under a strike.

    The strike is stamped, counted and re-evaluates the channel as failing policy
    compliance, while the disbursement state stays accruing.

    Design: Corner/state_machines/policy_strike_stamps_last_strike_at_and_suspends_only_eligibility
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    validate_success(api.evaluate_creator(creator["id"], FINANCE))

    struck = validate_success(
        api.create_policy_strike(
            creator["id"],
            fac.policy_strike_payload(
                reason="Third confirmed reuse of licensed footage."
            ),
            REVIEWER,
        ),
        200,
    )
    assert struck["eligibility_status"] == ELIGIBILITY_SUSPENDED
    assert struck["payout_state"] == PAYOUT_STATE_ACCRUING
    assert struck["active_strike_count"] == 1
    assert_instant(struck["last_strike_at"], "2026-08-01T00:00:00Z")
    assert struck["evaluation_count"] == 2
    assert struck["last_evaluation_failed_criteria"] == [FAILED_CRITERION_POLICY]
