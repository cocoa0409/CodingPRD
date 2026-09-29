"""A call's legality can depend entirely on the state of another record."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_instant, assert_ledger_sequence, assert_total_count
from test_helpers.constants import (
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_PENDING_REVIEW,
    ELIGIBILITY_SUSPENDED,
    ENTRY_ACCRUAL,
    ENTRY_PAYOUT_DEBIT,
    ENTRY_PAYOUT_FEE,
    ENTRY_WITHHOLDING_TRUE_UP,
    EVENT_ACCRUED,
    INVESTIGATION_CLEARED,
    PAYOUT_PENDING,
    PAYOUT_PROCESSING,
    PAYOUT_STATE_HOLD,
    PAYOUT_STATE_IN_FLIGHT,
    PERIOD_CLOSED,
    PERIOD_FINALIZED,
    PERIOD_OPEN,
    VARIANT_FINAL,
)
from test_helpers.fixtures import (
    close,
    eligible_creator,
    finalize,
    july_period,
    new_creator,
    payable_creator,
    post_event,
    refresh_creator,
    statement_for,
    tips_product,
)
from test_helpers.test_users import ADMIN, FINANCE, REVIEWER, REVIEWER_ALT


def test_the_same_accrual_is_refused_accepted_and_refused_again(api):
    """Only the channel's eligibility changes between three identical posts.

    A channel awaiting review cannot accrue, the very same body succeeds once it
    has been evaluated eligible, and a strike closes the door again without the
    body, the product or the period changing.

    Design: Difficulty/cross_entity_state_dependency/revenue_event_gated_by_creator_eligibility_dimension
    """
    creator = new_creator(api, display_name="Zed Gate")
    assert creator["eligibility_status"] == ELIGIBILITY_PENDING_REVIEW
    product = tips_product(api)
    july_period(api)

    first = api.create_revenue_event(
        fac.revenue_event_payload(creator["id"], product["id"]), FINANCE
    )
    validate_error(first, err.ERR_CREATOR_NOT_ELIGIBLE, 409)

    evaluated = validate_success(api.evaluate_creator(creator["id"], FINANCE))
    assert evaluated["eligibility_status"] == ELIGIBILITY_ELIGIBLE

    accepted = validate_success(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"], product["id"], occurred_at="2026-07-06T00:00:00Z"
            ),
            FINANCE,
        ),
        201,
    )
    assert accepted["creator_share_cents"] == 5000
    assert accepted["status"] == EVENT_ACCRUED

    struck = get_success_data(
        api.create_policy_strike(
            creator["id"],
            fac.policy_strike_payload(reason="Monetising other creators' uploads."),
            REVIEWER,
        )
    )
    assert struck["eligibility_status"] == ELIGIBILITY_SUSPENDED

    third = api.create_revenue_event(
        fac.revenue_event_payload(
            creator["id"], product["id"], occurred_at="2026-07-07T00:00:00Z"
        ),
        FINANCE,
    )
    validate_error(third, err.ERR_CREATOR_NOT_ELIGIBLE, 409)


def test_only_the_accepted_accrual_left_a_trace(api):
    """The two refused attempts stored neither an event nor a ledger row.

    Exactly one event and one ledger entry survive, the balance is the single
    5000-cent share, and the period is still open with no statements.

    Design: Difficulty/cross_entity_state_dependency/revenue_event_gated_by_creator_eligibility_dimension
    """
    creator = new_creator(api, display_name="Zed Gate")
    product = tips_product(api)
    period = july_period(api)

    api.create_revenue_event(
        fac.revenue_event_payload(creator["id"], product["id"]), FINANCE
    )
    validate_success(api.evaluate_creator(creator["id"], FINANCE))
    validate_success(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"], product["id"], occurred_at="2026-07-06T00:00:00Z"
            ),
            FINANCE,
        ),
        201,
    )
    get_success_data(
        api.create_policy_strike(creator["id"], fac.policy_strike_payload(), REVIEWER)
    )
    api.create_revenue_event(
        fac.revenue_event_payload(
            creator["id"], product["id"], occurred_at="2026-07-07T00:00:00Z"
        ),
        FINANCE,
    )

    assert_total_count(
        api.list_revenue_events(FINANCE, {"creator_id": creator["id"]}), 1
    )
    assert refresh_creator(api, creator["id"])["ledger_balance_cents"] == 5000
    assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 1)
    reloaded = validate_success(api.get_period(period["id"], FINANCE))
    assert reloaded["status"] == PERIOD_OPEN
    assert reloaded["statement_count"] == 0


def _held_in_flight_payout(api):
    creator, _profile = payable_creator(api, display_name="Abe Held")
    product = tips_product(api)
    period = july_period(api)
    post_event(api, creator["id"], product["id"], gross_amount_cents=40000)
    close(api, period["id"])
    finalize(api, statement_for(api, creator["id"], period["id"])["id"])
    payout = validate_success(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE), 201
    )
    before = refresh_creator(api, creator["id"])
    investigation = get_success_data(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Advertiser complaint about July tips.",
                violation_window_end="2026-07-31T23:59:59Z",
                hold_payouts=True,
            ),
            REVIEWER,
        )
    )
    return creator, payout, before, investigation


def test_an_open_hold_freezes_a_disbursement_that_already_existed(api):
    """The hold outranks the in-flight clause, so the pending payout cannot go.

    Nothing is held in cash because the statement was already claimed, yet the
    channel moves to the hold state and submitting the existing disbursement is
    refused, leaving it pending and unsubmitted.

    Design: Difficulty/cross_entity_state_dependency/payout_submit_gated_by_creator_hold_from_investigation
    """
    creator, payout, before, investigation = _held_in_flight_payout(api)
    assert payout["amount_cents"] == 19800
    assert before["payout_state"] == PAYOUT_STATE_IN_FLIGHT
    assert investigation["hold_amount_cents"] == 0
    assert refresh_creator(api, creator["id"])["payout_state"] == PAYOUT_STATE_HOLD

    validate_error(
        api.submit_payout(payout["id"], FINANCE), err.ERR_PAYOUT_HELD, 409
    )
    frozen = validate_success(api.get_payout(payout["id"], FINANCE))
    assert frozen["state"] == PAYOUT_PENDING
    assert frozen["submitted_at"] is None


def test_clearing_the_case_releases_the_identical_submission(api):
    """An operation on the case, not on the payout, unblocks the payout.

    Clearing issues no strike and no clawback, the channel drops back to the
    in-flight state, the same submission now succeeds, and neither the refusal
    nor the clearance wrote a ledger entry.

    Design: Difficulty/cross_entity_state_dependency/payout_submit_gated_by_creator_hold_from_investigation
    """
    creator, payout, _before, investigation = _held_in_flight_payout(api)
    api.submit_payout(payout["id"], FINANCE)

    cleared = validate_success(
        api.clear_investigation(
            investigation["id"],
            fac.clear_payload(finding="Complaint withdrawn; tips are legitimate."),
            REVIEWER_ALT,
        )
    )
    assert cleared["state"] == INVESTIGATION_CLEARED
    assert cleared["resolved_by_user_id"] == "reviewer-r2"
    assert cleared["clawback_base_cents"] == 0

    released = refresh_creator(api, creator["id"])
    assert released["payout_state"] == PAYOUT_STATE_IN_FLIGHT
    assert released["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    assert released["active_strike_count"] == 0

    submitted = validate_success(api.submit_payout(payout["id"], FINANCE))
    assert submitted["state"] == PAYOUT_PROCESSING
    assert_instant(submitted["submitted_at"], "2026-08-01T00:00:00Z")

    after = refresh_creator(api, creator["id"])
    assert after["held_cents"] == 0
    assert after["outstanding_clawback_cents"] == 0
    assert after["ledger_balance_cents"] == 0
    rows = assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 3)
    assert_ledger_sequence(
        rows,
        [
            (ENTRY_ACCRUAL, 20000),
            (ENTRY_PAYOUT_DEBIT, -19800),
            (ENTRY_PAYOUT_FEE, -200),
        ],
    )


def _two_statement_period(api):
    first = eligible_creator(api, display_name="Bea One")
    second = eligible_creator(api, display_name="Cal Two")
    product = tips_product(api)
    period = july_period(api)
    post_event(api, first["id"], product["id"], gross_amount_cents=10000)
    post_event(
        api, second["id"], product["id"], gross_amount_cents=20000,
        occurred_at="2026-07-06T00:00:00Z",
    )
    closed = validate_success(api.close_period(period["id"], FINANCE))
    assert closed["status"] == PERIOD_CLOSED
    assert closed["statement_count"] == 2
    assert closed["finalized_statement_count"] == 0
    statement_one = statement_for(api, first["id"], period["id"])
    statement_two = statement_for(api, second["id"], period["id"])
    assert statement_one["net_payable_cents"] == 3800
    assert statement_two["net_payable_cents"] == 7600
    return first, second, period, statement_one, statement_two


def test_a_period_finalizes_only_when_its_last_child_does(api):
    """No endpoint finalizes the period; the children's count does it.

    Finalizing one of two statements leaves the period closed with a count of
    one, and finalizing the second flips the parent to finalized with its close
    stamp untouched.

    Design: Difficulty/cross_entity_state_dependency/period_finalization_derived_from_children_then_blocks_fund_creation
    """
    _first, _second, period, statement_one, statement_two = _two_statement_period(api)

    finalize(api, statement_one["id"])
    midway = validate_success(api.get_period(period["id"], FINANCE))
    assert midway["status"] == PERIOD_CLOSED
    assert midway["finalized_statement_count"] == 1

    finalize(api, statement_two["id"])
    ended = validate_success(api.get_period(period["id"], FINANCE))
    assert ended["status"] == PERIOD_FINALIZED
    assert ended["finalized_statement_count"] == 2
    assert ended["statement_count"] == 2
    assert_instant(ended["closed_at"], "2026-08-01T00:00:00Z")


def test_the_derived_parent_state_then_blocks_a_fourth_record(api):
    """A fund cannot be opened against a period the children finalized.

    The refusal is caused by a state no call in the chain set directly, no fund
    is stored, and both statements sit on the final variant with no true-up.

    Design: Difficulty/cross_entity_state_dependency/period_finalization_derived_from_children_then_blocks_fund_creation
    """
    first, _second, period, statement_one, statement_two = _two_statement_period(api)
    final_one = finalize(api, statement_one["id"])
    final_two = finalize(api, statement_two["id"])

    response = api.create_fund(
        fac.fund_payload(period["id"], name="Too Late Fund"), ADMIN
    )
    validate_error(response, err.ERR_FUND_PERIOD_FINALIZED, 409)
    assert_total_count(api.list_funds(ADMIN), 0)

    assert final_one["withholding_variant"] == VARIANT_FINAL
    assert final_one["withholding_cents"] == 1200
    assert final_one["net_payable_cents"] == 3800
    assert final_two["withholding_variant"] == VARIANT_FINAL
    assert final_two["withholding_cents"] == 2400
    assert final_two["net_payable_cents"] == 7600
    assert_total_count(
        api.list_ledger_entries(
            first["id"], FINANCE, {"entry_type": ENTRY_WITHHOLDING_TRUE_UP}
        ),
        0,
    )
