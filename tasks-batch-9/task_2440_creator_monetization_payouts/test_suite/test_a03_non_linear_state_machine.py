"""Cyclic and forking lifecycles must not be flattened into a line."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import (
    assert_instant,
    assert_total_count,
    assert_dimensions,
)
from test_helpers.constants import (
    APPEAL_INFO_REQUESTED,
    APPEAL_SUBMITTED,
    DEMONETIZED,
    ELIGIBILITY_SUSPENDED,
    ENTRY_ACCRUAL,
    ENTRY_PAYOUT_DEBIT,
    ENTRY_PAYOUT_FEE,
    ENTRY_PAYOUT_REVERSAL,
    FAILURE_CODE_ACCOUNT_CLOSED,
    FAILURE_CODE_BANK_REJECTED,
    PAYOUT_ABANDONED,
    PAYOUT_FAILED,
    PAYOUT_PROCESSING,
    PAYOUT_STATE_ACCRUING,
    PAYOUT_STATE_IN_FLIGHT,
    RATING_RED,
)
from test_helpers.fixtures import (
    august_period,
    content_item,
    eligible_creator,
    finalized_statement,
    ledger_rows,
    pending_payout,
    refresh_creator,
    tips_product,
)
from test_helpers.test_users import ADMIN, FINANCE, REVIEWER, REVIEWER_ALT, make_creator_headers


def _appeal_at_second_information_request(api):
    """Walk an appeal through two full information cycles."""
    creator = eligible_creator(api)
    item = content_item(api, creator["id"], title="Contested Clip")
    get_success_data(
        api.rate_content_item(item["id"], fac.rate_payload(RATING_RED), REVIEWER)
    )
    creator_headers = make_creator_headers(creator["id"])
    appeal = validate_success(
        api.create_appeal(fac.appeal_payload(item["id"]), creator_headers), 201
    )
    assert appeal["revision_round"] == 0

    rounds = []
    for text in ("Round one evidence.", "Round two evidence."):
        get_success_data(api.start_appeal_review(appeal["id"], REVIEWER_ALT))
        get_success_data(
            api.request_appeal_info(
                appeal["id"], fac.request_info_payload(), REVIEWER_ALT
            )
        )
        rounds.append(
            get_success_data(
                api.respond_to_appeal(
                    appeal["id"], fac.respond_payload(response_statement=text), creator_headers
                )
            )
        )
    get_success_data(api.start_appeal_review(appeal["id"], REVIEWER_ALT))
    get_success_data(
        api.request_appeal_info(
            appeal["id"],
            fac.request_info_payload(info_request="Third request for the licence."),
            REVIEWER_ALT,
        )
    )
    return creator, item, appeal, rounds


def test_the_appeal_cycle_returns_to_submitted_at_every_revision_round(api):
    """The same appeal is submitted at revision round zero, one and two.

    Each information request followed by a channel response returns the appeal
    to the submitted state with its revision counter one higher, which no
    linear lifecycle can produce.

    Design: Difficulty/non_linear_state_machine/appeal_info_request_cycle_exhausts_revision_rounds
    """
    _creator, _item, _appeal, rounds = _appeal_at_second_information_request(api)

    assert [r["revision_round"] for r in rounds] == [1, 2]
    assert [r["state"] for r in rounds] == [APPEAL_SUBMITTED, APPEAL_SUBMITTED]
    assert rounds[-1]["response_statement"] == "Round two evidence."


def test_a_third_response_is_refused_and_parks_the_appeal(api):
    """Exactly two responses are admissible, so the third is rejected.

    The appeal stays parked in the information-requested state with its
    decision fields still empty and its content item still under one open
    appeal, so a second appeal on the same item is refused as well.

    Design: Difficulty/non_linear_state_machine/appeal_info_request_cycle_exhausts_revision_rounds
    """
    creator, item, appeal, _rounds = _appeal_at_second_information_request(api)
    creator_headers = make_creator_headers(creator["id"])

    response = api.respond_to_appeal(
        appeal["id"],
        fac.respond_payload(response_statement="Round three evidence."),
        creator_headers,
    )
    validate_error(response, err.ERR_APPEAL_ROUNDS_EXHAUSTED, 409)

    # PRD 4: GET /monetization/appeals/{appeal_id} authorizes Creator,
    # PolicyReviewer, PlatformAdmin and Auditor — not FinanceOperator.
    parked = validate_success(api.get_appeal(appeal["id"], ADMIN))
    assert parked["state"] == APPEAL_INFO_REQUESTED
    assert parked["revision_round"] == 2
    assert parked["response_statement"] == "Round two evidence."
    assert parked["info_request"] == "Third request for the licence."
    assert parked["decided_by_user_id"] is None
    assert parked["decided_at"] is None
    assert parked["rationale"] is None

    reloaded_item = validate_success(api.get_content_item(item["id"], FINANCE))
    assert reloaded_item["open_appeal_count"] == 1
    assert reloaded_item["suitability_rating"] == RATING_RED
    assert reloaded_item["monetization_state"] == DEMONETIZED
    validate_error(
        api.create_appeal(fac.appeal_payload(item["id"]), creator_headers),
        err.ERR_APPEAL_ALREADY_OPEN,
        409,
    )


def _fail(api, payout_id, failure_code=FAILURE_CODE_BANK_REJECTED):
    return get_success_data(
        api.record_settlement(
            payout_id,
            fac.settlement_payload("FAILED", failure_code=failure_code),
            FINANCE,
        )
    )


def test_each_retry_reuses_the_frozen_fee_and_amount(api):
    """A retry re-debits the identical amount and fee it first snapshotted.

    Two failure-and-retry cycles leave the payout processing with a retry
    count of two while the 19800-cent amount and 200-cent fee never move.

    Design: Difficulty/non_linear_state_machine/payout_retry_cycle_forks_to_abandoned_on_exhaustion
    """
    ctx = pending_payout(api)
    payout = ctx["payout"]
    assert payout["payable_before_fee_cents"] == 20000
    assert payout["fee_cents"] == 200
    assert payout["amount_cents"] == 19800

    get_success_data(api.submit_payout(payout["id"], FINANCE))
    first_failure = _fail(api, payout["id"])
    assert first_failure["state"] == PAYOUT_FAILED
    assert first_failure["retry_count"] == 0

    first_retry = validate_success(api.retry_payout(payout["id"], FINANCE))
    assert first_retry["state"] == PAYOUT_PROCESSING
    assert first_retry["retry_count"] == 1
    assert first_retry["failure_code"] is None

    _fail(api, payout["id"])
    second_retry = validate_success(api.retry_payout(payout["id"], FINANCE))
    assert second_retry["state"] == PAYOUT_PROCESSING
    assert second_retry["retry_count"] == 2
    assert second_retry["fee_cents"] == 200
    assert second_retry["amount_cents"] == 19800


def test_the_third_failure_forks_to_abandoned_instead_of_failed(api):
    """With the retry budget spent, failure lands on the terminal branch.

    The payout is abandoned with a settlement stamp, a further retry is
    refused, and the three debit-fee-reversal triples leave the ledger back at
    the original 20000-cent accrual.

    Design: Difficulty/non_linear_state_machine/payout_retry_cycle_forks_to_abandoned_on_exhaustion
    """
    ctx = pending_payout(api)
    payout = ctx["payout"]
    get_success_data(api.submit_payout(payout["id"], FINANCE))
    _fail(api, payout["id"])
    validate_success(api.retry_payout(payout["id"], FINANCE))
    _fail(api, payout["id"])
    validate_success(api.retry_payout(payout["id"], FINANCE))

    abandoned = _fail(api, payout["id"], FAILURE_CODE_ACCOUNT_CLOSED)
    assert abandoned["state"] == PAYOUT_ABANDONED
    assert abandoned["retry_count"] == 2
    assert abandoned["failure_code"] == FAILURE_CODE_ACCOUNT_CLOSED
    assert_instant(abandoned["settled_at"], "2026-08-01T00:00:00Z")

    validate_error(
        api.retry_payout(payout["id"], FINANCE), err.ERR_PAYOUT_NOT_FAILED, 409
    )

    creator = refresh_creator(api, ctx["creator"]["id"])
    assert creator["consecutive_payment_failures"] == 3
    assert creator["ledger_balance_cents"] == 20000

    rows = assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 10)
    counts = {}
    for row in rows:
        counts[row["entry_type"]] = counts.get(row["entry_type"], 0) + 1
    assert counts == {
        ENTRY_ACCRUAL: 1,
        ENTRY_PAYOUT_DEBIT: 3,
        ENTRY_PAYOUT_FEE: 3,
        ENTRY_PAYOUT_REVERSAL: 3,
    }
    assert sum(r["amount_cents"] for r in rows) == 20000


def test_a_suspended_channel_is_still_disbursable(api):
    """Suspension is an earning verdict and leaves disbursement untouched.

    A strike drives eligibility to suspended while the disbursement dimension
    stays accruing, so the very same payout is created for 19800 cents and
    moves the channel into the in-flight state.

    Design: Difficulty/non_linear_state_machine/creator_eligibility_and_payout_state_are_independent_dimensions
    """
    ctx = finalized_statement(api)
    struck = get_success_data(
        api.create_policy_strike(
            ctx["creator"]["id"], fac.policy_strike_payload(), REVIEWER
        )
    )
    assert_dimensions(
        struck,
        eligibility_status=ELIGIBILITY_SUSPENDED,
        payout_state=PAYOUT_STATE_ACCRUING,
    )
    assert struck["available_balance_cents"] == 20000

    payout = validate_success(
        api.create_payout(fac.payout_payload(ctx["creator"]["id"]), FINANCE), 201
    )
    assert payout["fee_cents"] == 200
    assert payout["amount_cents"] == 19800

    after = refresh_creator(api, ctx["creator"]["id"])
    assert_dimensions(
        after,
        eligibility_status=ELIGIBILITY_SUSPENDED,
        payout_state=PAYOUT_STATE_IN_FLIGHT,
    )


def test_a_suspended_channel_can_no_longer_accrue(api):
    """The earning gate reads only the eligibility dimension.

    After the strike a fresh revenue event is refused as ineligible even
    though the channel is mid-disbursement, and no second event is stored.

    Design: Difficulty/non_linear_state_machine/creator_eligibility_and_payout_state_are_independent_dimensions
    """
    ctx = finalized_statement(api)
    get_success_data(
        api.create_policy_strike(
            ctx["creator"]["id"], fac.policy_strike_payload(), REVIEWER
        )
    )
    validate_success(
        api.create_payout(fac.payout_payload(ctx["creator"]["id"]), FINANCE), 201
    )
    august_period(api)

    response = api.create_revenue_event(
        fac.revenue_event_payload(
            ctx["creator"]["id"],
            ctx["product"]["id"],
            occurred_at="2026-08-01T00:00:00Z",
        ),
        FINANCE,
    )
    validate_error(response, err.ERR_CREATOR_NOT_ELIGIBLE, 409)
    assert_total_count(
        api.list_revenue_events(FINANCE, {"creator_id": ctx["creator"]["id"]}), 1
    )
