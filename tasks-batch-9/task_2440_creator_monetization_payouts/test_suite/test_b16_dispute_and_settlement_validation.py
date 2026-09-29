"""Bounds on cases, dispute adjustments, settlement outcomes and retries."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_instant, assert_total_count
from test_helpers.constants import (
    ENTRY_PAYOUT_REVERSAL,
    FAILURE_CODE_BANK_REJECTED,
    INVESTIGATION_OPEN,
    PAYOUT_FAILED,
    PAYOUT_METHOD_BANK_TRANSFER,
    PAYOUT_PENDING,
    PAYOUT_PROCESSING,
    PAYOUT_STATE_ACCRUING,
    PAYOUT_STATE_IN_FLIGHT,
    PRODUCT_TYPE_TIPS,
    STATEMENT_FINALIZED,
    STATEMENT_UNDER_DISPUTE,
)
from test_helpers.fixtures import (
    august_period,
    eligible_creator,
    new_creator,
    payable_creator,
    post_event,
    refresh_creator,
    statement_for,
    subs_product,
    tips_product,
)
from test_helpers.test_users import FINANCE, REVIEWER, make_creator_headers


def test_a_case_window_cannot_end_before_it_starts(api):
    """A backwards window is refused and opens no case.

    Design: Corner/validations/investigation_window_end_before_start_is_rejected
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")

    validate_error(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Backwards window",
                violation_window_start="2026-08-10T00:00:00Z",
                violation_window_end="2026-08-09T00:00:00Z",
            ),
            REVIEWER,
        ),
        err.ERR_INVESTIGATION_WINDOW_INVALID,
        422,
    )
    assert_total_count(
        api.list_investigations(REVIEWER, {"creator_id": creator["id"]}), 0
    )
    assert refresh_creator(api, creator["id"])["payout_state"] == PAYOUT_STATE_ACCRUING


def test_a_case_window_may_be_a_single_instant(api):
    """A window whose ends coincide is accepted.

    Design: Corner/validations/investigation_single_instant_window_is_accepted
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")

    opened = validate_success(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Single instant review",
                violation_window_start="2026-08-10T00:00:00Z",
                violation_window_end="2026-08-10T00:00:00Z",
                hold_payouts=False,
            ),
            REVIEWER,
        ),
        201,
    )
    assert opened["state"] == INVESTIGATION_OPEN
    assert_instant(opened["violation_window_start"], "2026-08-10T00:00:00Z")
    assert_instant(opened["violation_window_end"], "2026-08-10T00:00:00Z")
    assert opened["opened_by_user_id"] == "reviewer-r1"
    assert opened["hold_amount_cents"] == 0


def _disputed_statement(api):
    """A finalized 700000-cent statement with a 100000-cent claim outstanding."""
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
    get_success_data(
        api.dispute_statement(
            statement["id"],
            fac.dispute_payload(
                100000, dispute_reason="Two sponsorship events are missing"
            ),
            make_creator_headers(creator["id"]),
        )
    )
    return creator, statement


def test_a_rejected_dispute_may_not_grant_anything(api):
    """A rejection carrying money is refused and the claim stays open.

    Design: Corner/validations/rejected_dispute_resolution_requires_a_zero_adjustment
    """
    _creator, statement = _disputed_statement(api)

    validate_error(
        api.resolve_dispute(
            statement["id"], fac.resolve_dispute_payload("REJECTED", 50000), FINANCE
        ),
        err.ERR_ADJUSTMENT_OUT_OF_BOUNDS,
        422,
    )
    reloaded = validate_success(api.get_statement(statement["id"], FINANCE))
    assert reloaded["status"] == STATEMENT_UNDER_DISPUTE
    assert reloaded["dispute_adjustment_cents"] == 0
    assert reloaded["net_payable_cents"] == 532000


def test_an_upheld_dispute_must_grant_a_positive_amount_within_the_claim(api):
    """Both a cent above the claim and a zero grant are refused.

    Design: Corner/validations/upheld_dispute_adjustment_cannot_exceed_the_claim
    """
    creator, statement = _disputed_statement(api)

    validate_error(
        api.resolve_dispute(
            statement["id"], fac.resolve_dispute_payload("UPHELD", 100001), FINANCE
        ),
        err.ERR_ADJUSTMENT_OUT_OF_BOUNDS,
        422,
    )
    validate_error(
        api.resolve_dispute(
            statement["id"], fac.resolve_dispute_payload("UPHELD", 0), FINANCE
        ),
        err.ERR_ADJUSTMENT_OUT_OF_BOUNDS,
        422,
    )
    reloaded = validate_success(api.get_statement(statement["id"], FINANCE))
    assert reloaded["status"] == STATEMENT_UNDER_DISPUTE
    assert reloaded["dispute_adjustment_cents"] == 0
    assert refresh_creator(api, creator["id"])["ledger_balance_cents"] == 532000


def _processing_payout(api):
    """A verified channel whose 699900-cent disbursement is on the rail."""
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
    return creator, statement, payout


def test_a_failed_settlement_must_name_its_failure_code(api):
    """The codeless failure is refused and reverses nothing.

    Design: Corner/validations/failed_settlement_without_a_failure_code_is_rejected
    """
    creator, _statement, payout = _processing_payout(api)

    validate_error(
        api.record_settlement(payout["id"], {"outcome": "FAILED"}, FINANCE),
        err.ERR_FAILURE_CODE_REQUIRED,
        422,
    )
    reloaded = validate_success(api.get_payout(payout["id"], FINANCE))
    assert reloaded["state"] == PAYOUT_PROCESSING
    assert reloaded["failure_code"] is None
    assert reloaded["retry_count"] == 0
    assert_total_count(
        api.list_ledger_entries(
            creator["id"], FINANCE, {"entry_type": ENTRY_PAYOUT_REVERSAL}
        ),
        0,
    )
    assert refresh_creator(api, creator["id"])["consecutive_payment_failures"] == 0


def test_a_successful_settlement_may_not_name_a_failure_code(api):
    """The contradictory settlement is refused and pays nothing.

    Design: Corner/validations/succeeded_settlement_with_a_failure_code_is_rejected
    """
    creator, statement, payout = _processing_payout(api)

    validate_error(
        api.record_settlement(
            payout["id"],
            fac.settlement_payload(
                "SUCCEEDED", failure_code=FAILURE_CODE_BANK_REJECTED
            ),
            FINANCE,
        ),
        err.ERR_FAILURE_CODE_FORBIDDEN,
        422,
    )
    reloaded = validate_success(api.get_payout(payout["id"], FINANCE))
    assert reloaded["state"] == PAYOUT_PROCESSING
    assert reloaded["settled_at"] is None
    assert refresh_creator(api, creator["id"])["lifetime_paid_cents"] == 0
    assert validate_success(api.get_statement(statement["id"], FINANCE))["status"] == (
        STATEMENT_FINALIZED
    )


def test_a_retry_is_blocked_when_a_dispute_has_taken_the_balance_away(api):
    """Disputing the detached statement leaves nothing to retry with.

    Design: Corner/validations/retry_blocked_when_a_dispute_removes_the_restored_balance
    """
    creator, statement, payout = _processing_payout(api)
    get_success_data(
        api.record_settlement(
            payout["id"],
            fac.settlement_payload("FAILED", failure_code=FAILURE_CODE_BANK_REJECTED),
            FINANCE,
        )
    )
    get_success_data(
        api.dispute_statement(
            statement["id"],
            fac.dispute_payload(700000, dispute_reason="The whole statement is wrong"),
            make_creator_headers(creator["id"]),
        )
    )

    validate_error(
        api.retry_payout(payout["id"], FINANCE),
        err.ERR_INSUFFICIENT_BALANCE_FOR_RETRY,
        422,
    )
    reloaded = validate_success(api.get_payout(payout["id"], FINANCE))
    assert reloaded["state"] == PAYOUT_FAILED
    assert reloaded["retry_count"] == 0
    assert reloaded["amount_cents"] == 699900
    assert reloaded["fee_cents"] == 100

    reloaded_statement = validate_success(api.get_statement(statement["id"], FINANCE))
    assert reloaded_statement["status"] == STATEMENT_UNDER_DISPUTE
    assert reloaded_statement["payout_id"] is None
    assert refresh_creator(api, creator["id"])["available_balance_cents"] == 0


def test_a_balance_exactly_at_the_threshold_is_payable(api):
    """The threshold is inclusive, so a balance equal to it is disbursed.

    Design: Corner/validations/payout_at_a_balance_exactly_equal_to_the_threshold_is_accepted
    """
    creator, _profile = payable_creator(
        api, display_name="Ada Ads", payout_threshold_cents=1000
    )
    period = august_period(api)
    product = tips_product(
        api,
        product_type=PRODUCT_TYPE_TIPS,
        name="Tip Jar",
        creator_share_bps=1000,
        platform_fee_bps=9000,
    )
    post_event(
        api,
        creator["id"],
        product["id"],
        gross_amount_cents=10000,
        occurred_at="2026-08-05T00:00:00Z",
    )
    get_success_data(api.close_period(period["id"], FINANCE))
    statement = statement_for(api, creator["id"], period["id"])
    get_success_data(api.finalize_statement(statement["id"], FINANCE))

    payout = validate_success(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE), 201
    )
    assert payout["payable_before_fee_cents"] == 1000
    assert payout["method"] == PAYOUT_METHOD_BANK_TRANSFER
    assert payout["fee_cents"] == 200
    assert payout["amount_cents"] == 800
    assert payout["state"] == PAYOUT_PENDING
    assert refresh_creator(api, creator["id"])["payout_state"] == PAYOUT_STATE_IN_FLIGHT
